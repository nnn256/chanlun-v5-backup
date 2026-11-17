#!/usr/bin/env python3
"""Align candidate evidence from explicit, timestamped Chanlun level CSVs."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from chanlun_multilevel import LevelSeries, align_level_candidates, load_level_csv, parse_timestamp


def _level_arg(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("use LEVEL=PATH, e.g. 30m=bars_30m.csv")
    level, filename = value.split("=", 1)
    if not level or not filename:
        raise argparse.ArgumentTypeError("both LEVEL and PATH are required")
    return level, Path(filename)


def _load(spec: tuple[str, Path], separation: int) -> tuple[LevelSeries, dict]:
    level, path = spec
    series = load_level_csv(path, level, separation)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    details = {"level": level, "path": str(path.resolve()), "sha256": digest,
               "bars": len(series.bars), "definition_mode": series.report["definition_mode"],
               "structure_completeness": series.report["structure_completeness"],
               "fractal_count": len(series.report["fractals"]),
               "stroke_count": len(series.report["strokes"]),
               "segment_count": len(series.report["segments"]),
               "center_count": len(series.report["centers"])}
    return series, details


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trade", required=True, type=_level_arg, metavar="LEVEL=CSV")
    parser.add_argument("--confirm", type=_level_arg, metavar="LEVEL=CSV")
    parser.add_argument("--trigger", type=_level_arg, metavar="LEVEL=CSV")
    parser.add_argument("--as-of", required=True, type=parse_timestamp,
                        help="timezone-aware ISO-8601 cutoff, e.g. 2026-11-13T10:00:00+08:00")
    parser.add_argument("--min-separation", type=int, default=4)
    parser.add_argument("-o", "--output", type=Path, default=Path("chanlun_bundle_report.json"))
    args = parser.parse_args()
    if args.min_separation < 4:
        parser.error("--min-separation must be >=4 for the declared stroke proxy")

    trade, trade_info = _load(args.trade, args.min_separation)
    confirm = trigger = None
    inputs = {"trade": trade_info}
    if args.confirm:
        confirm, inputs["confirm"] = _load(args.confirm, args.min_separation)
    if args.trigger:
        trigger, inputs["trigger"] = _load(args.trigger, args.min_separation)

    report = {
        "as_of": args.as_of.isoformat(),
        "inputs": inputs,
        "aligned_candidates": align_level_candidates(trade, args.as_of, confirm, trigger),
        "definition_mode": "timestamp_aligned_proxy",
        "structure_completeness": "partial_proxy",
        "approximation_loss": [
            "levels are supplied explicitly; parent/child structure is not inferred recursively",
            "aligned child records are candidates, not strict lower-level confirmations",
            "same-side timestamp alignment does not prove a Chan buy/sell point",
        ],
        "execution_allowed": False,
    }
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"levels={len(inputs)} candidates={len(report['aligned_candidates'])} output={args.output}")


if __name__ == "__main__":
    main()
