"""Dev-set retrieval grid. Sends only id and question; gold stays on the evaluation side.

One live search per question, strategy and mode uses candidate_k=30 and returns 10
chunks. k=3 and k=5 are prefixes of that ranking, which is what top_k does in M4.
Both packing policies are applied to each prefix and written as official A runs.
"""
import json
import sys
import uuid
from collections import defaultdict
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.m4_retrieval.cli import load_requests, run_batch, sha_file
from scripts.m4_retrieval.packing import object_hash
from scripts.m4_retrieval.workshop import validate
from scripts.m5_live.common import inspect_paths
from scripts.m5_live.retrieval_worker import initialize

QUESTIONS = ROOT / 'data/evaluation/inputs/m5_dev.questions.jsonl'
GOLD = ROOT / 'data/evaluation/m5_dev.json'
OUT = ROOT / 'm5_runs' / 'd_dev_retrieval'
WORK = ROOT / '.local-m4'
SEARCH_K = 10
KS = (3, 5, 10)
POLICIES = ('legacy_break_v1', 'skip_continue_dedup_v1')


def percentile(values, p):
    xs = sorted(values)
    if not xs:
        return None
    pos = (len(xs) - 1) * p
    lo = int(pos)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


def mean(values):
    return sum(values) / len(values) if values else None


def condition_name(strategy, mode, k, policy):
    short = 'legacy' if policy == 'legacy_break_v1' else 'skip'
    return f'{strategy}_{mode}_k{k}_{short}'


def load_gold():
    rows = json.loads(GOLD.read_text(encoding='utf-8'))
    by_id = {}
    for row in rows:
        by_id[row['id']] = row
    return by_id


def check_input(items, gold):
    raw = [json.loads(line) for line in QUESTIONS.read_text(encoding='utf-8-sig').splitlines() if line.strip()]
    if any(set(row) - {'id', 'question'} for row in raw):
        raise SystemExit('Dev JSONL contains fields other than id and question.')
    ids = [item['request']['id'] for item in items]
    if any(item['error'] for item in items) or len(ids) != 15 or set(ids) != set(gold):
        raise SystemExit('Dev question ids do not match the gold file.')
    answerable = []
    for qid in ids:
        row = gold[qid]
        has_evidence = bool(row['gold_evidence'])
        if row['answerable'] != has_evidence or (row['expected_status'] == 'ANSWERED') != has_evidence:
            raise SystemExit('Gold answerability flags disagree: ' + qid)
        if row['split'] != 'dev':
            raise SystemExit('Gold split is not dev: ' + qid)
    return [gold[qid] for qid in ids if gold[qid]['answerable']]


def map_quotes(workshop, answerable):
    by_doc = {}
    for strategy, rows in workshop.rows.items():
        grouped = defaultdict(list)
        for row in rows:
            grouped[row['meta']['document_id']].append(row)
        by_doc[strategy] = grouped
    mapped = {}
    coverage = {}
    for strategy in 'ABC':
        contained = 0
        total = 0
        missing = []
        for item in answerable:
            units = []
            for unit in item['gold_evidence']:
                total += 1
                hits = [row['chunk_id'] for row in by_doc[strategy][unit['document_id']]
                        if unit['quote'] in row['text']]
                if hits:
                    contained += 1
                else:
                    missing.append({'id': item['id'], 'evidence_id': unit['evidence_id'],
                                    'quote_chars': len(unit['quote'])})
                units.append({'evidence_id': unit['evidence_id'], 'document_id': unit['document_id'],
                              'chunk_ids': hits})
            mapped[(strategy, item['id'])] = units
        coverage[strategy] = {'units': total, 'fully_contained': contained, 'missing': missing}
    return mapped, coverage


def score_list(chunk_ids, document_ids, units):
    covered = [any(cid in unit['chunk_ids'] for cid in chunk_ids) for unit in units]
    cover_ids = {cid for unit in units for cid in unit['chunk_ids']}
    gold_docs = {unit['document_id'] for unit in units}
    reciprocal = 0.0
    for rank, cid in enumerate(chunk_ids, 1):
        if cid in cover_ids:
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


def aggregate(rows):
    return {
        'n': len(rows),
        'hit': f"{sum(r['hit'] for r in rows)}/{len(rows)}",
        'hit_rate': mean([r['hit'] for r in rows]),
        'recall': mean([r['recall'] for r in rows]),
        'complete': f"{sum(r['complete'] for r in rows)}/{len(rows)}",
        'complete_rate': mean([r['complete'] for r in rows]),
        'mrr': mean([r['rr'] for r in rows]),
        'doc_hit': f"{sum(r['doc_hit'] for r in rows)}/{len(rows)}",
        'doc_hit_rate': mean([r['doc_hit'] for r in rows]),
        'mean_count': mean([r['count'] for r in rows]),
        'miss_ids': [r['id'] for r in rows if not r['hit']],
        'incomplete_ids': [r['id'] for r in rows if not r['complete']],
    }


def evaluate(path, strategy, mapped, answerable_ids):
    records = [json.loads(line) for line in (path / 'results.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
    raw_rows, budget_rows = [], []
    timings = []
    for record in records:
        if record['id'] not in answerable_ids:
            continue
        packed = json.loads((path / record['packed_file']).read_text(encoding='utf-8'))
        if sha_file(path / record['packed_file']) != record['packed_sha256']:
            raise SystemExit('Packed hash mismatch: ' + str(path))
        if object_hash(packed) != json.loads((path / record['packing_report_file']).read_text(encoding='utf-8'))['packed_sha256']:
            raise SystemExit('Packing binding mismatch: ' + str(path))
        retrieval = packed['retrieval']
        results = retrieval['results']
        by_chunk = {row['chunk_id']: row for row in results}
        units = mapped[(strategy, record['id'])]
        raw = score_list([row['chunk_id'] for row in results],
                         [row['document_id'] for row in results], units)
        selected = packed['selected_chunk_ids']
        budget = score_list(selected, [by_chunk[cid]['document_id'] for cid in selected], units)
        raw['id'] = budget['id'] = record['id']
        budget['context_tokens'] = packed['context_tokens']
        raw_rows.append(raw)
        budget_rows.append(budget)
        timings.append(retrieval['timing_ms'])
    summary = aggregate(raw_rows)
    budget_summary = aggregate(budget_rows)
    budget_summary['mean_context_tokens'] = mean([r['context_tokens'] for r in budget_rows])
    return summary, budget_summary, timings


def main():
    gold = load_gold()
    items = load_requests(QUESTIONS)
    answerable = check_input(items, gold)
    answerable_ids = {row['id'] for row in answerable}
    OUT.mkdir(parents=True, exist_ok=True)
    workshop = initialize(ROOT, inspect_paths(WORK), OUT / '_runtime')
    mapped, containment = map_quotes(workshop, answerable)
    for strategy, info in containment.items():
        print(f"Quote containment {strategy}: {info['fully_contained']}/{info['units']}", flush=True)

    real_retrieve = workshop.retrieve
    cache = {}
    live_calls = []

    def cached_retrieve(query, strategy='B', top_k=5, candidate_k=30, filters=None,
                        mode='dense', rrf_constant=60):
        key = (query, strategy, mode, candidate_k, rrf_constant)
        if key not in cache:
            full = real_retrieve(query, strategy=strategy, top_k=SEARCH_K, candidate_k=candidate_k,
                                 filters=filters, mode=mode, rrf_constant=rrf_constant)
            cache[key] = full
            live_calls.append({'strategy': strategy, 'mode': mode, 'timing_ms': full['timing_ms'],
                               'status': full['status'], 'returned': len(full['results'])})
        base = cache[key]
        value = deepcopy(base)
        value['request_id'] = uuid.uuid4().hex
        value['results'] = deepcopy(base['results'][:top_k])
        for rank, row in enumerate(value['results'], 1):
            row['rank'] = rank
        value['config'] = dict(base['config'])
        value['config']['top_k'] = top_k
        return validate(value, workshop.schema)

    workshop.retrieve = cached_retrieve
    input_sha = sha_file(QUESTIONS)
    conditions = []
    for strategy in 'ABC':
        for mode in ('dense', 'bm25', 'hybrid'):
            for k in KS:
                for policy in POLICIES:
                    name = condition_name(strategy, mode, k, policy)
                    output = OUT / name
                    config = {'strategy': strategy, 'mode': mode, 'top_k': k, 'candidate_k': 30,
                              'rrf_constant': 60, 'context_tokens': 1024, 'packing_policy': policy}
                    print('Running ' + name, flush=True)
                    manifest = run_batch(items, config, output, workshop_factory=lambda: workshop,
                                         input_sha256=input_sha)
                    raw, budget, _ = evaluate(output, strategy, mapped, answerable_ids)
                    conditions.append({'name': name, 'strategy': strategy, 'mode': mode, 'top_k': k,
                                       'packing_policy': policy, 'path': str(output.relative_to(ROOT)),
                                       'status': manifest['status'], 'elapsed_seconds': manifest['elapsed_seconds'],
                                       'results_sha256': manifest['results_sha256'],
                                       'raw': raw, 'budget': budget})
                    print(f"{name}: raw Hit {raw['hit']} Recall {raw['recall']:.3f} "
                          f"Complete {raw['complete']} MRR {raw['mrr']:.3f} Doc {raw['doc_hit']}", flush=True)

    latency = {}
    grouped = defaultdict(list)
    for row in live_calls:
        grouped[(row['strategy'], row['mode'])].append(row['timing_ms'])
    for (strategy, mode), rows in sorted(grouped.items()):
        latency[f'{strategy}_{mode}'] = {
            'n': len(rows),
            'encode_p50_ms': round(percentile([r['encode'] for r in rows], 0.50), 1),
            'search_p50_ms': round(percentile([r['search'] for r in rows], 0.50), 1),
            'total_p50_ms': round(percentile([r['total'] for r in rows], 0.50), 1),
            'total_p95_ms': round(percentile([r['total'] for r in rows], 0.95), 1),
            'total_mean_ms': round(mean([r['total'] for r in rows]), 1),
        }
    summary = {
        'schema_version': 'm5_d_retrieval_summary.v1',
        'population': 'dev answerable questions only; holdout was not read',
        'questions_file': str(QUESTIONS.relative_to(ROOT)),
        'questions_sha256': input_sha,
        'gold_file': str(GOLD.relative_to(ROOT)),
        'gold_sha256': sha_file(GOLD),
        'question_count': 15,
        'answerable_count': len(answerable_ids),
        'unanswerable_count': 15 - len(answerable_ids),
        'search_top_k': SEARCH_K,
        'candidate_k': 30,
        'rrf_constant': 60,
        'context_tokens': 1024,
        'live_searches': len(live_calls),
        'quote_containment': containment,
        'latency': latency,
        'conditions': conditions,
    }
    (OUT / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('Summary: ' + str(OUT / 'summary.json'), flush=True)
    print('Live searches: ' + str(len(live_calls)), flush=True)


if __name__ == '__main__':
    main()
