"""Check the M6 draft plan and protocol labels. No model and no paid API."""
import argparse
from decimal import Decimal, InvalidOperation
import hashlib
import json
import subprocess
from pathlib import Path

from scripts.m5_generation.api import M5Error
from scripts.m5_generation.billing import validate_pricing

ROOT = Path(__file__).resolve().parents[2]
PLAN = ROOT / 'configs/m6/experiment_plan_draft.json'
TEMPLATE = ROOT / 'configs/m6/run_manifest.template.json'
REVIEW_STAGES = {'review', 'repair_review'}
GENERATION_STAGES = {'generation', 'repair_generation'}
REQUIRED_MANIFEST = (
    'schema_version', 'freeze_status', 'run_id', 'split', 'protocol', 'git_commit',
    'questions_sha256', 'gold_sha256', 'gold_sent_to_model', 'retrieval_run',
    'results_sha256', 'model', 'budget_profile', 'pricing_file', 'output_dir',
    'request_count', 'api_requests', 'total_cost')


def load_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def file_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def cost_is_zero(value):
    if isinstance(value, bool) or value is None:
        return False
    if isinstance(value, (int, float)):
        return value == 0
    if isinstance(value, str):
        try:
            return Decimal(value.strip()) == 0
        except InvalidOperation:
            return False
    return False


def bound_file(root, relative):
    if not isinstance(relative, str) or not relative:
        return None
    path = Path(relative)
    if path.is_absolute() or '..' in path.parts:
        return None
    target = (root / path).resolve()
    if not target.is_relative_to(root.resolve()) or not target.is_file():
        return None
    return target


def hash_error(root, relative, recorded):
    target = bound_file(root, relative)
    if target is None or not isinstance(recorded, str) or file_sha256(target) != recorded:
        return 'recorded hash differs from ' + str(relative)
    return None


def commit_exists(root, commit):
    if not isinstance(commit, str) or len(commit) != 40 or any(char not in '0123456789abcdef' for char in commit):
        return False
    found = subprocess.run(['git', '-C', str(root), 'cat-file', '-e', commit + '^{commit}'],
                           capture_output=True)
    return found.returncode == 0


def worktree_is_dirty(root):
    status = subprocess.run(['git', '-C', str(root), 'status', '--porcelain'], capture_output=True, text=True)
    return status.returncode != 0 or bool(status.stdout.strip())


def commit_file_matches(root, commit, relative, recorded):
    path = Path(relative) if isinstance(relative, str) else None
    if path is None or path.is_absolute() or '..' in path.parts or not isinstance(recorded, str):
        return False
    blob = subprocess.run(['git', '-C', str(root), 'cat-file', 'blob', commit + ':' + relative], capture_output=True)
    return blob.returncode == 0 and hashlib.sha256(blob.stdout).hexdigest() == recorded


def pricing_errors(root, manifest):
    cost = manifest.get('total_cost')
    relative = manifest.get('pricing_file')
    recorded = manifest.get('pricing_sha256')
    if cost is None and not relative and not recorded:
        return []
    if hash_error(root, relative, recorded):
        return ['unknown cost stays null'] if cost is not None and not recorded else ['pricing file does not match its hash']
    try:
        validate_pricing(load_json(bound_file(root, relative)), manifest.get('model'))
    except (M5Error, json.JSONDecodeError, OSError, TypeError):
        return ['pricing rates are not valid for the manifest model']
    return []


def check_plan(plan, root=ROOT):
    errors = []
    if plan.get('schema_version') != 'm6_experiment_plan.v1':
        errors.append('schema')
    if plan.get('freeze_status') != 'not_frozen':
        errors.append('draft plan is not a freeze record')
    for name in ('model', 'budget_profile', 'pricing'):
        if (plan.get(name) or {}).get('status') != 'pending_gateway_confirmation':
            errors.append(name + ' must stay pending until the gateway model is confirmed')
        if (plan.get(name) or {}).get('frozen_model') or (plan.get(name) or {}).get('frozen_profile') or (plan.get(name) or {}).get('frozen_pricing'):
            errors.append(name + ' has a frozen value')
    if plan.get('working_tree_dirty') is not True:
        errors.append('record that the working tree is dirty')
    holdout = plan.get('holdout') or {}
    if holdout.get('included_in_current_runs') is not False or holdout.get('sealed') is not True:
        errors.append('holdout stays sealed and out of the current runs')
    protocols = plan.get('protocols') or {}
    if protocols.get('G2', {}).get('accepted_entry') is not True:
        errors.append('G2 entry')
    for name in ('G0', 'G1'):
        if protocols.get(name, {}).get('accepted_entry') is not False:
            errors.append(name + ' has no accepted entry')
    rules = plan.get('driver_rules') or {}
    for key in ('dry_run_is_protocol', 'no_repair_is_g1', 'strip_review_is_g1'):
        if rules.get(key) is not False:
            errors.append(key)
    for key in ('same_questions', 'same_evidence', 'same_model_and_budget_once_frozen', 'gold_not_sent_to_model'):
        if rules.get(key) is not True:
            errors.append(key)
    g0 = protocols.get('G0') or {}
    g1 = protocols.get('G1') or {}
    g2 = protocols.get('G2') or {}
    if g0.get('automatic_review') is not False or g0.get('repair') is not False or g0.get('citation_support') != 'NOT_APPLICABLE':
        errors.append('G0 keeps uncited facts and does not call review')
    if g0.get('prompt_requires_citation') is not True or g0.get('hard_validation_is_release_gate') is not False:
        errors.append('G0 asks for citations only in the prompt')
    if g0.get('current_generation_prompt_can_be_reused') is not False:
        errors.append('G0 prompt')
    if g1.get('automatic_review') is not False or g1.get('repair') is not False or g1.get('hard_validation_is_release_gate') is not True:
        errors.append('G1 stops after hard validation')
    if g2.get('automatic_review') is not True:
        errors.append('G2 keeps automatic review')
    data = plan.get('data') or {}
    for relative, recorded in (
            (data.get('questions_file'), data.get('questions_sha256')),
            (data.get('gold_file'), data.get('gold_sha256')),
            ((plan.get('holdout') or {}).get('questions_file'), (plan.get('holdout') or {}).get('questions_sha256')),
            ('data/evaluation/m5_holdout.json', (plan.get('holdout') or {}).get('gold_sha256'))):
        message = hash_error(root, relative, recorded)
        if message:
            errors.append(message)
    for relative, recorded in (plan.get('prompts_recorded_not_frozen') or {}).items():
        message = hash_error(root, relative, recorded)
        if message:
            errors.append(message)
    evidence = ((plan.get('retrieval_control') or {}).get('planned_generation_evidence') or {})
    run_json = bound_file(root, str(Path(evidence.get('path', '')) / 'run.json'))
    results = bound_file(root, str(Path(evidence.get('path', '')) / 'results.jsonl'))
    if run_json is None or results is None:
        errors.append('planned evidence run is missing')
    else:
        saved = load_json(run_json)
        actual = file_sha256(results)
        if saved.get('results_sha256') != actual or evidence.get('results_sha256') != actual:
            errors.append('evidence results are not bound to the retrieval run')
        if saved.get('input_sha256') != data.get('questions_sha256'):
            errors.append('evidence input is not bound to the question file')
        if saved.get('config') != evidence.get('config'):
            errors.append('planned evidence config differs from the saved retrieval run')
    return errors


def observed_protocol(pipeline):
    stages = [call.get('stage') for call in pipeline.get('api_calls') or []]
    reviews = [attempt.get('review') for attempt in pipeline.get('attempts') or []]
    if any(stage in REVIEW_STAGES for stage in stages) or any(review is not None for review in reviews):
        return 'G2'
    if pipeline.get('status') == 'READY_FOR_PIPELINE' or pipeline.get('gate') == 'NOT_RUN':
        return 'not_a_protocol'
    if any(stage in GENERATION_STAGES for stage in stages):
        return 'unreviewed_generation'
    return 'not_a_protocol'


def _has_review_or_repair(pipeline):
    stages = [call.get('stage') for call in pipeline.get('api_calls') or []]
    reviews = [attempt.get('review') for attempt in pipeline.get('attempts') or [] if isinstance(attempt, dict)]
    return (any(stage in REVIEW_STAGES or stage == 'repair_generation' for stage in stages)
            or any(review is not None for review in reviews) or pipeline.get('repair_used') is True)


def _one_generation(pipeline):
    calls = pipeline.get('api_calls') or []
    if not calls or any(call.get('stage') != 'generation' for call in calls):
        return False
    primary = [call for call in calls if call.get('network_attempt') == 1 and call.get('logical_call') == 1]
    return len(primary) == 1 and all(call.get('logical_call') == 1 for call in calls)


def _binding_problems(pipeline, protocol, prompt):
    binding = pipeline.get('protocol_binding')
    if not isinstance(binding, dict) or binding.get('protocol') != protocol:
        return ['missing ' + protocol + ' protocol binding']
    if binding.get('automatic_review') is not False or binding.get('repair') is not False:
        return [protocol + ' binding still has review or repair']
    if binding.get('prompt_file') != prompt or binding.get('prompt_sha256') != file_sha256(ROOT / prompt):
        return [protocol + ' prompt hash']
    return []


def g0_problems(pipeline):
    if pipeline.get('gate') == 'NOT_RUN' or pipeline.get('status') == 'READY_FOR_PIPELINE':
        return ['dry run is not G0']
    if _has_review_or_repair(pipeline):
        return ['review or repair is not G0']
    problems = _binding_problems(pipeline, 'G0', 'scripts/m5_generation/prompts/g0_prompt_citation_v1.txt')
    if (pipeline.get('protocol_binding') or {}).get('hard_validation') is not False:
        problems.append('G0 hard validation is not off')
    if not _one_generation(pipeline):
        problems.append('G0 call ledger is not one generation')
    if pipeline.get('gate') == 'PROMPT_CITATION_ONLY':
        if (pipeline.get('validation') or {}).get('citation_ids') != 'prompt_only':
            problems.append('G0 used a citation hard check')
        if not pipeline.get('answer'):
            problems.append('G0 saved no answer')
    elif pipeline.get('gate') in {'ERROR', 'BLOCKED'} and pipeline.get('answer'):
        problems.append('G0 failure released an answer')
    elif pipeline.get('gate') not in {'ERROR', 'BLOCKED'}:
        problems.append('G0 gate is not prompt-only citation')
    return problems


def g1_problems(pipeline):
    if pipeline.get('gate') == 'NOT_RUN' or pipeline.get('status') == 'READY_FOR_PIPELINE':
        return ['dry run is not G1']
    if _has_review_or_repair(pipeline):
        return ['review or repair is not G1']
    problems = _binding_problems(pipeline, 'G1', 'scripts/m5_generation/prompts/generation_v1.txt')
    if (pipeline.get('protocol_binding') or {}).get('hard_validation') != 'release_gate':
        problems.append('G1 hard validation is not the release gate')
    if not _one_generation(pipeline):
        problems.append('G1 call ledger is not one generation')
    if pipeline.get('gate') == 'HARD_VALIDATION_PASSED':
        validation = ((pipeline.get('attempts') or [{}])[-1].get('generation') or {}).get('validation') or {}
        if validation.get('schema') != 'pass' or validation.get('citation_ids') not in {'pass', 'not_applicable'}:
            problems.append('G1 release did not pass hard citation validation')
    elif pipeline.get('gate') in {'ERROR', 'BLOCKED'} and pipeline.get('answer'):
        problems.append('G1 failure released an answer')
    elif pipeline.get('gate') not in {'ERROR', 'BLOCKED'}:
        problems.append('G1 gate is not hard validation')
    return problems


def protocol_problems(declared, pipeline):
    if pipeline.get('gate') == 'NO_RETRIEVAL_EVIDENCE' and not (pipeline.get('api_calls') or []):
        return [] if declared in {'G0', 'G1', 'G2'} else ['declared ' + declared + ' does not match a no-evidence refusal']
    if declared == 'G2':
        observed = observed_protocol(pipeline)
        return [] if observed == 'G2' else ['declared G2 does not match observed ' + observed]
    if declared == 'G0':
        return g0_problems(pipeline)
    if declared == 'G1':
        return g1_problems(pipeline)
    return ['declared ' + declared + ' does not match observed ' + observed_protocol(pipeline)]


def check_manifest(manifest, plan, root=ROOT):
    errors = []
    for key in REQUIRED_MANIFEST:
        if key not in manifest:
            errors.append('missing ' + key)
    if manifest.get('schema_version') != 'm6_run_manifest.v1':
        errors.append('schema')
    if manifest.get('gold_sent_to_model') is not False:
        errors.append('gold stays on the evaluation side')
    if manifest.get('split') == 'holdout' and manifest.get('freeze_status') != 'frozen':
        errors.append('holdout waits for a freeze record')
    errors.extend(pricing_errors(root, manifest))
    if manifest.get('freeze_status') == 'frozen':
        for key in ('git_commit', 'model', 'budget_profile', 'budget_profile_sha256', 'retrieval_run', 'results_sha256'):
            if not manifest.get(key):
                errors.append('frozen manifest needs ' + key)
        if manifest.get('working_tree_dirty') is not False or worktree_is_dirty(root):
            errors.append('frozen record needs a clean working tree')
        commit = manifest.get('git_commit')
        if not commit_exists(root, commit):
            errors.append('frozen commit is not in this repository')
            commit = None
        for label, relative, recorded in (
                ('budget', manifest.get('budget_profile'), manifest.get('budget_profile_sha256')),
                ('questions', manifest.get('questions_file'), manifest.get('questions_sha256')),
                ('gold', manifest.get('gold_file'), manifest.get('gold_sha256'))):
            message = hash_error(root, relative, recorded)
            if message:
                errors.append('frozen ' + label + ': ' + message)
            elif commit and not commit_file_matches(root, commit, relative, recorded):
                errors.append('frozen ' + label + ' is not in the commit')
        prompts = manifest.get('prompt_sha256') or {}
        if not prompts:
            errors.append('frozen record needs prompt hashes')
        for relative, recorded in prompts.items():
            message = hash_error(root, relative, recorded)
            if message:
                errors.append('frozen prompt: ' + message)
            elif commit and not commit_file_matches(root, commit, relative, recorded):
                errors.append('frozen prompt is not in the commit')
        retrieval = manifest.get('retrieval_run')
        run_json = bound_file(root, str(Path(str(retrieval)) / 'run.json')) if retrieval else None
        results = bound_file(root, str(Path(str(retrieval)) / 'results.jsonl')) if retrieval else None
        if run_json is None or results is None or file_sha256(results) != manifest.get('results_sha256'):
            errors.append('frozen evidence results are not bound to the retrieval run')
        elif load_json(run_json).get('results_sha256') != manifest.get('results_sha256'):
            errors.append('frozen evidence results are not bound to the retrieval run')
        if manifest.get('protocol') in {'G0', 'G1'} and manifest.get('driver_accepted') is not True:
            errors.append('frozen G0 or G1 needs an accepted driver')
    return errors


def main():
    parser = argparse.ArgumentParser(description='Check the unfrozen M6 plan without calling a model.')
    parser.add_argument('--plan', type=Path, default=PLAN)
    parser.add_argument('--manifest', type=Path, default=TEMPLATE)
    parser.add_argument('--pipeline', type=Path)
    parser.add_argument('--declare', choices=('G0', 'G1', 'G2'))
    args = parser.parse_args()
    plan = load_json(args.plan)
    errors = check_plan(plan)
    errors.extend('manifest: ' + item for item in check_manifest(load_json(args.manifest), plan, ROOT))
    if args.pipeline or args.declare:
        if not args.pipeline or not args.declare:
            errors.append('protocol check needs both a pipeline and a declared label')
        else:
            errors.extend(protocol_problems(args.declare, load_json(args.pipeline)))
    if errors:
        for item in errors:
            print('ERROR: ' + item)
        return 1
    print('M6 plan draft is consistent and not frozen.')
    print('G0 and G1 have no accepted product entry. The draft plan is not the freeze record.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
