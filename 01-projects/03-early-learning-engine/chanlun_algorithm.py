#!/usr/bin/env python3
"""A deterministic Chanlun structure proxy for OHLC CSV research.

This implementation is explicit about approximation: segment and center
construction are proxies, and its output is not an execution recommendation.
"""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


@dataclass
class Bar:
    index: int
    high: float
    low: float
    open: float
    close: float
    source_start: int
    source_end: int


@dataclass
class Fractal:
    kind: str
    index: int
    price: float
    source_index: int
    confirmed_at: int


@dataclass
class Stroke:
    direction: str
    start: Fractal
    end: Fractal
    high: float
    low: float
    confirmed_at: int


def load_ohlc(path: Path) -> list[Bar]:
    """Read CSV columns date(optional), open, high, low, close (case-insensitive)."""
    with path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames:
            raise ValueError("CSV has no header")
        names = {name.strip().lower(): name for name in reader.fieldnames}
        required = {"open", "high", "low", "close"}
        missing = required - names.keys()
        if missing:
            raise ValueError(f"missing OHLC columns: {', '.join(sorted(missing))}")
        result = []
        for i, row in enumerate(reader):
            o, h, l, c = (float(row[names[key]]) for key in ("open", "high", "low", "close"))
            if not all(map(lambda x: x == x and abs(x) != float("inf"), (o, h, l, c))):
                raise ValueError(f"non-finite OHLC at CSV row {i + 2}")
            if h < l or h < max(o, c) or l > min(o, c):
                raise ValueError(f"invalid OHLC range at CSV row {i + 2}")
            result.append(Bar(i, h, l, o, c, i, i))
    if len(result) < 5:
        raise ValueError("at least five OHLC rows are needed")
    return result


def _contains(a: Bar, b: Bar) -> bool:
    return (a.high >= b.high and a.low <= b.low) or (b.high >= a.high and b.low <= a.low)


def merge_inclusions(bars: Iterable[Bar]) -> list[Bar]:
    """Merge adjacent inclusions; direction follows the latest non-contained move."""
    merged: list[Bar] = []
    direction = 0
    for source in bars:
        current = Bar(len(merged), source.high, source.low, source.open, source.close,
                      source.source_start, source.source_end)
        if not merged:
            merged.append(current)
            continue
        prev = merged[-1]
        if _contains(prev, current):
            if direction == 0:
                direction = 1 if current.close >= prev.close else -1
            if direction > 0:
                prev.high, prev.low = max(prev.high, current.high), max(prev.low, current.low)
            else:
                prev.high, prev.low = min(prev.high, current.high), min(prev.low, current.low)
            prev.close = current.close
            prev.source_end = current.source_end
            continue
        direction = 1 if current.high > prev.high and current.low > prev.low else -1
        merged.append(Bar(len(merged), current.high, current.low, current.open, current.close,
                          current.source_start, current.source_end))
    return merged


def find_fractals(bars: list[Bar]) -> list[Fractal]:
    """Centered 3-bar extrema; confirmed only after the right-hand bar arrives."""
    found: list[Fractal] = []
    for i in range(1, len(bars) - 1):
        left, mid, right = bars[i - 1:i + 2]
        if mid.high > left.high and mid.high > right.high and mid.low > left.low and mid.low > right.low:
            found.append(Fractal("top", i, mid.high, mid.source_end, right.source_end))
        if mid.low < left.low and mid.low < right.low and mid.high < left.high and mid.high < right.high:
            found.append(Fractal("bottom", i, mid.low, mid.source_end, right.source_end))
    return found


def select_alternating_fractals(fractals: list[Fractal], min_separation: int = 4) -> list[Fractal]:
    selected: list[Fractal] = []
    for candidate in fractals:
        if not selected:
            selected.append(candidate)
            continue
        last = selected[-1]
        if candidate.kind == last.kind:
            more_extreme = candidate.price > last.price if candidate.kind == "top" else candidate.price < last.price
            if more_extreme:
                selected[-1] = candidate
        elif candidate.index - last.index >= min_separation:
            selected.append(candidate)
    return selected


def build_strokes(fractals: list[Fractal], min_separation: int = 4) -> list[Stroke]:
    points = select_alternating_fractals(fractals, min_separation)
    strokes = []
    for start, end in zip(points, points[1:]):
        if start.kind == end.kind:
            continue
        strokes.append(Stroke("up" if start.kind == "bottom" else "down", start, end,
                              max(start.price, end.price), min(start.price, end.price), end.confirmed_at))
    return strokes


def build_segment_proxies(strokes: list[Stroke]) -> list[dict]:
    """Non-overlapping groups of three strokes; a research proxy, not strict segment logic."""
    segments = []
    for i in range(0, len(strokes) - 2, 3):
        group = strokes[i:i + 3]
        first, last = group[0], group[-1]
        segments.append({"index": len(segments), "direction": first.direction,
                         "start": first.start.index, "end": last.end.index,
                         "high": max(s.high for s in group), "low": min(s.low for s in group),
                         "components": [i, i + 1, i + 2], "definition_mode": "segment_proxy"})
    return segments


def build_center_proxies(strokes: list[Stroke]) -> list[dict]:
    """Find rolling overlap of three consecutive strokes, extending while overlap persists."""
    centers = []
    i = 0
    while i <= len(strokes) - 3:
        group = strokes[i:i + 3]
        zg = min(s.high for s in group)
        zd = max(s.low for s in group)
        if zd > zg:
            i += 1
            continue
        end = i + 2
        while end + 1 < len(strokes):
            nxt = strokes[end + 1]
            next_zg, next_zd = min(zg, nxt.high), max(zd, nxt.low)
            if next_zd > next_zg:
                break
            zg, zd, end = next_zg, next_zd, end + 1
        centers.append({"index": len(centers), "start_stroke": i, "end_stroke": end,
                        "start": strokes[i].start.index, "end": strokes[end].end.index,
                        "zg": zg, "zd": zd, "gg": max(s.high for s in strokes[i:end + 1]),
                        "dd": min(s.low for s in strokes[i:end + 1]),
                        "components": list(range(i, end + 1)), "state": "oscillating",
                        "definition_mode": "segment_proxy"})
        i = end + 1
    return centers


def _trend(strokes: list[Stroke]) -> str:
    if len(strokes) < 2:
        return "untradable_unclear"
    tail = strokes[-min(6, len(strokes)):]
    if len(tail) >= 4 and tail[-1].end.price > tail[0].start.price and sum(s.direction == "up" for s in tail) >= len(tail) // 2:
        return "uptrend_proxy"
    if len(tail) >= 4 and tail[-1].end.price < tail[0].start.price and sum(s.direction == "down" for s in tail) >= len(tail) // 2:
        return "downtrend_proxy"
    return "center_oscillation_or_transition"


def analyze(bars: list[Bar], min_separation: int = 4) -> dict:
    merged = merge_inclusions(bars)
    fractals = find_fractals(merged)
    strokes = build_strokes(fractals, min_separation)
    segments = build_segment_proxies(strokes)
    centers = build_center_proxies(strokes)
    divergence = None
    same_way = [s for s in strokes if len(strokes) >= 2 and s.direction == strokes[-1].direction]
    if len(same_way) >= 2:
        a, b = same_way[-2:]
        amp_a, amp_b = abs(a.end.price - a.start.price), abs(b.end.price - b.start.price)
        divergence = {"kind": "price_amplitude_proxy", "compared_strokes": [strokes.index(a), strokes.index(b)],
                      "weaker_later_leg": amp_b < amp_a, "amplitudes": [amp_a, amp_b],
                      "definition_mode": "swing_proxy"}
    last_center = centers[-1] if centers else None
    candidates = []
    if last_center and strokes:
        last = strokes[-1]
        c = last_center
        if last.direction == "up" and last.end.price > c["zg"]:
            candidates.append({"class": "third_buy_candidate", "status": "unconfirmed_without_pullback",
                               "trigger_missing": True, "invalidation": f"re-entry below zg={c['zg']}"})
        elif last.direction == "down" and last.end.price < c["zd"]:
            candidates.append({"class": "third_sell_candidate", "status": "unconfirmed_without_rebound",
                               "trigger_missing": True, "invalidation": f"re-entry above zd={c['zd']}"})
    return {
        "definition_mode": "structure_proxy", "structure_completeness": "partial_proxy",
        "approximation_loss": ["segments use fixed groups of three strokes", "centers overlap strokes, not recursive trend types",
                               "divergence compares price amplitude only", "buy/sell points are candidates without lower-level trigger"],
        "review_level": "UNBOUND", "trade_level": "UNBOUND", "confirm_level": "UNBOUND", "trigger_level": "UNBOUND",
        "input_bars": len(bars), "merged_bars": len(merged),
        "merged": [asdict(x) for x in merged], "fractals": [asdict(x) for x in fractals],
        "strokes": [asdict(x) for x in strokes], "segments": segments, "centers": centers,
        "current_state": _trend(strokes), "divergence": divergence, "signal_candidates": candidates,
        "action": "observe", "execution_allowed": False
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", type=Path, help="OHLC CSV with open,high,low,close columns")
    parser.add_argument("-o", "--output", type=Path, help="write JSON report (default: stdout)")
    parser.add_argument("--min-separation", type=int, default=4, help="minimum merged-bar distance between stroke endpoints")
    args = parser.parse_args()
    if args.min_separation < 1:
        parser.error("--min-separation must be positive")
    report = json.dumps(analyze(load_ohlc(args.csv), args.min_separation), ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(report + "\n", encoding="utf-8")
    else:
        print(report)


if __name__ == "__main__":
    main()
