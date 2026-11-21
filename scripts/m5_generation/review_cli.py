import argparse
import hashlib
import json
import uuid
from pathlib import Path
from .api import M5Error, strict_json
from .support import review_answer
from .token_budget import print_budget


def main():
    parser = argparse.ArgumentParser(description='Review a saved M5 answer. Automatic review does not replace human gold evaluation.')
    parser.add_argument('--input', required=True, type=Path, help='Saved answer_response.v1 file')
    parser.add_argument('--dry-run', action='store_true', help='Check record integrity locally without a model call')
    parser.add_argument('--model', default='deepseek-flash')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    output = args.output or Path('m5_runs') / ('support_' + uuid.uuid4().hex + '.json')
    if output.exists() or output.resolve() == args.input.resolve():
        print('ERROR [OUTPUT_EXISTS]: Cannot overwrite the original record or an existing output.')
        return 1
    try:
        if args.input.stat().st_size > 5_000_000:
            raise M5Error('INPUT_FILE_TOO_LARGE', 'The record exceeds the 5 MB limit.')
        raw = args.input.read_bytes()
        record = strict_json(raw.decode('utf-8-sig'))
        print('Mode: local integrity check; no API calls.' if args.dry_run else
              'Mode: at most 1 DeepSeek review call using account credit; no answer regeneration.')
        result = review_answer(record, dry_run=args.dry_run, model=args.model)
        result['input_file_sha256'] = hashlib.sha256(raw).hexdigest()
        result['input_file'] = str(args.input.resolve())
    except (M5Error, OSError, UnicodeError) as exc:
        result = {'schema_version': 'm5_support_review.v1', 'decision': 'ERROR',
                  'method': 'local_check_only', 'human_review': 'not_performed',
                  'review_required': True, 'publication_ready': False, 'judge': {'calls': 0},
                  'error': {'code': exc.code if isinstance(exc, M5Error) else 'INPUT_FILE_ERROR',
                            'message': str(exc) if isinstance(exc, M5Error) else 'Cannot read input. Check the path, permissions and UTF-8 encoding.'}}
    except KeyboardInterrupt:
        print('\nCancelled.')
        return 130
    print('Review decision: ' + result['decision'])
    for claim in result.get('claim_reviews', []):
        print(f"{claim['claim_id']}: {claim['verdict']}; directly relevant: {claim['relevant']}")
        print('  Support reason: ' + claim['reason'])
        if 'scope_role' in claim:
            print('  Scope role: ' + claim['scope_role'])
            print('  Relevance reason: ' + claim['relevance_reason'])
        for citation in claim['citation_reviews']:
            print('  ' + citation['source_id'] + ': ' + citation['verdict'] + '; ' + citation['reason'])
    if result.get('answer_review'):
        print('Overall review: ' + result['answer_review']['reason'])
    print_budget(result.get('token_budget'))
    print('Review API calls: ' + str(result['judge']['calls']))
    if result['decision'] in {'PASS', 'FAIL'}:
        print('Method: llm_judge (automatic model review), not human verification.')
        print('The original answer remains a draft; publication_ready=false.')
    if result['decision'] == 'FAIL':
        print('Inspect the failure reasons. No answer was rewritten. Do not rerun until a pass occurs.')
    if result.get('error'):
        print('Error: ' + result['error']['code'] + '; ' + result['error']['message'])
        details = result['error'].get('diagnostics')
        if details:
            print('Diagnostic: source=' + details.get('source', 'unknown') + '; reason=' + details.get('reason', 'unknown'))
            if details.get('source') == 'judge_output':
                print('Object: ' + details['location'])
                print('Received type: ' + details['actual_type'])
                print('Missing fields: ' + (', '.join(details['missing_fields']) or '(none)'))
                print('Unexpected known fields: ' + (', '.join(details['unexpected_known_fields']) or '(none)'))
                print('Unexpected field count: ' + str(details['unexpected_field_count']))
                print('Unrecognized field names: ' + str(details['unrecognized_field_count']) + ' (not recorded)')
            if 'line' in details:
                print('Location: line ' + str(details['line']) + ', column ' + str(details['column']))
            if 'model_text_excerpt' in details:
                print('The rejected model text excerpt is saved in the diagnostic record; it is not an approved answer.')
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open('x', encoding='utf-8') as handle:
            json.dump(result, handle, ensure_ascii=False, indent=2, allow_nan=False)
        print('Review saved: ' + str(output.resolve()))
    except (OSError, ValueError):
        print('ERROR [OUTPUT_WRITE_ERROR]: Could not save the review.')
        return 1
    return 1 if result['decision'] in {'FAIL', 'ERROR'} else 0


if __name__ == '__main__':
    raise SystemExit(main())
