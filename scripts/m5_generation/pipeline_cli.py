"""Run generation, automatic review and at most one shared repair."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import uuid

from .api import M5Error, strict_json
from .pipeline import run_pipeline
from .token_budget import print_budget
from .render import render_sources


def main():
    parser = argparse.ArgumentParser(description='M5: English generation, review and at most one repair. Outputs remain drafts.')
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--dry-run', action='store_true', help='Validate input and evidence without requesting a key or calling the API')
    parser.add_argument('--no-repair', action='store_true', help='Stop at the first failure; at most 2 API calls')
    parser.add_argument('--model', default='deepseek-flash')
    parser.add_argument('--output-dir', type=Path, help='A new run directory; existing directories are refused')
    parser.add_argument('--network-retries', type=int, choices=(0,1), default=0, help='Explicit retries per logical API request; default 0 for compatibility')
    args = parser.parse_args()
    run_dir = args.output_dir or Path('m5_runs') / ('pipeline_' + uuid.uuid4().hex)
    if run_dir.exists():
        print('ERROR [OUTPUT_EXISTS]: Choose a new output directory.')
        return 1
    try:
        if args.input.stat().st_size > 5_000_000:
            raise M5Error('INPUT_FILE_TOO_LARGE', 'Input exceeds 5 MB.')
        raw = args.input.read_bytes()
        data = strict_json(raw.decode('utf-8-sig'))
        input_info = {'input_file':str(args.input.resolve()), 'input_file_sha256':hashlib.sha256(raw).hexdigest()}
        run_dir.mkdir(parents=True, exist_ok=False)
        report_path = run_dir / 'pipeline.json'
        previous_stage = None

        def checkpoint(state):
            nonlocal previous_stage
            stage = state.get('active_stage')
            if stage and stage != previous_stage:
                print('Stage: ' + stage, flush=True)
                previous_stage = stage
            temp = run_dir / ('pipeline.' + uuid.uuid4().hex + '.tmp')
            with temp.open('x', encoding='utf-8') as stream:
                json.dump({**state, **input_info}, stream, ensure_ascii=False, indent=2, allow_nan=False)
            os.replace(temp, report_path)

        checkpoint({'schema_version':'m5_pipeline.v1','status':'STARTING', 'publication_ready':False})
        print('Mode: local preflight; API calls: 0.' if args.dry_run else
              'Mode: paid DeepSeek generation and review; at most ' + str((2 if args.no_repair else 4)*(1+args.network_retries)) +
              ' API calls. Repair limit: ' + ('0.' if args.no_repair else '1 shared repair.'))
        result = run_pipeline(data, dry_run=args.dry_run, model=args.model,
                              allow_repair=not args.no_repair, checkpoint=checkpoint, network_retries=args.network_retries)
        print('Status: ' + result['status'])
        print('Gate: ' + result['gate'])
        print('API calls in this run: ' + str(len(result['api_calls'])))
        print('Repair used: ' + str(result['repair_used']).lower())
        if args.dry_run and result['status'] == 'READY_FOR_PIPELINE':
            print('Evidence items: ' + str(len(result['preview']['evidence'])))
            print('Planned maximum API calls: ' + str(result['max_api_calls']))
        if result.get('answer_record'):
            print('Draft for human review; publication_ready=false.')
            print(result['answer'])
            sources_text = render_sources(result['sources'])
            if sources_text: print(sources_text)
            answer_path = run_dir/'answer.json'
            with answer_path.open('x',encoding='utf-8') as stream:
                json.dump(result['answer_record'],stream,ensure_ascii=False,indent=2,allow_nan=False)
            print('Draft record saved: ' + str(answer_path.resolve()))
        elif result['gate'] == 'BLOCKED':
            print('The draft was blocked. No answer was released. Rejected attempts remain in the diagnostic record.')
        if result.get('error'):
            print('Error: ' + result['error']['code'] + '; ' + result['error']['message'])
        print_budget(result.get('preview', {}).get('token_budget'))
        for attempt in result.get('attempts', []):
            review = attempt.get('review')
            if review and review.get('token_budget'):
                print('Review budget for attempt ' + str(attempt['number']) + ':')
                print_budget(review['token_budget'])
        print('Pipeline record saved: ' + str(report_path.resolve()))
        return 1 if result['status'] == 'ERROR' else 0
    except (OSError, UnicodeError, ValueError, M5Error):
        print('ERROR: Could not read input or complete/save the run. Inspect the input and output paths and any existing pipeline record. Do not rerun blindly: an API request may already have used credit.')
        print('Run directory: ' + str(run_dir.resolve()))
        return 1
    except KeyboardInterrupt:
        print('\nCancelled. Inspect the saved run directory before retrying: ' + str(run_dir.resolve()))
        return 130


if __name__ == '__main__':
    raise SystemExit(main())
