"""Summarize retrieval latency, human-score rates, and generation ledgers.

Missing cost stays null. Error requests stay in the all-request denominator.
This script reads saved files only and does not call a model.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path

from scripts.m6_evaluation.check_answer_scores import check_row, load_gold


def percentile(values, p):
    xs = sorted(values)
    if not xs:
        return None
    pos = (len(xs) - 1) * p
    lo = int(pos)
    hi = min(lo + 1, len(xs) - 1)
    return round(xs[lo] + (xs[hi] - xs[lo]) * (pos - lo), 1)


def ratio(numerator, denominator):
    return {'numerator': numerator, 'denominator': denominator,
            'text': f'{numerator}/{denominator}' if denominator else '0/0'}


def latency_block(values):
    return {'n': len(values), 'p50': percentile(values, 0.50), 'p95': percentile(values, 0.95),
            'mean': round(sum(values) / len(values), 1) if values else None}


def summarize_scores(path):
    gold = load_gold()
    with Path(path).open(encoding='utf-8-sig', newline='') as stream:
        rows = list(csv.DictReader(stream))
    official = []
    problems = []
    present = omitted = contradicted = required = cited = citation_present = 0
    seen = {}
    candidates = []
    for line_no, row in enumerate(rows, 2):
        if row.get('case_role') == 'calibration' or not row.get('primary_label', '').strip():
            continue
        key = (row.get('run_id', ''), row.get('id', ''))
        seen.setdefault(key, []).append(line_no)
        candidates.append((line_no, row))
    duplicated = {key for key, lines in seen.items() if len(lines) > 1}
    for line_no, row in candidates:
        item_id = row.get('id', '')
        item = gold.get(item_id)
        errors = []
        if (row.get('run_id', ''), item_id) in duplicated:
            errors.append('duplicate id in the same run')
        if item is None:
            errors.append('unknown id')
        else:
            expected = ';'.join(item['ids'])
            if row.get('required_fact_ids', '') != expected:
                errors.append('required facts differ from gold')
        if errors:
            problems.append({'line': line_no, 'id': item_id, 'errors': errors})
            continue
        result = check_row(row, gold, line_no)
        if isinstance(result[2], list):
            problems.append({'line': line_no, 'id': item_id, 'errors': result[2]})
            continue
        official.append(result[2])
        if row['answerable'] == 'true' and result[2] != 'ERROR':
            marks = [part.split('=', 1)[1] for part in row['fact_marks'].split(';') if part]
            present += marks.count('PRESENT')
            omitted += marks.count('OMITTED')
            contradicted += marks.count('CONTRADICTED')
            required += len(marks)
            if row.get('protocol') in {'G1', 'G2'}:
                citations = dict(part.split('=', 1) for part in row.get('fact_citation_marks', '').split(';') if part)
                for part in row['fact_marks'].split(';'):
                    if not part:
                        continue
                    fact_id, mark = part.split('=', 1)
                    if mark == 'PRESENT':
                        citation_present += 1
                        cited += citations.get(fact_id) == 'CITED'
    counts = {label: official.count(label) for label in sorted(set(official))}
    non_error = [label for label in official if label != 'ERROR']
    return {
        'official_rows': len(official),
        'labels_all_requests': {label: ratio(count, len(official)) for label, count in counts.items()},
        'labels_excluding_error': {label: ratio(non_error.count(label), len(non_error))
                                   for label in sorted(set(non_error))},
        'error_requests_retained': ratio(counts.get('ERROR', 0), len(official)),
        'fact_coverage_excluding_error': ratio(present, required),
        'citation_coverage_excluding_error': ratio(cited, citation_present),
        'fact_omission_excluding_error': ratio(omitted, required),
        'fact_contradiction_excluding_error': ratio(contradicted, required),
        'check_problems': problems,
    }


def summarize_retrieval(summary_path):
    data = json.loads(Path(summary_path).read_text(encoding='utf-8'))
    root = Path(summary_path).resolve().parent
    timings = []
    for name, block in sorted(data.get('latency', {}).items()):
        folder = root / f'{name}_k10_skip'
        if not folder.is_dir():
            continue
        for item in sorted(folder.glob('item_*/retrieval.json')):
            packed = json.loads(item.read_text(encoding='utf-8'))
            timings.append(packed['retrieval']['timing_ms']['total'])
    return {'stored_latency': data.get('latency', {}),
            'recomputed_from_k10_skip_ms': latency_block(timings),
            'live_searches': data.get('live_searches'),
            'answerable_count': data.get('answerable_count'),
            'question_count': data.get('question_count')}


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def bound_pipeline(root, relative):
    if not isinstance(relative, str) or not relative:
        return None
    path = Path(relative)
    if path.is_absolute() or '..' in path.parts:
        return None
    target = (root / path).resolve()
    if not target.is_relative_to(root.resolve()) or not target.is_file():
        return None
    return target


def _calls_from_pipeline(pipeline, item_id):
    calls = []
    for call in pipeline.get('api_calls') or []:
        calls.append({'id': item_id, 'stage': call.get('stage'), 'state': call.get('state'),
                      'input_tokens': call.get('input_tokens'), 'output_tokens': call.get('output_tokens'),
                      'latency_ms': call.get('latency_ms'), 'error_code': call.get('error_code')})
    return calls


def summarize_generation(run_dir):
    root = Path(run_dir)
    manifest = json.loads((root / 'run.json').read_text(encoding='utf-8'))
    predictions = []
    ledger = root / 'predictions.jsonl'
    if ledger.is_file():
        predictions = [json.loads(line) for line in ledger.read_text(encoding='utf-8').splitlines() if line.strip()]
    planned = manifest.get('request_count')
    if type(planned) is not int or planned < 1:
        planned = len(predictions)
    saved = len(predictions)
    unfinished = max(0, planned - saved)
    problems = []
    if saved > planned:
        problems.append({'id': None, 'errors': ['more predictions than request_count']})
    seen = {}
    for row in predictions:
        seen.setdefault(row.get('id'), []).append(row)
    calls = []
    repairs = 0
    linked = set()
    saved_ok = saved <= planned and not any(len(rows) > 1 for rows in seen.values())
    for item_id, rows in seen.items():
        if len(rows) > 1:
            problems.append({'id': item_id, 'errors': ['duplicate prediction id']})
            saved_ok = False
            continue
        row = rows[0]
        relative = row.get('pipeline_file')
        pipeline_path = bound_pipeline(root, relative)
        recorded = row.get('pipeline_sha256')
        if pipeline_path is None or not isinstance(recorded, str) or file_sha256(pipeline_path) != recorded:
            problems.append({'id': item_id, 'errors': ['pipeline path or hash mismatch']})
            saved_ok = False
            continue
        if pipeline_path in linked:
            problems.append({'id': item_id, 'errors': ['duplicate pipeline path']})
            saved_ok = False
            continue
        pipeline = json.loads(pipeline_path.read_text(encoding='utf-8'))
        if not row.get('request_id') or row.get('request_id') != pipeline.get('request_id'):
            problems.append({'id': item_id, 'errors': ['request id mismatch']})
            saved_ok = False
            continue
        linked.add(pipeline_path)
        calls.extend(_calls_from_pipeline(pipeline, item_id))
        repairs += int(bool(pipeline.get('repair_used')))
    closed = saved_ok
    if saved_ok:
        extra_calls = 0
        for folder in sorted(path for path in root.glob('item_*') if path.is_dir()):
            checkpoint = folder / 'pipeline.json'
            if checkpoint.is_file() and checkpoint.resolve() not in linked:
                extra_calls += len(json.loads(checkpoint.read_text(encoding='utf-8')).get('api_calls') or [])
        manifest_calls = manifest.get('api_requests')
        if extra_calls:
            problems.append({'id': None, 'errors': ['unlinked checkpoint calls are outside the prediction ledger']})
            closed = False
        if type(manifest_calls) is int and manifest_calls != len(calls):
            problems.append({'id': None, 'errors': ['manifest api_requests does not match linked calls']})
            closed = False
        elif manifest_calls is None:
            problems.append({'id': None, 'errors': ['manifest api_requests is unknown']})
            closed = False
    verified = closed
    statuses = [row.get('status') for row in predictions]
    billing = manifest.get('billing') or {}
    token_fields = ('input_tokens', 'output_tokens')

    def token_sum(values):
        return {field: (sum(call[field] for call in values)
                        if values and all(isinstance(call[field], int) for call in values) else None)
                for field in token_fields}

    saved_tokens = token_sum(calls)
    tokens = saved_tokens if verified else {field: None for field in token_fields}
    subtotal = None if verified or not saved_ok else {'api_calls': len(calls), 'tokens': saved_tokens}
    latencies = [call['latency_ms'] for call in calls if isinstance(call.get('latency_ms'), (int, float))]
    cost = billing.get('total_cost')
    return {
        'run_dir': str(root),
        'status': manifest.get('status'),
        'request_count': planned,
        'saved_predictions': saved,
        'unfinished_requests': ratio(unfinished, planned),
        'status_counts': {status: statuses.count(status) for status in sorted(set(statuses))},
        'error_requests': ratio(statuses.count('ERROR'), planned),
        'ledger_verified': verified,
        'ledger_problems': problems,
        'verified_subtotal': subtotal,
        'api_calls': len(calls) if verified else None,
        'repairs_used': repairs if verified else None,
        'tokens': tokens,
        'token_usage_complete': bool(verified and unfinished == 0 and calls
                                     and all(tokens[field] is not None for field in token_fields)),
        'call_latency_ms': latency_block(latencies),
        'total_cost': cost,
        'cost_known': cost is not None,
        'billing_reason': billing.get('reason'),
        'missing_or_unknown_calls': billing.get('missing_or_unknown_calls') or [],
    }


def build_report(retrieval_summary=None, score_sheet=None, generation_runs=()):
    report = {'schema_version': 'm6_offline_summary.v1',
              'limits': ['Offline checks validate program handling.',
                         'They do not show that a live model detects factual errors.',
                         'A null cost is unknown, not zero.',
                         'ERROR requests remain in the all-request denominator.']}
    if retrieval_summary:
        report['retrieval'] = summarize_retrieval(retrieval_summary)
    if score_sheet:
        report['scores'] = summarize_scores(score_sheet)
    report['generation'] = [summarize_generation(path) for path in generation_runs]
    return report


def main():
    parser = argparse.ArgumentParser(description='Summarize saved M5/M6 runs without calling a model.')
    parser.add_argument('--retrieval-summary', type=Path)
    parser.add_argument('--score-sheet', type=Path)
    parser.add_argument('--generation-run', type=Path, action='append', default=[])
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    report = build_report(args.retrieval_summary, args.score_sheet, args.generation_run)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(text + '\n', encoding='utf-8')
    print(text)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
