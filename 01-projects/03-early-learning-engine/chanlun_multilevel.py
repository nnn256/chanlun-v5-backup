"""Timestamp-aligned evidence linking for the Chanlun proxy engine.

This module does not infer recursive levels from timeframe ratios. It converts
single-level proxy reports into auditable events and joins independently
supplied levels by their actual timestamps.
"""

from __future__ import annotations

import csv
from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from chanlun_algorithm import Bar, load_ohlc


@dataclass(frozen=True)
class RuleProfile:
    profile_id: str = "course_proxy_v1"
    definition_mode: str = "structure_proxy"
    min_separation: int = 4
    boundary_touch_is_reentry: bool = True
    segment_mode: str = "directional_reversal_proxy"
    center_mode: str = "three_segment_overlap_proxy"


@dataclass(frozen=True)
class StructureNode:
    id: str
    kind: str
    direction: str | None
    level: str
    start_idx: int
    end_idx: int
    confirmed_at: datetime | None
    available_at: datetime | None
    components: tuple[str, ...]
    definition_mode: str
    provisional: bool


@dataclass(frozen=True)
class LevelSeries:
    level: str
    bars: Sequence[Bar]
    timestamps: Sequence[datetime]
    report: Mapping[str, Any]

    @classmethod
    def from_bars(
        cls,
        level: str,
        bars: Sequence[Bar],
        timestamps: Sequence[datetime],
        separation: int = 4,
    ) -> "LevelSeries":
        from chanlun_engine import analyze

        report = analyze(list(bars), separation=separation, level=level)
        return cls(level, tuple(bars), tuple(timestamps), report)

    def __post_init__(self) -> None:
        if not self.level:
            raise ValueError("level must be a non-empty label")
        if len(self.bars) != len(self.timestamps):
            raise ValueError("bars and timestamps must have equal lengths")
        if not self.bars:
            raise ValueError("a level series must contain at least one bar")
        if any(ts.tzinfo is None or ts.utcoffset() is None for ts in self.timestamps):
            raise ValueError("timestamps must be timezone-aware")
        if any(a >= b for a, b in zip(self.timestamps, self.timestamps[1:])):
            raise ValueError("timestamps must be strictly increasing")

    def index_at_or_before(self, timestamp: datetime) -> int:
        return bisect_right(self.timestamps, timestamp) - 1


def _time_at(series: LevelSeries, index: Any) -> datetime | None:
    if not isinstance(index, int) or isinstance(index, bool):
        return None
    if index < 0 or index >= len(series.timestamps):
        return None
    return series.timestamps[index]


def parse_timestamp(value: str) -> datetime:
    """Parse ISO-8601 timestamps; naive local times are rejected."""
    timestamp = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError(f"timestamp must include a timezone offset: {value!r}")
    return timestamp


def load_level_csv(path: Path, level: str, separation: int = 4) -> LevelSeries:
    """Load an OHLC CSV with a timestamp/datetime/date ISO-8601 column."""
    with path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames:
            raise ValueError(f"CSV has no header: {path}")
        names = {name.strip().lower(): name for name in reader.fieldnames}
        time_key = next((names[key] for key in ("timestamp", "datetime", "date") if key in names), None)
        if time_key is None:
            raise ValueError(f"CSV needs timestamp/datetime/date column: {path}")
        timestamps = [parse_timestamp(row[time_key]) for row in reader]
    bars = load_ohlc(path)
    return LevelSeries.from_bars(level, bars, timestamps, separation)


def structure_nodes_from_report(series: LevelSeries) -> list[StructureNode]:
    """Convert report structures into immutable, timestamped component nodes."""
    report = series.report
    nodes: list[StructureNode] = []
    fractal_ids: dict[tuple[int, str], str] = {}

    for i, item in enumerate(report.get("fractals", [])):
        node_id = f"fractal:{series.level}:{i}"
        source = item.get("source_index", item.get("index", -1))
        kind = item.get("kind")
        fractal_ids[(source, kind)] = node_id
        confirmed = _time_at(series, item.get("confirmed_at"))
        nodes.append(StructureNode(node_id, f"{kind}_fractal", None, series.level,
                                   source, source, confirmed, confirmed, (),
                                   item.get("definition_mode", "strict_fractal_proxy"), False))

    stroke_ids: dict[Any, str] = {}
    for i, item in enumerate(report.get("strokes", [])):
        raw_id = item.get("id", i)
        node_id = f"stroke:{series.level}:{raw_id}"
        stroke_ids[raw_id] = node_id
        start_kind = "bottom" if item.get("direction") == "up" else "top"
        end_kind = "top" if item.get("direction") == "up" else "bottom"
        components = tuple(x for x in (
            fractal_ids.get((item.get("start"), start_kind)),
            fractal_ids.get((item.get("end"), end_kind)),
        ) if x)
        confirmed = _time_at(series, item.get("confirmed_at"))
        available = _time_at(series, item.get("available_at"))
        nodes.append(StructureNode(node_id, "stroke", item.get("direction"), series.level,
                                   item.get("start", -1), item.get("end", -1), confirmed,
                                   available, components, item.get("definition_mode", "swing_proxy"),
                                   not bool(item.get("finalized", False))))

    segment_ids: dict[Any, str] = {}
    for i, item in enumerate(report.get("segments", [])):
        raw_id = item.get("id", i)
        node_id = f"segment:{series.level}:{raw_id}"
        segment_ids[raw_id] = node_id
        components = tuple(stroke_ids[x] for x in item.get("components", []) if x in stroke_ids)
        confirmed = _time_at(series, item.get("confirmed_at"))
        nodes.append(StructureNode(node_id, "segment", item.get("direction"), series.level,
                                   item.get("start", -1), item.get("end", -1), confirmed,
                                   confirmed, components, item.get("definition_mode", "segment_proxy"),
                                   confirmed is None))

    for i, item in enumerate(report.get("centers", [])):
        raw_id = item.get("id", i)
        components = tuple(segment_ids[x] for x in item.get("components", []) if x in segment_ids)
        confirmed = _time_at(series, item.get("confirmed_at"))
        nodes.append(StructureNode(f"center:{series.level}:{raw_id}", "center", None,
                                   series.level, item.get("start", -1), item.get("end", -1),
                                   confirmed, confirmed, components,
                                   item.get("definition_mode", "segment_proxy"), confirmed is None))
    return nodes


def _candidate_time(series: LevelSeries, signal: Mapping[str, Any]) -> datetime | None:
    return _time_at(series, signal.get("available_at"))


def _side_matches(parent_side: str, signal: Mapping[str, Any]) -> bool:
    if signal.get("side") != parent_side:
        return False
    return str(signal.get("signal_class", "")).endswith(("buy_candidate", "sell_candidate"))


def _find_child_candidate(
    parent_side: str,
    parent_time: datetime,
    child: LevelSeries | None,
    as_of: datetime,
) -> Mapping[str, Any] | None:
    if child is None or as_of < parent_time:
        return None
    eligible = []
    for signal in child.report.get("signal_candidates", []):
        when = _candidate_time(child, signal)
        if when is None or when < parent_time or when > as_of:
            continue
        if _side_matches(parent_side, signal):
            eligible.append((when, signal))
    if not eligible:
        return None
    return max(eligible, key=lambda pair: pair[0])[1]


def _invalidated_at(series: LevelSeries, signal: Mapping[str, Any], as_of: datetime) -> bool:
    boundary = signal.get("invalidation")
    side = signal.get("side")
    available = signal.get("available_at")
    if not isinstance(boundary, (int, float)) or not isinstance(available, int):
        return False
    last = series.index_at_or_before(as_of)
    if last <= available:
        return False
    for bar in series.bars[available + 1:last + 1]:
        if side == "buy" and bar.low <= boundary:
            return True
        if side == "sell" and bar.high >= boundary:
            return True
    return False


def align_level_candidates(
    trade: LevelSeries,
    as_of: datetime,
    confirm: LevelSeries | None = None,
    trigger: LevelSeries | None = None,
) -> list[dict[str, Any]]:
    """Join same-side child candidates without inferring timeframe ratios.

    A match remains a candidate, not an executable/confirmed trade signal. All
    child evidence is filtered to its literal timestamp and to the requested
    as-of time.
    """
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    if trade.index_at_or_before(as_of) < 0:
        return []

    results: list[dict[str, Any]] = []
    for signal in trade.report.get("signal_candidates", []):
        parent_time = _candidate_time(trade, signal)
        if parent_time is None or parent_time > as_of:
            continue
        child_signal = _find_child_candidate(str(signal.get("side", "")), parent_time, confirm, as_of)
        trigger_signal = _find_child_candidate(str(signal.get("side", "")), parent_time, trigger, as_of)
        invalidated = _invalidated_at(trade, signal, as_of)
        if invalidated:
            status = "parent_invalidated"
        elif child_signal is None or trigger_signal is None:
            status = "candidate_trigger_missing"
        else:
            status = "multilevel_candidate_aligned"
        results.append({
            "signal_class": signal.get("signal_class"),
            "side": signal.get("side"),
            "trade_level": trade.level,
            "confirm_level": confirm.level if confirm else "missing",
            "trigger_level": trigger.level if trigger else "missing",
            "available_at": parent_time.isoformat(),
            "as_of": as_of.isoformat(),
            "status": status,
            "parent_invalidation": signal.get("invalidation"),
            "confirm_signal": dict(child_signal) if child_signal else None,
            "trigger_signal": dict(trigger_signal) if trigger_signal else None,
            "definition_mode": "timestamp_aligned_proxy",
            "structure_completeness": "partial_proxy",
            "execution_allowed": False,
        })
    return results

