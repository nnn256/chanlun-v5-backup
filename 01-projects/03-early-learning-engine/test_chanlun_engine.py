import unittest
from unittest.mock import patch

from chanlun_algorithm import Bar
from chanlun_engine import analyze, centers_at, replay, segment_proxies, structural_signals, strokes_at


def move(i, start, end, direction, force=10):
    return {"id": i, "start": i * 10, "end": (i + 1) * 10,
            "start_price": start, "end_price": end,
            "low": min(start, end), "high": max(start, end),
            "direction": direction, "force": force, "confirmed_at": (i + 1) * 10 + 5}


class EngineTests(unittest.TestCase):
    def test_equal_high_or_low_is_not_a_strict_fractal(self):
        # A visual tie is not promoted to a strict turning point.
        values = [(8, 5), (12, 8), (12, 6), (8, 4)]
        bars = [Bar(i, h, l, l, h, i, i) for i, (h, l) in enumerate(values)]
        _, fractals, _ = strokes_at(bars, 4)
        self.assertEqual(fractals, [])

    def test_unsealed_tail_stroke_is_exposed_but_not_finalized(self):
        values = [(8, 5), (12, 8), (9, 6), (7, 3), (10, 5), (6, 2), (9, 4)]
        bars = [Bar(i, h, l, l, h, i, i) for i, (h, l) in enumerate(values)]
        _, _, strokes = strokes_at(bars, 1)
        self.assertTrue(strokes)
        self.assertFalse(strokes[-1]["finalized"])
        self.assertIsNone(strokes[-1]["confirmed_at"])

    def test_center_requires_positive_overlap(self):
        moves = [move(0, 1, 4, "up"), move(1, 4, 7, "down"),
                 move(2, 7, 10, "up")]
        self.assertEqual(centers_at(moves), [])

    def test_segment_proxy_does_not_promote_unconfirmed_tail(self):
        strokes = []
        for i, direction in enumerate(("up", "down", "up", "down")):
            strokes.append({"id": i, "direction": direction, "start": i * 3,
                            "end": i * 3 + 2, "start_price": 10 + i,
                            "end_price": 14 - i, "low": 8, "high": 16,
                            "confirmed_at": i * 3 + 4,
                            "available_at": i * 3 + 3,
                            "finalized": i < 3})
        segments = segment_proxies(strokes, [0.0] * 20)
        self.assertEqual(segments, [])

    def test_three_strokes_without_price_overlap_do_not_seed_segment(self):
        raw = [("up", 1, 4), ("down", 6, 5), ("up", 8, 10)]
        strokes = [{"id": i, "direction": direction, "start": i * 3,
                    "end": i * 3 + 2, "start_price": start, "end_price": end,
                    "low": min(start, end), "high": max(start, end),
                    "confirmed_at": i * 3 + 4, "available_at": i * 3 + 3,
                    "finalized": True}
                   for i, (direction, start, end) in enumerate(raw)]
        self.assertEqual(segment_proxies(strokes, [0.0] * 20), [])

    def test_segment_proxy_confirms_only_after_reversal_break(self):
        raw = [("up", 1, 10), ("down", 10, 5), ("up", 5, 12),
               ("down", 12, 4)]
        strokes = [{"id": i, "direction": d, "start": i * 3,
                    "end": i * 3 + 2, "start_price": a, "end_price": b,
                    "low": min(a, b), "high": max(a, b),
                    "confirmed_at": i * 3 + 4, "available_at": i * 3 + 3,
                    "finalized": True} for i, (d, a, b) in enumerate(raw)]
        segments = segment_proxies(strokes, [0.0] * 20)
        self.assertEqual(len(segments), 1)
        self.assertEqual(segments[0]["components"], [0, 1, 2])
        self.assertEqual(segments[0]["confirmed_at"], strokes[3]["confirmed_at"])

    def test_touching_ranges_do_not_create_positive_width_center(self):
        moves = [move(0, 1, 4, "up"), move(1, 4, 8, "down"),
                 move(2, 8, 9, "up")]
        for item, low, high in zip(moves, (1, 4, 5), (5, 8, 9)):
            item["low"], item["high"] = low, high
        self.assertEqual(centers_at(moves), [])

    def test_center_seed_is_not_shrunk_by_extension(self):
        moves = [move(0, 1, 8, "up"), move(1, 8, 3, "down"),
                 move(2, 3, 7, "up"), move(3, 7, 4, "down"), move(4, 4, 6, "up")]
        c = centers_at(moves)[0]
        self.assertEqual((c["zd"], c["zg"]), (3, 7))
        self.assertEqual(c["state"], "extension")

    def test_center_extension_keeps_core_and_expands_outer_range(self):
        moves = [move(0, 2, 10, "up"), move(1, 12, 4, "down"),
                 move(2, 3, 11, "up"), move(3, 13, 1, "down"),
                 move(4, 0, 15, "up")]
        for item, (low, high) in zip(moves, [(2, 10), (4, 12), (3, 11), (1, 13), (0, 15)]):
            item["low"], item["high"] = low, high
        c = centers_at(moves)[0]
        self.assertEqual((c["zd"], c["zg"]), (4, 10))
        self.assertEqual((c["dd"], c["gg"]), (0, 15))
        self.assertEqual(c["state"], "extension")

    def test_only_first_failed_return_qualifies_third_buy(self):
        moves = [move(0, 8, 2, "down"), move(1, 2, 7, "up"),
                 move(2, 7, 3, "down"), move(3, 3, 12, "up"), move(4, 12, 8, "down")]
        centers = centers_at(moves)
        signals = structural_signals(moves, centers)
        self.assertEqual(signals[0]["signal_class"], "third_buy_candidate")
        self.assertEqual(signals[0]["available_at"], moves[4]["confirmed_at"])
        self.assertEqual(signals[0]["invalidation"], 7)
        moves[4] = move(4, 12, 7, "down")  # boundary touch re-enters
        self.assertFalse(structural_signals(moves, centers_at(moves)))

    def test_sell_is_price_mirror(self):
        moves = [move(0, 8, 2, "down"), move(1, 2, 7, "up"),
                 move(2, 7, 3, "down"), move(3, 3, 12, "up"), move(4, 12, 8, "down")]
        mirror = [move(s["id"], -s["start_price"], -s["end_price"],
                       "down" if s["direction"] == "up" else "up") for s in moves]
        signals = structural_signals(mirror, centers_at(mirror))
        self.assertEqual(signals[0]["signal_class"], "third_sell_candidate")
        self.assertEqual(signals[0]["invalidation"], -7)

    def test_new_low_and_weak_force_not_enough_without_trend(self):
        moves = [move(0, 10, 2, "down", 20), move(1, 2, 7, "up"), move(2, 7, 1, "down", 5)]
        self.assertEqual(structural_signals(moves, centers_at(moves)), [])

    def test_fractal_right_bar_must_be_sealed(self):
        values = [(8, 5), (12, 8), (9, 6), (8, 4)]
        bars = [Bar(i, h, l, l, h, i, i) for i, (h, l) in enumerate(values)]
        self.assertEqual(strokes_at(bars[:3], 4)[1], [])
        f = strokes_at(bars, 4)[1]
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0]["confirmed_at"], 3)

    def test_adjacent_fractals_without_independent_candle_do_not_form_stroke(self):
        # The middle candle is the right side of the top and left side of the
        # bottom, so the two fractals have no independent candle between them.
        values = [(8, 5), (12, 9), (11, 7), (6, 2), (10, 5), (9, 3)]
        bars = [Bar(i, h, l, l, h, i, i) for i, (h, l) in enumerate(values)]
        _, fractals, strokes = strokes_at(bars, 4)
        self.assertEqual([f["kind"] for f in fractals], ["top"])
        self.assertEqual(strokes, [])

    def test_confirmed_fractal_time_is_not_backdated_by_future_extreme(self):
        values = [(8, 5), (12, 8), (9, 6), (8, 4), (14, 11), (20, 15)]
        bars = [Bar(i, h, l, l, h, i, i) for i, (h, l) in enumerate(values)]
        _, before_confirmation, _ = strokes_at(bars[:3], 1)
        _, at_confirmation, _ = strokes_at(bars[:4], 1)
        _, after_future_extremes, _ = strokes_at(bars, 1)
        self.assertFalse(any(f["kind"] == "top" and f["index"] == 1
                             for f in before_confirmation))
        confirmed = [f for f in at_confirmation if f["kind"] == "top" and f["index"] == 1]
        later = [f for f in after_future_extremes if f["kind"] == "top" and f["index"] == 1]
        self.assertEqual(len(confirmed), 1)
        self.assertEqual(len(later), 1)
        self.assertEqual(confirmed[0]["confirmed_at"], 3)
        self.assertEqual(later[0]["confirmed_at"], confirmed[0]["confirmed_at"])
        self.assertFalse(analyze(bars, level="synthetic")["execution_allowed"])

    def test_report_schema_exposes_causal_and_approximation_fields(self):
        bars = [Bar(i, float(i + 2), float(i), float(i + 1), float(i + 1), i, i)
                for i in range(12)]
        report = analyze(bars, level="30m")
        required = {"as_of", "trade_level", "definition_mode", "structure_completeness",
                    "approximation_loss", "merged", "fractals", "strokes", "segments",
                    "centers", "signal_candidates", "execution_allowed"}
        self.assertTrue(required.issubset(report))
        self.assertEqual(report["trade_level"], "30m")
        self.assertIsInstance(report["approximation_loss"], list)

    def test_first_then_second_requires_two_separated_centers(self):
        moves = [move(0, 30, 20, "down"), move(1, 20, 28, "up"),
                 move(2, 28, 21, "down"), move(3, 21, 26, "up"),
                 move(4, 26, 14, "down", 30), move(5, 14, 18, "up"),
                 move(6, 18, 12, "down"), move(7, 12, 17, "up"),
                 move(8, 17, 10, "down", 10), move(9, 10, 16, "up"),
                 move(10, 16, 11, "down")]
        centers = [{"id": 0, "dd": 20, "gg": 28, "failed_return": None},
                   {"id": 1, "dd": 12, "gg": 18, "seed_components": [5, 6, 7],
                    "components": [5, 6, 7], "failed_return": None}]
        signals = structural_signals(moves, centers)
        self.assertEqual([s["signal_class"] for s in signals],
                         ["first_buy_candidate", "second_buy_candidate"])
        self.assertEqual(signals[1]["first_anchor"], moves[8]["end"])
        moves[10] = move(10, 16, 9, "down")
        self.assertEqual(len(structural_signals(moves, centers)), 1)

    def test_first_seen_then_invalidation_is_append_only(self):
        bars = [Bar(i, 12, 10 if i < 7 else 8, 11, 11, i, i) for i in range(9)]
        signal = {"signal_class": "third_buy_candidate", "anchor": 3,
                  "available_at": 4, "invalidation": 9, "side": "buy"}
        with patch("chanlun_engine.analyze", return_value={"signal_candidates": [signal]}):
            events = replay(bars, level="test")
        self.assertEqual([x["event"] for x in events], ["first_seen", "invalidated"])
        self.assertEqual([x["available_at"] for x in events], [4, 7])
        self.assertEqual(events[0]["exec_not_before"], 5)


if __name__ == "__main__":
    unittest.main()
