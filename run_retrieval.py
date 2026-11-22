"""Run the delivered M4 initialization and query it from a terminal."""
import argparse
import json
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", nargs="?", default="Which celestial body prompted the 2006 vote on Pluto?")
    parser.add_argument("--mode", choices=["dense", "bm25", "hybrid"], default="hybrid")
    parser.add_argument("--strategy", choices=list("ABC"), default="C")
    parser.add_argument("--allow-model-download", action="store_true")
    parser.add_argument("--check", action="store_true", help="Run live unit and database integration checks")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    os.chdir(root)
    base = root / ".local-m4"
    os.environ.setdefault("M4_WORK_BASE", str(base))
    os.environ.setdefault("M4_DATA_ROOT", str(base / "m3_data"))
    os.environ.setdefault("M4_RUN_DB", str(base / "runtime_chroma"))
    if args.allow_model_download:
        os.environ["M4_ALLOW_MODEL_DOWNLOAD"] = "1"
    notebook = json.loads((root / "M4_HANDOFF.ipynb").read_text(encoding="utf-8"))
    namespace = {"__name__": "m4_initialization"}
    schema_path = root / "schemas/retrieval_response.v2.schema.json"
    original_schema = schema_path.read_bytes()
    # Reuse the published initialization, including all model/index identity checks.
    for index in (2, 4, 6, 8):
        if index == 6 and args.allow_model_download:
            from huggingface_hub import snapshot_download
            spec = namespace["manifests"]["B"]["embedding"]
            snapshot_download(
                repo_id=spec["model"], revision=spec["revision"],
                cache_dir=str(namespace["BASE"] / "model_cache"),
                allow_patterns=["*.json", "*.safetensors", "vocab.txt"],
            )
            # The PyTorch snapshot is ready; skip unused ONNX/TF/OpenVINO weights.
            os.environ["M4_ALLOW_MODEL_DOWNLOAD"] = "0"
        cell = notebook["cells"][index]
        assert cell["cell_type"] == "code"
        exec(compile("".join(cell["source"]), f"M4_HANDOFF.ipynb:cell{index}", "exec"), namespace)
        if index == 8:
            # Workshop validates and rewrites the schema; preserve its release bytes.
            schema_path.write_bytes(original_schema)
    workshop = namespace["w"]
    output = Path(os.environ["M4_WORK_BASE"])
    if args.check:
        example_dir = root / "documents/m4/contract_examples_v2"
        originals = {p: p.read_bytes() for p in example_dir.glob("*.json")}
        try:
            checks = {"unit": workshop.unit_checks(), "integration": workshop.integration_checks()}
            for path in originals:
                (output / ("local_contract_" + path.name)).write_bytes(path.read_bytes())
        finally:
            for path, content in originals.items():
                path.write_bytes(content)
        namespace["save_json"](output / "local_checks.json", checks)
        print(json.dumps(checks, indent=2))
        assert checks["integration"]["status"] == "PASS", checks
    response = workshop.retrieve(args.query, strategy=args.strategy, mode=args.mode, top_k=5, candidate_k=30, rrf_constant=60)
    namespace["save_json"](output / "last_response.json", response)
    if response["status"] != "OK":
        raise RuntimeError(response)
    selected, context, tokens = workshop.pack(response["results"], token_budget=1024)
    namespace["save_json"](output / "last_context.json", {"context": context, "tokens": tokens, "chunk_ids": [row["chunk_id"] for row in selected]})
    print(f"\nQuery: {args.query}\nStatus: {response['status']} | {args.mode}/{args.strategy}")
    for row in response["results"]:
        print(f"\n{row['rank']}. {json.dumps(row['citation'], ensure_ascii=False)}\n{row['text'][:500]}")
    print(f"\nSaved response: {output / 'last_response.json'}")


if __name__ == "__main__":
    main()
