import argparse
import hashlib
import json
import sys
import uuid
from pathlib import Path
from .api import M5Error, strict_json
from .generator import generate_answer
from .token_budget import print_budget


def main():
    parser = argparse.ArgumentParser(description="M5: validate M4 input and generate an English draft with evidence.")
    parser.add_argument("--input", required=True, type=Path, help="M4 v1/v2 response or packed M4 example JSON")
    parser.add_argument("--output", type=Path, help="Create a result file; existing files are never overwritten")
    parser.add_argument("--dry-run", action="store_true", help="Validate input and evidence without calling the API")
    parser.add_argument("--model", default="deepseek-flash")
    parser.add_argument("--repair-once", action="store_true", help="Allow one repair for generation/citation errors; at most 2 API calls")
    args = parser.parse_args()
    output = args.output or Path("m5_runs") / ("m5_" + uuid.uuid4().hex + ".json")
    if output.exists():
        print("ERROR [OUTPUT_EXISTS]: Choose a new output filename.")
        return 1
    if output.resolve() == args.input.resolve():
        print("ERROR [OUTPUT_CONFLICT]: Output must not overwrite input.")
        return 1
    try:
        if args.input.stat().st_size > 5_000_000:
            raise M5Error("INPUT_FILE_TOO_LARGE", "Input JSON exceeds the 5 MB limit.")
        raw = args.input.read_bytes()
        retrieval = strict_json(raw.decode('utf-8-sig'))
        print("Mode: local validation only; no API calls." if args.dry_run else
              "Mode: submit valid evidence to DeepSeek using account credit; " + ("at most 2 calls." if args.repair_once else "at most 1 call."))
        result = generate_answer(retrieval, dry_run=args.dry_run, model=args.model, repair_once=args.repair_once)
        result['input_file_sha256'] = hashlib.sha256(raw).hexdigest()
        result['input_file'] = str(args.input.resolve())
    except (M5Error, OSError, UnicodeError) as exc:
        code = exc.code if isinstance(exc, M5Error) else "INPUT_FILE_ERROR"
        message = str(exc) if isinstance(exc, M5Error) else "Cannot read input. Check the path, permissions and UTF-8 encoding."
        result = {"schema_version": "answer_response.v1", "request_id": None, "status": "ERROR",
                  "claims": [], "sources": [], "answer": "", "missing_information": [],
                  "review_required": False, "publication_ready": False,
                  "validation": {"input": "fail", "support": "not_applicable"},
                  "generation": {"calls": [], "input_tokens": 0, "output_tokens": 0},
                  "error": {"code": code, "message": message}}
    except KeyboardInterrupt:
        print("\nCancelled.")
        return 130
    print("Status: " + result["status"])
    if result.get("review_required"):
        print("Draft for review: support and answer scope have not yet been verified.")
    if result.get("answer"):
        print(result["answer"])
    if result["status"] == "READY_FOR_GENERATION":
        if result.get('m4_input'):
            meta = result['m4_input']
            print('M4 input schema: ' + meta['source_schema_version'])
            print('Retrieved candidates: ' + str(meta['candidate_count']))
            print('Selected by M4/input: ' + str(len(meta['selected_chunk_ids'])))

            print('Live retrieval in this run: no; reading saved M4 output.')
        print("Evidence items: " + str(len(result["evidence"])))
        for evidence in result["evidence"]:
            print(evidence["source_id"] + " -> " + evidence["chunk_id"])
    print_budget(result.get("token_budget"))
    print("API calls in this run: " + str(len(result["generation"]["calls"])))
    if result.get("error"):
        print("Error: " + result["error"]["code"] + "; " + result["error"]["message"])
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8") as handle:
            json.dump(result, handle, ensure_ascii=False, indent=2, allow_nan=False)
        print("Result saved: " + str(output.resolve()))
    except OSError:
        print("ERROR [OUTPUT_WRITE_ERROR]: Cannot save output. Check the path and permissions.")
        return 1
    return 1 if result["status"] == "ERROR" else 0


if __name__ == "__main__":
    raise SystemExit(main())
