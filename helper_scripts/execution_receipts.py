"""Record local PMT execution receipts and produce deterministic calibration reports.

Usage:
    python helper_scripts/execution_receipts.py record --task-id task_<32 hex> \
        --executor codex --outcome success --verified-by human
    python helper_scripts/execution_receipts.py report [--json]

Receipts contain observed facts, hashes, and human/tool verification only. Model response
bodies and credentials are rejected or redacted; the roadmap remains the task database.
"""

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

DEFAULT_STORE = Path(__file__).with_name("execution_receipts.json")
TASK_ID_RE = re.compile(r"^task_[0-9a-f]{32}$")
SECRET_RE = re.compile(
    r"(?i)(bearer\s+[A-Za-z0-9._~+/=-]+|(?:api[_ -]?key|token|password)\s*[:=]\s*\S+)"
)
OUTCOMES = ("success", "rework", "escalated", "failed")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def redact(text: str) -> str:
    return SECRET_RE.sub("[REDACTED]", text)


def load_store(path: Path) -> dict:
    if not path.exists():
        return {"schema_version": 1, "receipts": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1 or not isinstance(data.get("receipts"), list):
        raise ValueError("unsupported execution receipt schema")
    return data


def record_receipt(path: Path, receipt: dict) -> dict:
    """Validate, redact, append, and atomically save one locally asserted receipt."""
    if not TASK_ID_RE.fullmatch(receipt.get("task_id", "")):
        raise ValueError("task_id must be task_ followed by 32 lowercase hex characters")
    if receipt.get("final_outcome") not in OUTCOMES:
        raise ValueError(f"final_outcome must be one of: {', '.join(OUTCOMES)}")
    if receipt.get("verified_by") not in {"human", "tooling"}:
        raise ValueError("verified_by must be human or tooling")
    if "model_output" in receipt:
        raise ValueError("model output is not authoritative receipt data")
    store = load_store(path)
    sequence = 1 + max(
        (item["attempt"] for item in store["receipts"] if item["task_id"] == receipt["task_id"]),
        default=0,
    )
    clean = {
        "task_id": receipt["task_id"],
        "attempt": sequence,
        "executor": receipt.get("executor", "unknown"),
        "prompt_sha256": receipt.get("prompt_sha256", ""),
        "context_sha256": receipt.get("context_sha256", ""),
        "context_chars": int(receipt.get("context_chars", 0)),
        "artifacts_changed": sorted(set(receipt.get("artifacts_changed", []))),
        "verification": redact(receipt.get("verification", "")),
        "verified_by": receipt["verified_by"],
        "human_corrections": redact(receipt.get("human_corrections", "")),
        "escalation": redact(receipt.get("escalation", "")),
        "final_outcome": receipt["final_outcome"],
    }
    store["receipts"].append(clean)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".new")
    temp.write_text(json.dumps(store, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)
    return clean


def calibration_report(store: dict) -> dict:
    """Aggregate only recorded outcomes; never infer success from executor output."""
    groups = {}
    for receipt in store["receipts"]:
        group = groups.setdefault(
            receipt["executor"],
            {
                "attempts": 0,
                "success": 0,
                "rework": 0,
                "escalated": 0,
                "failed": 0,
                "context_chars_total": 0,
            },
        )
        group["attempts"] += 1
        group[receipt["final_outcome"]] += 1
        group["context_chars_total"] += receipt.get("context_chars", 0)
    for group in groups.values():
        group["context_chars_average"] = (
            group.pop("context_chars_total") // group["attempts"] if group["attempts"] else 0
        )
    return {
        "schema_version": 1,
        "attempts": len(store["receipts"]),
        "executors": {key: groups[key] for key in sorted(groups)},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", type=Path, default=DEFAULT_STORE)
    sub = parser.add_subparsers(dest="command", required=True)
    record = sub.add_parser("record")
    record.add_argument("--task-id", required=True)
    record.add_argument("--executor", required=True)
    record.add_argument("--outcome", required=True, choices=OUTCOMES)
    record.add_argument("--verified-by", required=True, choices=("human", "tooling"))
    record.add_argument("--prompt-file", type=Path)
    record.add_argument("--context-file", type=Path)
    record.add_argument("--artifact", action="append", default=[])
    record.add_argument("--verification", default="")
    record.add_argument("--human-corrections", default="")
    record.add_argument("--escalation", default="")
    report = sub.add_parser("report")
    report.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "record":
            prompt = args.prompt_file.read_text(encoding="utf-8") if args.prompt_file else ""
            context = args.context_file.read_text(encoding="utf-8") if args.context_file else ""
            saved = record_receipt(
                args.store,
                {
                    "task_id": args.task_id,
                    "executor": args.executor,
                    "final_outcome": args.outcome,
                    "verified_by": args.verified_by,
                    "prompt_sha256": sha256_text(prompt) if prompt else "",
                    "context_sha256": sha256_text(context) if context else "",
                    "context_chars": len(context),
                    "artifacts_changed": args.artifact,
                    "verification": args.verification,
                    "human_corrections": args.human_corrections,
                    "escalation": args.escalation,
                },
            )
            print(json.dumps(saved, sort_keys=True))
        else:
            result = calibration_report(load_store(args.store))
            if args.json:
                print(json.dumps(result, indent=2, sort_keys=True))
            else:
                print(f"Execution attempts: {result['attempts']}")
                for name, facts in result["executors"].items():
                    print(
                        f"- {name}: {facts['success']} success, {facts['rework']} rework, "
                        f"{facts['escalated']} escalated, {facts['failed']} failed"
                    )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
