"""Loopback-only RAG Demo API. Run with the existing M5 Python environment."""
import argparse
import atexit
from collections import Counter
import copy
import csv
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import re
import selectors
import subprocess
import sys
import threading
import time
from urllib.parse import parse_qs, urlsplit
import uuid

ROOT = Path(__file__).resolve().parents[2]
from scripts.m5_generation.api import M5Error, call_api, strict_json
from scripts.m5_generation.token_budget import load_budget_profile
from scripts.m5_live.common import write_json
from scripts.m6_evaluation.protocol_driver import run_protocol_item

CONFIG = {'strategy': 'C', 'mode': 'hybrid', 'top_k': 5, 'candidate_k': 30,
          'rrf_constant': 60, 'context_tokens': 1024, 'packing_policy': 'skip_continue_dedup_v1',
          'application_total_token_limit': 8192, 'safety_margin_tokens': 512, 'network_retries': 0}
TERMINAL = {'completed', 'failed', 'cancelled'}
STAGES = {'generation': 'Generating answer', 'review': 'Reviewing answer',
          'repair_generation': 'Repairing answer', 'repair_review': 'Reviewing repaired answer'}


def load_environment():
    """Load only the gateway settings, never print their contents or evaluate shell syntax."""
    path = ROOT / '.env'
    if path.is_file():
        for line in path.read_text(encoding='utf-8').splitlines():
            key, sep, value = line.partition('=')
            if sep and key.strip() in {'M5_API_BASE', 'M5_API_KEY', 'DEEPSEEK_API_KEY'}:
                value = value.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                    value = value[1:-1]
                os.environ.setdefault(key.strip(), value)


def redact(value):
    text = json.dumps(value, ensure_ascii=False, allow_nan=False)
    for name in ('M5_API_KEY', 'DEEPSEEK_API_KEY', 'OPENAI_API_KEY'):
        secret = os.environ.get(name)
        if secret:
            text = text.replace(json.dumps(secret)[1:-1], '[REDACTED]')
    text = re.sub(r'(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,})', '[REDACTED]', text)
    return json.loads(text)


def validate_questions(rows):
    if not isinstance(rows, list) or not 1 <= len(rows) <= 100:
        raise M5Error('INVALID_QUESTIONS', 'Provide between 1 and 100 questions.')
    seen = set()
    for i, row in enumerate(rows, 1):
        if not isinstance(row, dict) or set(row) != {'id', 'question'}:
            raise M5Error('INVALID_QUESTIONS', f'Row {i}: only id and question are accepted.')
        if any(not isinstance(row[k], str) or not row[k].strip() for k in ('id', 'question')):
            raise M5Error('INVALID_QUESTIONS', f'Row {i}: id and question must be nonempty strings.')
        if len(row['id']) > 120 or len(row['question'].encode('utf-8')) > 8000:
            raise M5Error('INVALID_QUESTIONS', f'Row {i}: id or question exceeds the size limit.')
        if row['id'] in seen:
            raise M5Error('INVALID_QUESTIONS', f'Row {i}: duplicate id.')
        seen.add(row['id'])
    return rows


def percentile(values, p):
    if not values:
        return None
    xs = sorted(values)
    pos = (len(xs) - 1) * p
    lo = int(pos)
    return round(xs[lo] + (xs[min(lo + 1, len(xs) - 1)] - xs[lo]) * (pos - lo), 2)


def summary(task):
    calls = [c for row in task['results'] for c in row.get('calls', [])]
    counts = Counter(r['status'] for r in task['results'])
    times = [c['latency_ms'] for c in calls if isinstance(c.get('latency_ms'), (int, float))]
    def tokens(key):
        if not calls:
            return 0
        return sum(c[key] for c in calls) if all(type(c.get(key)) is int for c in calls) else None
    return {'total': len(task['results']), 'done': counts['completed'], 'failed': counts['failed'],
            'cancelled': counts['cancelled'], 'pending': counts['pending'], 'apiCalls': len(calls),
            'inputTokens': tokens('input_tokens'), 'outputTokens': tokens('output_tokens'),
            'elapsedMs': round((task.get('finishedMonotonic', time.monotonic()) - task['startedMonotonic']) * 1000),
            'medianMs': percentile(times, .5), 'p95Ms': percentile(times, .95), 'cost': None}


def answer_view(pipeline, protocol, elapsed):
    calls = pipeline.get('api_calls') or []
    def tokens(key):
        return sum(c[key] for c in calls) if all(type(c.get(key)) is int for c in calls) else None
    sources = pipeline.get('sources') or (pipeline.get('answer_record') or {}).get('evidence') or []
    result_sources = []
    for i, s in enumerate(sources):
        citation = s.get('citation') or s
        result_sources.append({'id': s.get('source_id', f'S{i+1}'), 'title': citation.get('title', 'Untitled source'),
                               'url': citation.get('url', ''), 'site': citation.get('source_name') or citation.get('source_domain', ''),
                               'date': citation.get('published_at_utc'), 'snippet': s.get('text', '')})
    gate = pipeline.get('gate', 'Unknown')
    return {'content': pipeline.get('answer', ''), 'sources': result_sources,
            'answerStatus': pipeline.get('status'), 'partial': pipeline.get('status') == 'PARTIAL',
            'insufficient': pipeline.get('status') == 'INSUFFICIENT_SOURCES',
            'missingFields': pipeline.get('missing_information') or [],
            'error': (pipeline.get('error') or {}).get('message'), 'errorCode': (pipeline.get('error') or {}).get('code'),
            'calls': calls, 'runDetails': {'protocol': protocol, 'model': pipeline.get('model', 'CS5351/DeepSeek-V4-Flash'),
              'runStatus': pipeline.get('status'), 'outputCheck': gate,
              'autoReview': gate if protocol == 'G2' else 'Not run', 'durationMs': round(elapsed * 1000),
              'apiCalls': len(calls), 'inputTokens': tokens('input_tokens'), 'outputTokens': tokens('output_tokens'),
              'repairCount': int(bool(pipeline.get('repair_used'))), 'cost': None}}


class RetrievalWorker:
    def __init__(self, python, run_root):
        self.python, self.run_root = python, run_root
        self.process = None
        self.lock = threading.Lock()
        self.log = None

    def close(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        if self.log:
            self.log.close()

    def request(self, data):
        with self.lock:
            if self.process is None or self.process.poll() is not None:
                self.run_root.mkdir(parents=True, exist_ok=True)
                self.log = (self.run_root / 'retrieval.log').open('a')
                env = {k: v for k, v in os.environ.items() if not any(s in k.upper() for s in ('KEY', 'TOKEN', 'SECRET', 'PASSWORD'))}
                env.update(PYTHONDONTWRITEBYTECODE='1', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
                self.process = subprocess.Popen([str(self.python), '-B', '-m', 'scripts.demo.worker'], cwd=ROOT,
                       env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.log, text=True, bufsize=1)
                if data['action'] != 'load':
                    raise M5Error('KB_RELOAD_REQUIRED', 'The retrieval process restarted. Reload the knowledge base.')
            try:
                self.process.stdin.write(json.dumps(data) + '\n')
                self.process.stdin.flush()
                with selectors.DefaultSelector() as selector:
                    selector.register(self.process.stdout, selectors.EVENT_READ)
                    if not selector.select(timeout=300):
                        self.close()
                        raise M5Error('RETRIEVAL_TIMEOUT', 'Retrieval timed out. Reload the knowledge base before trying again.')
                line = self.process.stdout.readline()
                if not line:
                    raise M5Error('RETRIEVAL_STOPPED', 'The retrieval process stopped. Reload the knowledge base.')
                response = json.loads(line)
            except (BrokenPipeError, OSError, json.JSONDecodeError):
                raise M5Error('RETRIEVAL_STOPPED', 'Retrieval failed. Reload the knowledge base.') from None
            if not response.get('ok'):
                err = response['error']
                raise M5Error(err['code'], err['message'])
            return response['result']


class Demo:
    def __init__(self, m4_python, runs):
        self.runs = Path(runs)
        self.runs.mkdir(parents=True, exist_ok=True)
        self.worker = RetrievalWorker(m4_python, self.runs)
        self.lock = threading.RLock()
        self.active = None
        self.tasks = {}
        self.kb = {'status': 'unloaded', 'info': None, 'error': None}
        self.default_path = str(ROOT / '.local-m4')
        self.model = load_budget_profile(ROOT / 'configs/m5_budget_cityu_cs5351.json')['model']
        atexit.register(self.worker.close)

    def state(self):
        with self.lock:
            return {'connected': True, 'mode': 'live', 'model': self.model, 'config': CONFIG,
                    'credentialsConfigured': bool(os.getenv('M5_API_BASE') and os.getenv('M5_API_KEY')),
                    'kb': copy.deepcopy(self.kb), 'busy': self.active is not None,
                    'defaultKnowledgeBase': self.default_path}

    def load(self, path):
        if not isinstance(path, str) or not path.strip():
            raise M5Error('INVALID_PATH', 'Select a local knowledge base directory.')
        with self.lock:
            if self.active:
                raise M5Error('BUSY', 'Wait for the current task before changing the knowledge base.')
            self.active = 'load'
            self.kb = {'status': 'loading', 'info': None, 'error': None}
        def run():
            try:
                info = self.worker.request({'action': 'load', 'path': str(Path(path).expanduser().resolve()),
                                            'run_dir': str(self.runs / ('load_' + uuid.uuid4().hex))})
                info['loadTime'] = datetime.now().astimezone().isoformat(timespec='seconds')
                info['id'] = uuid.uuid4().hex
                with self.lock:
                    self.kb = {'status': 'loaded', 'info': info, 'error': None}
            except Exception as exc:
                with self.lock:
                    self.kb = {'status': 'error', 'info': None, 'error': str(exc) if isinstance(exc, M5Error) else 'Knowledge base loading failed.'}
            finally:
                with self.lock:
                    self.active = None
        threading.Thread(target=run, daemon=True).start()
        return {'accepted': True}

    def public_task(self, task):
        data = {k: copy.deepcopy(v) for k, v in task.items() if k not in {'cancel', 'startedMonotonic', 'finishedMonotonic'}}
        data['stats'] = summary(task)
        return redact(data)

    def save_task(self, task):
        write_json(self.runs / task['id'] / 'task.json', self.public_task(task))

    def get_task(self, ident):
        with self.lock:
            if ident in self.tasks:
                return self.public_task(self.tasks[ident])
        if re.fullmatch(r'[0-9a-f]{32}', ident):
            path = self.runs / ident / 'task.json'
            if path.is_file():
                data = json.loads(path.read_text())
                if data['status'] not in TERMINAL:
                    data.update(status='failed', stage='Interrupted by server restart')
                    for row in data['results']:
                        if row['status'] == 'running':
                            row.update(status='failed', error='Server restarted; provider outcome may be unknown.')
                    data['interrupted'] = True
                return data
        raise M5Error('NOT_FOUND', 'Task not found.')

    def start(self, data):
        rows = validate_questions(data.get('questions'))
        protocol = data.get('protocol')
        if protocol not in {'G0', 'G1', 'G2'}:
            raise M5Error('INVALID_PROTOCOL', 'Choose G0, G1 or G2.')
        from scripts.m5_generation.api import read_key
        read_key()  # Fail before starting any task if gateway configuration is missing.
        with self.lock:
            if self.active:
                raise M5Error('BUSY', 'Another task is running. Wait or stop it first.')
            if self.kb['status'] != 'loaded' or data.get('knowledgeBaseId') != self.kb['info']['id']:
                raise M5Error('KB_REQUIRED', 'Load the selected knowledge base before starting a task.')
            ident = uuid.uuid4().hex
            task = {'id': ident, 'status': 'running', 'stage': 'Starting', 'protocol': protocol, 'model': self.model,
                    'knowledgeBase': copy.deepcopy(self.kb['info']), 'createdAt': datetime.now(timezone.utc).isoformat(),
                    'startedMonotonic': time.monotonic(), 'cancel': threading.Event(), 'stopping': False,
                    'results': [dict(r, status='pending', content='', calls=[], sources=[], durationMs=None) for r in rows]}
            self.tasks[ident] = task
            self.active = ident
            self.save_task(task)
            threading.Thread(target=self.run, args=(task,), daemon=True).start()
            return self.public_task(task)

    def run(self, task):
        for index, row in enumerate(task['results']):
            if task['cancel'].is_set():
                break
            started = time.monotonic()
            with self.lock:
                row['status'] = 'running'
                task['stage'] = 'Retrieving evidence'
                self.save_task(task)
            folder = self.runs / task['id'] / f'item_{index+1:04d}'
            try:
                retrieved = self.worker.request({'action': 'retrieve', 'question': row['question']})
                write_json(folder / 'retrieval.json', retrieved['packed'])
                write_json(folder / 'packing.json', retrieved['audit'])
                if task['cancel'].is_set():
                    with self.lock:
                        row['status'] = 'cancelled'
                    break
                def checkpoint(pipeline):
                    safe = redact(pipeline)
                    write_json(folder / 'pipeline.json', safe)
                    with self.lock:
                        row['calls'] = safe.get('api_calls') or []
                        if row['calls']:
                            task['stage'] = STAGES.get(row['calls'][-1]['stage'], 'Processing')
                        self.save_task(task)
                def transport(payload, key):
                    if task['cancel'].is_set():
                        raise M5Error('CANCELLED', 'Stopped before the next model call; earlier calls remain recorded.')
                    return call_api(payload, key)
                with self.lock:
                    task['stage'] = 'Generating answer'
                pipeline = run_protocol_item(retrieved['packed'], task['protocol'], model=self.model,
                                             network_retries=0, api_call=transport, checkpoint=checkpoint)
                checkpoint(pipeline)
                result = answer_view(pipeline, task['protocol'], time.monotonic() - started)
                with self.lock:
                    row.update(redact(result))
                    row['status'] = ('cancelled' if result['errorCode'] == 'CANCELLED' else
                                     'failed' if pipeline.get('status') == 'ERROR' else 'completed')
            except Exception as exc:
                with self.lock:
                    row.update(status='failed', error=str(exc) if isinstance(exc, M5Error) else 'The task failed. Check local runtime files.',
                               errorCode=getattr(exc, 'code', 'TASK_FAILED'))
            finally:
                with self.lock:
                    row['durationMs'] = round((time.monotonic() - started) * 1000)
                    self.save_task(task)
        with self.lock:
            task['finishedMonotonic'] = time.monotonic()
            task['status'] = 'cancelled' if task['cancel'].is_set() else 'completed'
            for row in task['results']:
                if row['status'] == 'running':
                    row['status'] = 'cancelled'
            task['stage'] = 'Stopped' if task['status'] == 'cancelled' else 'Finished'
            task['stopping'] = False
            self.active = None
            self.save_task(task)

    def stop(self, ident):
        with self.lock:
            task = self.tasks.get(ident)
            if not task:
                raise M5Error('NOT_FOUND', 'Task not found.')
            if task['status'] not in TERMINAL:
                task['cancel'].set()
                task['stopping'] = True
                task['stage'] = 'Stopping after the current operation'
            return self.public_task(task)


def export_task(task, fmt):
    rows = task['results']
    if fmt == 'json':
        return json.dumps(task, ensure_ascii=False, indent=2), 'application/json', 'json'
    if fmt == 'jsonl':
        return '\n'.join(json.dumps(r, ensure_ascii=False) for r in rows) + '\n', 'application/x-ndjson', 'jsonl'
    if fmt == 'csv':
        output = io.StringIO(newline='')
        fields = ['id', 'question', 'status', 'answerStatus', 'content', 'error', 'durationMs']
        writer = csv.DictWriter(output, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        for original in rows:
            row = dict(original, answerStatus=original.get('answerStatus') or (original.get('runDetails') or {}).get('runStatus'))
            # Prevent executable spreadsheet formulas in user/model text.
            safe = {k: ("'" + v if isinstance(v, str) and v.lstrip().startswith(('=', '+', '-', '@')) else v)
                    for k, v in row.items() if k in fields}
            writer.writerow(safe)
        return output.getvalue(), 'text/csv; charset=utf-8', 'csv'
    raise M5Error('INVALID_FORMAT', 'Choose json, jsonl or csv.')


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # Never log request bodies, queries or credentials.

    def respond(self, data, code=200):
        body = json.dumps(redact(data), ensure_ascii=False, allow_nan=False).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(body)

    def handle_api(self):
        parsed = urlsplit(self.path)
        path = parsed.path
        if self.headers.get('Host') not in self.server.allowed_hosts:
            raise M5Error('FORBIDDEN', 'Only local requests are accepted.')
        origin = self.headers.get('Origin')
        if origin and origin not in self.server.allowed_origins:
            raise M5Error('FORBIDDEN', 'Cross-origin requests are not accepted.')
        if self.headers.get('Sec-Fetch-Site') == 'cross-site':
            raise M5Error('FORBIDDEN', 'Cross-site requests are not accepted.')
        demo = self.server.demo
        if self.command == 'GET':
            if path == '/api/status':
                return self.respond(demo.state())
            if path == '/api/directories':
                query = parse_qs(parsed.query)
                directory = Path(query.get('path', [demo.default_path])[0]).expanduser().resolve()
                if not directory.is_dir():
                    raise M5Error('INVALID_PATH', 'Directory not found.')
                children = sorted([p for p in directory.iterdir() if p.is_dir() and not p.name.startswith('.')], key=lambda p: p.name.lower())
                return self.respond({'path': str(directory), 'parent': str(directory.parent),
                    'directories': [{'name': p.name, 'path': str(p)} for p in children[:200]], 'default': demo.default_path})
            match = re.fullmatch(r'/api/tasks/([0-9a-f]{32})(/export)?', path)
            if match:
                task = demo.get_task(match[1])
                if not match[2]:
                    return self.respond(task)
                text, content_type, ext = export_task(task, parse_qs(parsed.query).get('format', ['json'])[0])
                payload = text.encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', content_type)
                self.send_header('Content-Length', str(len(payload)))
                self.send_header('Content-Disposition', f'attachment; filename="rag-{match[1]}.{ext}"')
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                self.wfile.write(payload)
                return
        if self.command == 'POST':
            if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                raise M5Error('INVALID_CONTENT_TYPE', 'Send application/json.')
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 1_000_000:
                raise M5Error('INVALID_BODY', 'Request body must be at most 1 MB.')
            data = strict_json(self.rfile.read(length).decode('utf-8'))
            if not isinstance(data, dict):
                raise M5Error('INVALID_BODY', 'Expected a JSON object.')
            if path == '/api/knowledge-base/load':
                return self.respond(demo.load(data.get('path')), 202)
            if path == '/api/knowledge-base/unload':
                with demo.lock:
                    if demo.active:
                        raise M5Error('BUSY', 'Wait for the current task before unloading.')
                    demo.kb = {'status': 'unloaded', 'info': None, 'error': None}
                return self.respond({'ok': True})
            if path == '/api/questions/validate':
                text = data.get('text')
                if not isinstance(text, str):
                    raise M5Error('INVALID_QUESTIONS', 'Select a JSONL text file.')
                rows = []
                for line_no, line in enumerate(text.splitlines(), 1):
                    if not line.strip():
                        continue
                    try:
                        rows.append(strict_json(line.lstrip('\ufeff')))
                    except M5Error:
                        raise M5Error('INVALID_QUESTIONS', f'Line {line_no}: invalid JSON.') from None
                return self.respond({'questions': validate_questions(rows)})
            if path == '/api/tasks':
                return self.respond(demo.start(data), 202)
            match = re.fullmatch(r'/api/tasks/([0-9a-f]{32})/stop', path)
            if match:
                return self.respond(demo.stop(match[1]))
        raise M5Error('NOT_FOUND', 'Endpoint not found.')

    def dispatch(self):
        try:
            self.handle_api()
        except M5Error as exc:
            self.respond({'error': {'code': exc.code, 'message': str(exc)}},
                         404 if exc.code == 'NOT_FOUND' else 403 if exc.code == 'FORBIDDEN' else 409 if exc.code == 'BUSY' else 400)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            self.respond({'error': {'code': 'SERVER_ERROR', 'message': 'Request failed. Check the local server configuration.'}}, 500)

    do_GET = dispatch
    do_POST = dispatch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--m4-python', type=Path, default=ROOT / '.venv/bin/python')
    parser.add_argument('--runs', type=Path, default=ROOT / 'm5_runs/demo')
    args = parser.parse_args()
    load_environment()
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    server.allowed_hosts = {f'127.0.0.1:{args.port}', f'localhost:{args.port}', '127.0.0.1:8080', 'localhost:8080'}
    server.allowed_origins = {f'http://127.0.0.1:{args.port}', f'http://localhost:{args.port}', 'http://127.0.0.1:8080', 'http://localhost:8080'}
    server.demo = Demo(args.m4_python, args.runs)
    print(f'RAG API ready at http://127.0.0.1:{args.port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.demo.worker.close()
        server.server_close()


if __name__ == '__main__':
    main()
