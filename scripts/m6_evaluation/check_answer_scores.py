"""Check human answer-score rows against the v1 decision order.

Blank rows are skipped. Calibration rows are accepted but never added to the
official tally. The script does not call a model or read holdout answers.
"""
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GOLD = {
    'dev': ROOT / 'data/evaluation/m5_dev.json',
    'holdout': ROOT / 'data/evaluation/m5_holdout.json',
}
LABELS = {
    'CORRECT', 'PARTIAL', 'FACTUAL_ERROR', 'CORRECT_REFUSAL', 'FALSE_REFUSAL',
    'INCOMPLETE_REFUSAL', 'NO_HIT', 'ERROR',
}
REASONS = {'', 'OMISSION', 'CITATION', 'UNANSWERABLE_SLOT', 'BOTH'}
CITATIONS = {'FULL', 'PARTIAL', 'NONE', 'NOT_APPLICABLE'}
MARKS = {'PRESENT', 'OMITTED', 'CONTRADICTED'}
CITATION_MARKS = {'CITED', 'UNCITED'}


def load_gold():
    facts = {}
    for split, path in GOLD.items():
        for row in json.loads(path.read_text(encoding='utf-8')):
            facts[row['id']] = {
                'split': split,
                'answerable': 'true' if row['answerable'] else 'false',
                'ids': [fact['fact_id'] for fact in row['required_facts']],
            }
    return facts


def parse_marks(text):
    marks = {}
    if not text.strip():
        return marks
    for part in text.split(';'):
        fact_id, mark = part.split('=', 1)
        if fact_id in marks or mark not in MARKS:
            raise ValueError('bad fact mark: ' + part)
        marks[fact_id] = mark
    return marks


def parse_citation_marks(text):
    marks = {}
    if not text.strip():
        return marks
    for part in text.split(';'):
        fact_id, mark = part.split('=', 1)
        if fact_id in marks or mark not in CITATION_MARKS:
            raise ValueError('bad fact citation: ' + part)
        marks[fact_id] = mark
    return marks


def citation_fact_errors(row):
    try:
        cited = parse_citation_marks(row.get('fact_citation_marks', ''))
        present = {fact_id for fact_id, mark in parse_marks(row['fact_marks']).items() if mark == 'PRESENT'}
    except ValueError:
        return ['fact_citation_marks']
    if row['citation_support'] == 'NOT_APPLICABLE':
        return ['fact citations belong only on cited answers'] if cited else []
    if set(cited) != present:
        return ['fact citation ids must be the PRESENT facts']
    values = set(cited.values())
    if row['citation_support'] == 'FULL' and values == {'CITED'}:
        return []
    if row['citation_support'] == 'NONE' and (not present or values == {'UNCITED'}):
        return []
    if row['citation_support'] == 'PARTIAL' and values == {'CITED', 'UNCITED'}:
        return []
    return ['fact citations disagree with ' + row['citation_support']]


def decide(row):
    answerable = row['answerable'] == 'true'
    marks = parse_marks(row['fact_marks'])
    present = sum(mark == 'PRESENT' for mark in marks.values())
    omitted = sum(mark == 'OMITTED' for mark in marks.values())
    contradicted = sum(mark == 'CONTRADICTED' for mark in marks.values())
    protocol = row['protocol']
    citation_ok = protocol == 'G0' or row['citation_support'] == 'FULL'
    if row['system_failure'] == 'YES':
        return 'ERROR', ''
    if row['invented_missing_slot'] == 'YES' or contradicted:
        return 'FACTUAL_ERROR', ''
    if not answerable:
        if row['explicit_refusal'] == 'YES':
            return 'CORRECT_REFUSAL', ''
        return 'INCOMPLETE_REFUSAL', ''
    if row['explicit_refusal'] == 'YES' and present == 0:
        return 'FALSE_REFUSAL', ''
    required = len(marks)
    if present == required and required > 0 and omitted == 0:
        if row['mixed_unanswerable_slot'] == 'YES':
            reason = 'UNANSWERABLE_SLOT' if citation_ok else 'BOTH'
            return 'PARTIAL', reason
        if citation_ok:
            return 'CORRECT', ''
        return 'PARTIAL', 'CITATION'
    if present > 0 and omitted > 0:
        reason = 'OMISSION' if citation_ok else 'BOTH'
        return 'PARTIAL', reason
    return 'NO_HIT', ''


def expected_citation(row, label, reason):
    protocol = row['protocol']
    if label in {'ERROR', 'CORRECT_REFUSAL', 'FALSE_REFUSAL', 'INCOMPLETE_REFUSAL', 'NO_HIT'}:
        return {'NOT_APPLICABLE'}
    if label == 'FACTUAL_ERROR':
        return {'NONE', 'PARTIAL', 'NOT_APPLICABLE'}
    if label == 'CORRECT':
        return {'NOT_APPLICABLE'} if protocol == 'G0' else {'FULL'}
    if reason == 'CITATION':
        return {'PARTIAL', 'NONE'}
    if reason == 'BOTH':
        return {'PARTIAL', 'NONE'}
    if reason == 'OMISSION':
        return {'NOT_APPLICABLE'} if protocol == 'G0' else {'FULL'}
    if reason == 'UNANSWERABLE_SLOT':
        return {'NOT_APPLICABLE'} if protocol == 'G0' else {'FULL'}
    return set()


def check_row(row, gold, line_no):
    errors = []
    for key in ('answerable', 'system_failure', 'explicit_refusal', 'invented_missing_slot', 'mixed_unanswerable_slot'):
        allowed = {'true', 'false'} if key == 'answerable' else {'YES', 'NO'}
        if row[key] not in allowed:
            errors.append(key)
    if row['protocol'] not in {'G0', 'G1', 'G2'}:
        errors.append('protocol')
    if row['citation_support'] not in CITATIONS:
        errors.append('citation_support')
    try:
        irrelevant = int(row['irrelevant_fact_count'])
        if irrelevant < 0:
            raise ValueError
    except ValueError:
        errors.append('irrelevant_fact_count')
    item = gold.get(row['id'])
    if item and row.get('case_role') != 'calibration':
        if item['answerable'] != row['answerable'] or item['split'] != row['split']:
            errors.append('gold identity')
        if row['mixed_unanswerable_slot'] != 'NO':
            errors.append('current gold has no mixed slot')
        if sorted(parse_marks(row['fact_marks'])) != sorted(item['ids']) and row['answerable'] == 'true':
            errors.append('fact ids differ from gold')
        if row['answerable'] == 'false' and row['fact_marks'].strip():
            errors.append('unanswerable fact marks')
    label, reason = decide(row)
    if row['primary_label'] != label:
        errors.append('primary_label should be ' + label)
    if row['partial_reason'] != reason:
        errors.append('partial_reason should be ' + (reason or 'empty'))
    refusal = label if label in {'CORRECT_REFUSAL', 'FALSE_REFUSAL', 'INCOMPLETE_REFUSAL'} else 'NOT_APPLICABLE'
    if row['refusal_label'] != refusal:
        errors.append('refusal_label should be ' + refusal)
    if row['citation_support'] not in expected_citation(row, label, reason):
        errors.append('citation_support disagrees with ' + label)
    if 'fact_citation_marks' not in row:
        errors.append('fact_citation_marks')
    else:
        errors.extend(citation_fact_errors(row))
    if row['disputed'] == 'YES' and row['adjudication'] not in LABELS:
        errors.append('disputed row needs another reviewer')
    if row['disputed'] == 'YES' and row['adjudicator'].strip() == row['reviewer'].strip():
        errors.append('adjudicator must be a different person')
    if errors:
        return line_no, row['id'], errors
    final = row['adjudication'] if row['disputed'] == 'YES' else label
    return line_no, row['id'], final


def tally(rows):
    official = [row for row in rows if row[2] not in {'skip'} and not isinstance(row[2], list)
                and row[3] != 'calibration']
    counts = {}
    for row in official:
        counts[row[2]] = counts.get(row[2], 0) + 1
    total = sum(counts.values())
    print('official scored: ' + str(total))
    for label in sorted(counts):
        print(f'{label}: {counts[label]}/{total}')
    errors = [row for row in rows if isinstance(row[2], list)]
    print('check errors: ' + str(len(errors)))
    for line_no, item_id, problems in errors:
        print(f'line {line_no} {item_id}: ' + '; '.join(problems))
    return len(errors)


def check_sheet_identity(row, gold):
    item = gold.get(row['id'])
    if item is None or row.get('case_role') == 'calibration':
        return []
    errors = []
    if row['answerable'] != item['answerable'] or row['split'] != item['split']:
        errors.append('gold identity')
    if row['required_fact_ids'] != ';'.join(item['ids']):
        errors.append('required facts differ from gold')
    if row['mixed_unanswerable_slot'] not in {'', 'NO'}:
        errors.append('current gold has no mixed slot')
    return errors


def main(path):
    gold = load_gold()
    with Path(path).open(encoding='utf-8-sig', newline='') as stream:
        rows = list(csv.DictReader(stream))
    checked = []
    for line_no, row in enumerate(rows, 2):
        identity = check_sheet_identity(row, gold)
        if identity:
            checked.append((line_no, row['id'], identity, row.get('case_role', '')))
            continue
        if not row['primary_label'].strip():
            continue
        result = check_row(row, gold, line_no)
        checked.append((result[0], result[1], result[2], row.get('case_role', '')))
    return tally(checked)


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('usage: check_answer_scores.py SCORE_SHEET.csv')
    raise SystemExit(main(sys.argv[1]))
