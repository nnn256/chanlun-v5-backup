#!/usr/bin/env python3
"""Causal Chan structure research engine; explicit, reproducible proxy conventions.

No market-order API. CSV input is in chronological order. Use --replay to
produce a first-seen event ledger instead of backdating final-chart labels.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from chanlun_algorithm import Bar, Fractal, load_ohlc, merge_inclusions


CONVENTIONS = {
    "mode": "structure_proxy",
    "inclusion": "directional high/high low/low; initial direction uses close (explicit proxy)",
    "fractal": "strict high AND low three-bar extremum; right merged bar must be sealed",
    "stroke": "alternating, price-polarity checked, >= min_separation merged-bar distance",
    "stroke_final": "endpoint frozen only after a subsequent eligible opposite fractal",
    "segment": "three-stroke overlap seed, extremum extension, reversal crosses last counterstroke start",
    "center": "three segment proxies overlap; seed ZD/ZG fixed; first failed return ends extension",
    "boundary_touch": "touching counts as overlap/re-entry; third point requires strict outside",
    "force": "MACD same-direction histogram area; auxiliary evidence only",
    "signal": "first/second/third structure candidates, no lower-level execution confirmation",
    "limitations": ["not feature-sequence gap case-1/case-2 strict segments",
                    "segment proxy centers are not recursively proven sublevel trend-type centers",
                    "one timeframe does not prove multi-level interval nesting",
                    "first points require two separated centers but force remains an indicator proxy"],
}


def macd(bars: list[Bar]) -> list[float]:
    if not bars:
        return []
    fast = slow = bars[0].close
    dea = 0.0
    hist = []
    for bar in bars:
        fast += 2 / 13 * (bar.close - fast)
        slow += 2 / 27 * (bar.close - slow)
        dif = fast - slow
        dea += 2 / 10 * (dif - dea)
        hist.append(2 * (dif - dea))
    return hist


def strokes_at(bars: list[Bar], separation: int) -> tuple[list[Bar], list[dict], list[dict]]:
    merged = merge_inclusions(bars)
    points: list[Fractal] = []
    # Last merged candle may still absorb future raw candles. A third bar is
    # sealed only when a fourth non-contained merged candle has started.
    for i in range(1, len(merged) - 2):
        left, mid, right = merged[i - 1:i + 2]
        kind = None
        if mid.high > max(left.high, right.high) and mid.low > max(left.low, right.low):
            kind = "top"
        elif mid.high < min(left.high, right.high) and mid.low < min(left.low, right.low):
            kind = "bottom"
        if kind is None:
            continue
        p = Fractal(kind, i, mid.high if kind == "top" else mid.low,
                    mid.source_end, merged[i + 2].source_start)
        if not points:
            points.append(p)
        elif points[-1].kind == kind:
            if (p.price > points[-1].price) if kind == "top" else (p.price < points[-1].price):
                points[-1] = p
        elif p.index - points[-1].index >= separation:
            price_valid = p.price > points[-1].price if kind == "top" else p.price < points[-1].price
            if price_valid:
                points.append(p)
    strokes = []
    for i, (a, b) in enumerate(zip(points, points[1:])):
        finalized = i + 2 < len(points)
        strokes.append({"id": i, "direction": "up" if a.kind == "bottom" else "down",
                        "start": a.source_index, "end": b.source_index,
                        "start_price": a.price, "end_price": b.price,
                        "low": min(a.price, b.price), "high": max(a.price, b.price),
                        "confirmed_at": points[i + 2].confirmed_at if finalized else None,
                        "available_at": b.confirmed_at, "finalized": finalized,
                        "definition_mode": "swing_proxy"})
    return merged, [asdict(p) for p in points], strokes


def segment_proxies(strokes: list[dict], hist: list[float]) -> list[dict]:
    """Directional reversal proxy. Never group every three strokes blindly."""
    ss = [s for s in strokes if s["finalized"]]
    result = []
    start = 0
    while start + 2 < len(ss):
        seed = ss[start:start + 3]
        if max(s["low"] for s in seed) >= min(s["high"] for s in seed):
            start += 1
            continue
        direction = seed[0]["direction"]
        endpoint = start + 2
        best = ss[endpoint]["end_price"]
        reversal_at = None
        for j in range(start + 3, len(ss)):
            s = ss[j]
            if s["direction"] == direction:
                if (s["end_price"] >= best if direction == "up" else s["end_price"] <= best):
                    endpoint, best = j, s["end_price"]
            else:
                threshold = ss[endpoint]["start_price"]
                if (s["end_price"] < threshold if direction == "up" else s["end_price"] > threshold):
                    reversal_at = j
                    break
        if reversal_at is None:
            break  # provisional tail is exposed through strokes, not promoted
        group = ss[start:endpoint + 1]
        a, b = group[0], group[-1]
        lo, hi = a["start"], b["end"]
        sign = 1 if direction == "up" else -1
        area = sum(max(0.0, sign * x) for x in hist[lo:hi + 1])
        result.append({"id": len(result), "direction": direction,
                       "start": lo, "end": hi, "start_price": a["start_price"],
                       "end_price": b["end_price"],
                       "low": min(s["low"] for s in group), "high": max(s["high"] for s in group),
                       "components": [s["id"] for s in group],
                       "confirmed_at": ss[reversal_at]["confirmed_at"],
                       "force": area, "force_mode": "indicator_proxy",
                       "definition_mode": "segment_proxy"})
        start = endpoint + 1
    return result


def centers_at(moves: list[dict]) -> list[dict]:
    """Freeze the original overlap and inspect leave/first-return pairs."""
    centers = []
    i = 0
    while i + 2 < len(moves):
        seed = moves[i:i + 3]
        zd, zg = max(x["low"] for x in seed), min(x["high"] for x in seed)
        if zd >= zg:
            i += 1
            continue
        end, j, failed_return = i + 2, i + 3, None
        while j + 1 < len(moves):
            leave, ret = moves[j:j + 2]
            if leave["direction"] == "up" and ret["low"] > zg:
                failed_return = {"side": "buy", "leave": j, "return": j + 1}
                break
            if leave["direction"] == "down" and ret["high"] < zd:
                failed_return = {"side": "sell", "leave": j, "return": j + 1}
                break
            end = j + 1
            j += 2
        group = moves[i:end + 1]
        centers.append({"id": len(centers), "zd": zd, "zg": zg,
                        "dd": min(x["low"] for x in group), "gg": max(x["high"] for x in group),
                        "start": seed[0]["start"], "end": group[-1]["end"],
                        "seed_components": list(range(i, i + 3)),
                        "components": list(range(i, end + 1)),
                        "confirmed_at": max(x["confirmed_at"] for x in seed),
                        "state": "departed" if failed_return else "extension" if end > i + 2 else "formed",
                        "failed_return": failed_return, "definition_mode": "segment_proxy"})
        if failed_return:
            i = failed_return["return"]
        else:
            break
    return centers


def structural_signals(moves: list[dict], centers: list[dict]) -> list[dict]:
    signals = []

    def emit(kind: str, move: dict, **evidence) -> dict:
        side = "buy" if "buy" in kind else "sell"
        signal = {"signal_class": kind, "side": side, "anchor": move["end"],
                  "available_at": move["confirmed_at"], "price": move["end_price"],
                  "invalidation": move["end_price"], "status": "candidate",
                  "definition_mode": "signal_proxy", "lower_level_trigger": "missing",
                  "next_observation": "lower-level structural turn and invalidation boundary",
                  **evidence}
        signals.append(signal)
        return signal

    for c in centers:
        failed = c["failed_return"]
        if failed:
            ret = moves[failed["return"]]
            emit(f"third_{failed['side']}_candidate", ret, center_id=c["id"],
                 zg=c["zg"], zd=c["zd"], leave_move=failed["leave"],
                 return_move=failed["return"],
                 invalidation=c["zg"] if failed["side"] == "buy" else c["zd"])

    for n in range(1, len(centers)):
        c0, c1 = centers[n - 1:n + 1]
        side = "buy" if c1["gg"] < c0["dd"] else "sell" if c1["dd"] > c0["gg"] else None
        if side is None:
            continue
        direction = "down" if side == "buy" else "up"
        enter = c1["seed_components"][0] - 1
        leave = c1["components"][-1] + 1
        if enter < 0 or leave >= len(moves):
            continue
        a, b = moves[enter], moves[leave]
        extreme = b["end_price"] < a["end_price"] if side == "buy" else b["end_price"] > a["end_price"]
        if a["direction"] != direction or b["direction"] != direction or not extreme:
            continue
        if a["force"] <= 0 or b["force"] >= a["force"]:
            continue
        first = emit(f"first_{side}_candidate", b, center_id=c1["id"],
                     compared_move_a=enter, compared_move_b=leave,
                     divergence_type="same_direction_MACD_area_proxy",
                     forces=[a["force"], b["force"]])
        if leave + 2 < len(moves):
            rebound, ret = moves[leave + 1:leave + 3]
            survives = ret["end_price"] > b["end_price"] if side == "buy" else ret["end_price"] < b["end_price"]
            if rebound["direction"] != direction and ret["direction"] == direction and survives:
                emit(f"second_{side}_candidate", ret, center_id=c1["id"],
                     first_anchor=first["anchor"], first_return=True,
                     invalidation=b["end_price"])
    return sorted(signals, key=lambda x: (x["available_at"], x["signal_class"]))


def analyze(bars: list[Bar], separation: int = 4, level: str = "unspecified") -> dict:
    if separation < 4:
        raise ValueError("min_separation must be >=4 for this declared convention")
    merged, fractals, strokes = strokes_at(bars, separation)
    hist = macd(bars)
    moves = segment_proxies(strokes, hist)
    centers = centers_at(moves)
    state = "untradable_unclear"
    if centers:
        state = "center_oscillation"
        if len(centers) > 1:
            a, b = centers[-2:]
            state = "uptrend_proxy" if b["dd"] > a["gg"] else "downtrend_proxy" if b["gg"] < a["dd"] else "higher_level_overlap"
    return {"as_of": bars[-1].index if bars else None, "input_bars": len(bars),
            "trade_level": level, "review_level": "missing", "confirm_level": "missing",
            "trigger_level": "missing", "definition_mode": "structure_proxy",
            "structure_completeness": "proxy_chain", "approximation_loss": CONVENTIONS["limitations"],
            "conventions": CONVENTIONS, "min_separation": separation,
            "merged": [asdict(x) for x in merged], "fractals": fractals,
            "strokes": strokes, "segments": moves, "centers": centers,
            "current_state": state, "signal_candidates": structural_signals(moves, centers),
            "execution_allowed": False, "action": "observe"}


def replay(bars: list[Bar], separation: int = 4, level: str = "unspecified") -> list[dict]:
    """Recompute prefixes; never backdate knowledge from the final chart.

    Deliberately quadratic reference implementation for audit, not tick-scale use.
    First-seen records remain immutable even if later chart interpretation changes.
    """
    events = []
    seen = set()
    active: list[dict] = []
    for stop in range(5, len(bars) + 1):
        bar = bars[stop - 1]
        for previous in list(active):
            broken = bar.low <= previous["invalidation"] if previous["side"] == "buy" else bar.high >= previous["invalidation"]
            if broken:
                events.append({"event": "invalidated", "signal_id": previous["signal_id"],
                               "available_at": bar.index, "invalidation": previous["invalidation"]})
                active.remove(previous)
        snapshot = analyze(bars[:stop], separation, level)
        for signal in snapshot["signal_candidates"]:
            key = (signal["signal_class"], signal["anchor"])
            if key in seen:
                continue
            seen.add(key)
            event = {**signal, "signal_id": f"{key[0]}:{key[1]}", "event": "first_seen",
                     "available_at": bar.index, "exec_not_before": bar.index + 1,
                     "trade_level": level, "confirm_level": "missing", "trigger_level": "missing",
                     "structure_completeness": "proxy_chain", "execution_allowed": False}
            # If its own delayed confirmation already violates the boundary,
            # retain evidence as stale rather than issuing an actionable candidate.
            later = bars[signal["anchor"] + 1:stop]
            broken = any(x.low <= signal["invalidation"] for x in later) if signal["side"] == "buy" else any(x.high >= signal["invalidation"] for x in later)
            event["status"] = "stale_on_confirmation" if broken else "candidate"
            events.append(event)
            if not broken:
                active.append(event)
    return events


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", type=Path)
    parser.add_argument("-o", "--output", type=Path, default=Path("chanlun_report.json"))
    parser.add_argument("--level", required=True, help="e.g. 5m, 30m, daily; label, not recursive proof")
    parser.add_argument("--min-separation", type=int, default=4)
    parser.add_argument("--replay", action="store_true")
    args = parser.parse_args()
    bars = load_ohlc(args.csv)
    report = analyze(bars, args.min_separation, args.level)
    report["input_sha256"] = hashlib.sha256(args.csv.read_bytes()).hexdigest()
    if args.replay:
        report["events"] = replay(bars, args.min_separation, args.level)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"bars={len(bars)} segments={len(report['segments'])} centers={len(report['centers'])} output={args.output}")


if __name__ == "__main__":
    main()
