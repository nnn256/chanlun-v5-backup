import unittest

from chanlun_algorithm import Bar, Stroke, Fractal, analyze, build_center_proxies, find_fractals, merge_inclusions


class ChanlunStructureTests(unittest.TestCase):
    def test_inclusion_merge_preserves_source_range(self):
        bars = [Bar(0, 10, 5, 6, 8, 0, 0), Bar(1, 9, 6, 8, 7, 1, 1),
                Bar(2, 12, 8, 9, 11, 2, 2)]
        merged = merge_inclusions(bars)
        self.assertEqual(len(merged), 2)
        self.assertEqual((merged[0].high, merged[0].low), (9, 5))
        self.assertEqual((merged[1].source_start, merged[1].source_end), (2, 2))

    def test_fractal_is_only_confirmed_after_right_bar(self):
        bars = [Bar(0, 8, 5, 6, 7, 0, 0), Bar(1, 12, 8, 9, 11, 1, 1),
                Bar(2, 9, 6, 7, 8, 2, 2)]
        top = find_fractals(bars)
        self.assertEqual([(x.kind, x.index, x.confirmed_at) for x in top], [("top", 1, 2)])

    def test_three_overlapping_strokes_form_proxy_center(self):
        def stroke(i, lo, hi, direction):
            s = Fractal("bottom", i, lo, i, i)
            e = Fractal("top", i + 1, hi, i + 1, i + 1)
            return Stroke(direction, s, e, hi, lo, i + 1)

        centers = build_center_proxies([stroke(0, 1, 5, "up"), stroke(2, 3, 7, "down"),
                                        stroke(4, 2, 6, "up")])
        self.assertEqual(len(centers), 1)
        self.assertEqual((centers[0]["zd"], centers[0]["zg"]), (3, 5))
        self.assertEqual(centers[0]["definition_mode"], "segment_proxy")

    def test_report_never_claims_execution(self):
        bars = [Bar(i, float(i + 2), float(i), float(i + 1), float(i + 1), i, i) for i in range(8)]
        report = analyze(bars)
        self.assertEqual(report["action"], "observe")
        self.assertFalse(report["execution_allowed"])
        self.assertEqual(report["definition_mode"], "structure_proxy")


if __name__ == "__main__":
    unittest.main()
