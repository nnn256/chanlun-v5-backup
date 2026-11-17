import unittest
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from chanlun_algorithm import Bar
from chanlun_multilevel import (LevelSeries, align_level_candidates,
                                load_level_csv, parse_timestamp, structure_nodes_from_report)


def timestamps(count, step_minutes=1):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [start + timedelta(minutes=step_minutes * i) for i in range(count)]


def bars(count, lows=None):
    lows = lows or [10.0] * count
    return [Bar(i, lows[i] + 2, lows[i], lows[i] + 0.5, lows[i] + 1,
                i, i) for i in range(count)]


def series(level, ts, report, lows=None):
    return LevelSeries(level, bars(len(ts), lows), ts, report)


class MultilevelTests(unittest.TestCase):
    def test_bundle_cli_writes_a_timestamped_proxy_report(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            csv_paths = {}
            for level in ("30m", "5m", "1m"):
                path = root / f"{level}.csv"
                lines = ["timestamp,open,high,low,close"]
                for i in range(8):
                    lines.append(f"2026-01-01T00:{i:02d}:00+00:00,10,12,9,11")
                path.write_text("\n".join(lines) + "\n", encoding="utf-8")
                csv_paths[level] = path
            output = root / "bundle.json"
            command = [sys.executable, str(Path(__file__).with_name("chanlun_bundle.py")),
                       "--trade", f"30m={csv_paths['30m']}",
                       "--confirm", f"5m={csv_paths['5m']}",
                       "--trigger", f"1m={csv_paths['1m']}",
                       "--as-of", "2026-01-01T00:07:00+00:00", "-o", str(output)]
            run = subprocess.run(command, capture_output=True, text=True, check=False)
            self.assertEqual(run.returncode, 0, run.stderr)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(set(report["inputs"]), {"trade", "confirm", "trigger"})
            self.assertEqual(report["definition_mode"], "timestamp_aligned_proxy")
            self.assertFalse(report["execution_allowed"])

    def test_load_timestamped_ohlc_csv(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "five_min.csv"
            rows = ["timestamp,open,high,low,close"]
            for i in range(6):
                rows.append(f"2026-01-01T00:0{i}:00+00:00,10,12,9,11")
            path.write_text("\n".join(rows) + "\n", encoding="utf-8")
            item = load_level_csv(path, "5m")
            self.assertEqual(item.level, "5m")
            self.assertEqual(len(item.bars), 6)
            self.assertEqual(item.timestamps[0], parse_timestamp("2026-01-01T00:00:00Z"))

    def test_naive_timestamp_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_timestamp("2026-01-01 09:30:00")

    def test_level_series_builds_proxy_report_from_bars(self):
        ts = timestamps(8)
        item = LevelSeries.from_bars("5m", bars(8), ts, separation=4)
        self.assertEqual(item.level, "5m")
        self.assertEqual(item.report["trade_level"], "5m")
        self.assertEqual(item.report["definition_mode"], "structure_proxy")

    def test_join_uses_timestamped_child_candidates(self):
        ts = timestamps(5)
        parent = series("30m", ts, {"signal_candidates": [{
            "signal_class": "first_buy_candidate", "side": "buy",
            "available_at": 1, "anchor": 0, "invalidation": 5,
        }]})
        confirm = series("5m", ts, {"signal_candidates": [{
            "signal_class": "first_buy_candidate", "side": "buy", "available_at": 2,
        }]})
        trigger = series("1m", ts, {"signal_candidates": [{
            "signal_class": "third_buy_candidate", "side": "buy", "available_at": 3,
        }]})

        aligned = align_level_candidates(parent, ts[4], confirm, trigger)
        self.assertEqual(len(aligned), 1)
        self.assertEqual(aligned[0]["status"], "multilevel_candidate_aligned")
        self.assertEqual(aligned[0]["trade_level"], "30m")
        self.assertFalse(aligned[0]["execution_allowed"])

    def test_future_child_evidence_is_not_used(self):
        parent_ts = timestamps(5)
        child_ts = timestamps(7, step_minutes=1)
        parent = series("30m", parent_ts, {"signal_candidates": [{
            "signal_class": "first_buy_candidate", "side": "buy",
            "available_at": 1, "anchor": 0, "invalidation": 5,
        }]})
        confirm = series("5m", child_ts, {"signal_candidates": [{
            "signal_class": "first_buy_candidate", "side": "buy", "available_at": 5,
        }]})
        result = align_level_candidates(parent, parent_ts[4], confirm, confirm)
        self.assertEqual(result[0]["status"], "candidate_trigger_missing")
        self.assertIsNone(result[0]["confirm_signal"])

    def test_parent_invalidation_dominates_child_matches(self):
        ts = timestamps(5)
        parent = series("30m", ts, {"signal_candidates": [{
            "signal_class": "first_buy_candidate", "side": "buy",
            "available_at": 1, "anchor": 0, "invalidation": 8,
        }]}, lows=[10, 10, 10, 10, 7])
        child = series("5m", ts, {"signal_candidates": [{
            "signal_class": "first_buy_candidate", "side": "buy", "available_at": 2,
        }]})
        result = align_level_candidates(parent, ts[4], child, child)
        self.assertEqual(result[0]["status"], "parent_invalidated")

    def test_wrong_side_child_does_not_confirm_parent(self):
        ts = timestamps(5)
        parent = series("30m", ts, {"signal_candidates": [{
            "signal_class": "first_buy_candidate", "side": "buy",
            "available_at": 1, "anchor": 0, "invalidation": 5,
        }]})
        child = series("5m", ts, {"signal_candidates": [{
            "signal_class": "first_sell_candidate", "side": "sell", "available_at": 2,
        }]})
        result = align_level_candidates(parent, ts[4], child, child)
        self.assertEqual(result[0]["status"], "candidate_trigger_missing")

    def test_structure_nodes_keep_component_links_and_confirmation_times(self):
        ts = timestamps(8)
        report = {
            "fractals": [
                {"kind": "bottom", "source_index": 0, "index": 0, "confirmed_at": 2},
                {"kind": "top", "source_index": 4, "index": 4, "confirmed_at": 6},
            ],
            "strokes": [{"id": 0, "direction": "up", "start": 0, "end": 4,
                         "available_at": 6, "confirmed_at": 7, "finalized": True}],
            "segments": [{"id": 0, "direction": "up", "start": 0, "end": 4,
                           "components": [0], "confirmed_at": 7}],
            "centers": [{"id": 0, "start": 0, "end": 4, "components": [0],
                          "confirmed_at": 7}],
        }
        nodes = structure_nodes_from_report(series("5m", ts, report))
        stroke = next(node for node in nodes if node.kind == "stroke")
        segment = next(node for node in nodes if node.kind == "segment")
        center = next(node for node in nodes if node.kind == "center")
        self.assertEqual(len(stroke.components), 2)
        self.assertEqual(segment.components, (stroke.id,))
        self.assertEqual(center.components, (segment.id,))
        self.assertEqual(center.confirmed_at, ts[7])

    def test_time_series_requires_strictly_increasing_aware_timestamps(self):
        ts = timestamps(3)
        with self.assertRaises(ValueError):
            LevelSeries("5m", bars(3), [ts[0], ts[0], ts[2]], {})
        with self.assertRaises(ValueError):
            LevelSeries("5m", bars(1), [datetime(2026, 1, 1)], {})


if __name__ == "__main__":
    unittest.main()
