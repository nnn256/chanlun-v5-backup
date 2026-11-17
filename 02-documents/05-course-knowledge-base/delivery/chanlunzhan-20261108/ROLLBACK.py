"""Restore the two baseline files and archive only this extension's additions.

Default is a dry run. Use --execute to apply; --root supports an independent drill.
Existing files with unexpected hashes are not overwritten.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil
import sys

HERE = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=HERE.parents[1])
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    baseline = json.loads((HERE / "baseline.json").read_text(encoding="utf-8"))
    modified = json.loads((HERE / "MODIFIED_FILES.json").read_text(encoding="utf-8"))
    by_name = {r["file"]: r for r in modified["modified_existing"]}
    checked = []
    for item in baseline:
        target = (root / item["file"]).resolve()
        pristine = (HERE / "baseline" / item["file"]).resolve()
        if not target.is_relative_to(root) or not target.is_file():
            raise ValueError("Missing or out-of-root restoration target")
        if digest(pristine) != item["sha256"]:
            raise ValueError("Pristine backup hash mismatch")
        if digest(target) not in {item["sha256"], by_name[item["file"]]["sha256"]}:
            raise ValueError("File changed since delivery; refusing overwrite: " + str(target))
        checked.append((target, pristine))
    additions = [(root / name).resolve() for name in modified["created_roots"]]
    if any(not p.is_relative_to(root) or p == root for p in additions):
        raise ValueError("Addition path escapes the intended library")
    archive = root / "delivery" / ("chanlunzhan-rollback-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
    if args.execute:
        archive.mkdir(parents=True, exist_ok=False)
        for target, pristine in checked:
            shutil.copy2(pristine, target)
        for target in additions:
            if target.exists():
                destination = archive / target.relative_to(root)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(target), str(destination))
    receipt = {"executed": args.execute, "root": str(root), "archive": str(archive),
               "restored": [{"file": r["file"], "sha256": digest(root / r["file"])} for r in baseline],
               "archive_candidates": [str(p) for p in additions]}
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
