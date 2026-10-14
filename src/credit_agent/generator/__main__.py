"""CLI: ``python -m credit_agent.generator --n 40 --seed 42``.

Writes one ground-truth JSON per file plus a manifest with batch statistics. Output is
deterministic: the same arguments always produce byte-identical files.
"""

from __future__ import annotations

import argparse
import json
import shutil
from collections import Counter
from datetime import date
from pathlib import Path

from credit_agent.config import REPO_ROOT, get_settings
from credit_agent.generator.build import generate_batch
from credit_agent.generator.manual import build_manual
from credit_agent.generator.models import GeneratedFile
from credit_agent.generator.render import render_document
from credit_agent.policy import load_policy

DEFAULT_OUT = REPO_ROOT / "data" / "ground_truth"
DEFAULT_SYNTHETIC = REPO_ROOT / "data" / "synthetic"


def build_manifest(
    files: list[GeneratedFile], *, seed: int, policy_version: str, as_of: date
) -> dict[str, object]:
    truths = [f.ground_truth for f in files]
    return {
        "seed": seed,
        "n_files": len(files),
        "policy_version": policy_version,
        "as_of_date": as_of.isoformat(),
        "split": dict(Counter(t.split for t in truths)),
        "owner": dict(Counter(t.owner_id for t in truths)),
        "expected_status": dict(Counter(t.expected_status.value for t in truths)),
        "defects_per_file": {
            str(k): v for k, v in sorted(Counter(len(t.defects) for t in truths).items())
        },
        "defect_types": dict(Counter(d.defect_type.value for t in truths for d in t.defects)),
        "near_threshold_defects": sum(d.near_threshold for t in truths for d in t.defects),
        "hard_negative_kinds": dict(Counter(h.kind for t in truths for h in t.hard_negatives)),
        "requires_mandatory_review": sum(t.requires_mandatory_review for t in truths),
        "files": {t.application_id: {"split": t.split, "owner": t.owner_id} for t in truths},
    }


def write_ground_truth(
    files: list[GeneratedFile], out_dir: Path, manifest: dict[str, object]
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in out_dir.glob("APP-*.json"):
        stale.unlink()
    for f in files:
        path = out_dir / f"{f.application.application_id}.json"
        path.write_text(f.model_dump_json(indent=2) + "\n", encoding="utf-8", newline="\n")
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )


def write_pdfs(files: list[GeneratedFile], synthetic_dir: Path) -> int:
    """One folder per application; returns the number of PDFs written."""
    synthetic_dir.mkdir(parents=True, exist_ok=True)
    for stale in synthetic_dir.glob("APP-*"):
        if stale.is_dir():
            shutil.rmtree(stale)
    count = 0
    for f in files:
        folder = synthetic_dir / f.application.application_id
        folder.mkdir()
        for doc in f.documents:
            render_document(doc, folder / doc.filename)
            count += 1
    return count


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Generate synthetic credit files and ground truth."
    )
    parser.add_argument("--n", type=int, default=40, help="number of files")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--as-of", type=date.fromisoformat, default=None)
    parser.add_argument("--synthetic-dir", type=Path, default=DEFAULT_SYNTHETIC)
    parser.add_argument(
        "--manual-path", type=Path, default=None, help="default: next to the policy YAML"
    )
    parser.add_argument("--skip-pdfs", action="store_true", help="write ground truth only")
    args = parser.parse_args(argv)

    policy = load_policy()
    as_of = args.as_of or get_settings().as_of_date
    files = generate_batch(args.n, args.seed, policy, as_of)
    manifest = build_manifest(
        files, seed=args.seed, policy_version=policy.policy_version, as_of=as_of
    )
    write_ground_truth(files, args.out_dir, manifest)
    if not args.skip_pdfs:
        n_pdfs = write_pdfs(files, args.synthetic_dir)
        manual_path = args.manual_path or get_settings().policy_path.with_suffix(".pdf")
        pages = build_manual(policy, manual_path)
        print(f"Rendered {n_pdfs} PDFs in {args.synthetic_dir}")
        print(f"Policy manual: {manual_path} ({pages} pages)")

    print(f"Generated {len(files)} files (seed={args.seed}, as_of={as_of}) in {args.out_dir}")
    for key in ("split", "owner", "expected_status", "defects_per_file", "defect_types"):
        print(f"  {key}: {manifest[key]}")


if __name__ == "__main__":
    main()
