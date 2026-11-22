"""Score saved dev retrieval at three stages. No new search and no generation API.

Stages are raw candidates, M4 selected chunks, and the evidence list build_context
would send to M5 under the built-in deepseek-flash input budget.
Each directory is accepted only after load_a_run checks status, hashes, and bindings.
"""
import hashlib
import json
from pathlib import Path

from scripts.m5_generation.api import M5Error
from scripts.m5_generation.batch import load_a_run
from scripts.m5_generation.context import build_context
from scripts.m5_generation.token_budget import BUILTIN_PROFILE_VERSION, builtin_profile

ROOT = Path(__file__).resolve().parents[2]
GOLD = ROOT / 'data/evaluation/m5_dev.json'
QUESTIONS = ROOT / 'data/evaluation/inputs/m5_dev.questions.jsonl'
OUT = ROOT / 'm5_runs' / 'd_dev_retrieval'
UNANSWERABLE = {'m5_dev_003', 'm5_dev_006', 'm5_dev_015'}
PROMPTS = (
    'scripts/m5_generation/prompts/generation_v1.txt',
    'scripts/m5_generation/prompts/repair_v1.txt',
    'scripts/m5_generation/prompts/support_v1.txt',
)
DEV_ITEMS = 15
M4_CONTEXT_TOKENS = 1024


def mean(values):
    return sum(values) / len(values) if values else None


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def chunk_covers(chunk_id, unit, texts, docs):
    return docs.get(chunk_id) == unit['document_id'] and unit['quote'] in texts.get(chunk_id, '')


def score_list(chunk_ids, document_ids, units, texts, docs):
    covered = [any(chunk_covers(cid, unit, texts, docs) for cid in chunk_ids) for unit in units]
    gold_docs = {unit['document_id'] for unit in units}
    reciprocal = 0.0
    for rank, cid in enumerate(chunk_ids, 1):
        if any(chunk_covers(cid, unit, texts, docs) for unit in units):
            reciprocal = 1.0 / rank
            break
    return {
        'hit': int(any(covered)),
        'recall': sum(covered) / len(units),
        'complete': int(all(covered)),
        'rr': reciprocal,
        'doc_hit': int(any(doc in gold_docs for doc in document_ids)),
        'count': len(chunk_ids),
    }


def newly_dropped(before, after):
    """Questions that were complete before this stage and incomplete after it."""
    already = {row['id'] for row in before if not row['complete']}
    return [row['id'] for row in after if not row['complete'] and row['id'] not in already]


def recorded_inputs():
    profile = builtin_profile()
    profile_bytes = json.dumps(profile, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return {
        'questions_file': 'data/evaluation/inputs/m5_dev.questions.jsonl',
        'questions_sha256': sha256_file(QUESTIONS),
        'gold_file': 'data/evaluation/m5_dev.json',
        'gold_sha256': sha256_file(GOLD),
        'prompt_sha256': {relative: sha256_file(ROOT / relative) for relative in PROMPTS},
        'm5_input_budget': {
            'model': 'deepseek-flash',
            'profile_version': BUILTIN_PROFILE_VERSION,
            'profile_sha256': hashlib.sha256(profile_bytes).hexdigest(),
            'profile_source': 'scripts/m5_generation/token_budget.py builtin_profile',
            'application_total_token_limit': profile['application_total_token_limit'],
            'safety_margin_tokens': profile['safety_margin_tokens'],
        },
        'm4_context_tokens': M4_CONTEXT_TOKENS,
    }


def aggregate(rows):
    return {
        'n': len(rows),
        'hit': f"{sum(row['hit'] for row in rows)}/{len(rows)}",
        'recall': round(mean([row['recall'] for row in rows]), 6),
        'complete': f"{sum(row['complete'] for row in rows)}/{len(rows)}",
        'mrr': round(mean([row['rr'] for row in rows]), 6),
        'doc_hit': f"{sum(row['doc_hit'] for row in rows)}/{len(rows)}",
        'mean_count': round(mean([row['count'] for row in rows]), 2),
        'incomplete_ids': [row['id'] for row in rows if not row['complete']],
    }


def load_units():
    units = {}
    for item in json.loads(GOLD.read_text(encoding='utf-8')):
        if item['id'] in UNANSWERABLE or not item['answerable']:
            continue
        units[item['id']] = [{'quote': row['quote'], 'document_id': row['document_id'],
                              'evidence_id': row['evidence_id']} for row in item['gold_evidence']]
    return units


def main():
    units = load_units()
    inputs = recorded_inputs()
    conditions = []
    changed = 0
    checked = 0
    for path in sorted(item for item in OUT.iterdir() if item.is_dir() and item.name != '_runtime'):
        manifest, items = load_a_run(path, max_items=DEV_ITEMS)
        if manifest.get('request_count') != DEV_ITEMS or manifest.get('input_sha256') != inputs['questions_sha256']:
            raise M5Error('A_BINDING_MISMATCH', 'Retrieval run is not bound to the dev question file: ' + path.name)
        config = manifest['config']
        if config.get('context_tokens') != M4_CONTEXT_TOKENS:
            raise M5Error('A_BINDING_MISMATCH', 'M4 context budget differs from 1024: ' + path.name)
        raw_rows, packed_rows, sent_rows = [], [], []
        for item in items:
            record = item['record']
            if record['id'] not in units:
                continue
            packed = item['packed']
            retrieval = packed['retrieval']
            texts = {row['chunk_id']: row['text'] for row in retrieval['results']}
            docs = {row['chunk_id']: row['document_id'] for row in retrieval['results']}
            question_units = units[record['id']]
            raw_ids = [row['chunk_id'] for row in retrieval['results']]
            selected = packed['selected_chunk_ids']
            evidence, _excluded = build_context(retrieval, 'deepseek-flash', selected)
            sent_ids = [row['chunk_id'] for row in evidence]
            raw = score_list(raw_ids, [docs[cid] for cid in raw_ids], question_units, texts, docs)
            budget = score_list(selected, [docs[cid] for cid in selected], question_units, texts, docs)
            sent = score_list(sent_ids, [docs[cid] for cid in sent_ids], question_units, texts, docs)
            for row in (raw, budget, sent):
                row['id'] = record['id']
            raw_rows.append(raw)
            packed_rows.append(budget)
            sent_rows.append(sent)
            checked += 1
            changed += sent_ids != selected
        conditions.append({
            'name': path.name,
            'strategy': config['strategy'],
            'mode': config['mode'],
            'top_k': config['top_k'],
            'packing_policy': config['packing_policy'],
            'raw': aggregate(raw_rows),
            'm4_packed': aggregate(packed_rows),
            'm5_input': aggregate(sent_rows),
            'newly_dropped_by_budget': newly_dropped(raw_rows, packed_rows),
            'incomplete_after_budget': [row['id'] for row in packed_rows if not row['complete']],
        })
    report = {
        'schema_version': 'm6_three_stage_retrieval.v1',
        'model_for_m5_input_preview': 'deepseek-flash',
        'generation_api_calls': 0,
        'input_check': 'load_a_run',
        'quote_match': 'full quote inside a chunk of the gold evidence document',
        **inputs,
        'answerable_rows_checked': checked,
        'rows_where_m5_input_differs_from_m4_selection': changed,
        'conditions': conditions,
    }
    destination = OUT / 'three_stage_summary.json'
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'checked {checked}; m5 input differs on {changed} rows')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
