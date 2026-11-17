import unittest

from cuda_audit import CudaAuditor, cpu_oracle, prepare_rows


class CpuContractTests(unittest.TestCase):
    def test_errors_are_distinguished(self):
        rows = [(10, 11, 9, 10.5, 0), (0, 11, 0, 10, 1), (12, 11, 9, 10, 1),
                (10, 11, 9, 10, -1), (10, 11, float('nan'), 10, 1),
                (10, 11, 9, 10, float('inf'))]
        result = cpu_oracle(rows)
        self.assertEqual(result['flags'], [0, 1, 2, 4, 11, 8])

    def test_ranges_and_empty_sessions(self):
        rows = [(10, 10, 10, 10, 1)]
        result = cpu_oracle(rows, [(0, 0), (0, 1)])
        self.assertEqual(result['sessions'][0]['low'], None)
        self.assertEqual(result['sessions'][1]['low'], 10)
        with self.assertRaises(ValueError): prepare_rows(rows, [(0, 2)])
        with self.assertRaises(ValueError): prepare_rows([(1, 2)])


class ActualGpuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # A missing CUDA driver or a failing kernel is a real test failure.
        cls.auditor = CudaAuditor()

    @classmethod
    def tearDownClass(cls):
        cls.auditor.close()

    def test_positive_negative_nan_infinity_and_boundaries(self):
        nan = float('nan')
        rows = [(10, 11, 9, 10.5, 0), (0, 11, 0, 10, 1), (12, 11, 9, 10, 1),
                (10, 11, 9, 10, -1), (10, 11, nan, 10, 1),
                (10, 11, 9, 10, float('inf')), (9, 11, 9, 11, 1),
                (10, 10, 10, 10, -0.0), (nan, 11, 9, 10, 1),
                (10, float('inf'), 9, 10, 1), (10, 11, 9, 10, nan)]
        result = self.auditor.audit(rows, [(0, 4), (4, 7), (7, 11), (3, 3)])
        self.assertTrue(result['verified_cpu'])
        self.assertEqual(result['flags'], cpu_oracle(rows)['flags'])
        self.assertGreaterEqual(tuple(map(int, result['device']['compute_capability'].split('.'))), (8, 6))
        self.assertGreaterEqual(result['timings_ms']['gpu_kernels'], 0)
        print('GPU fixture timing:', result['device'], result['timings_ms'])

    def test_empty_inputs(self):
        result = self.auditor.audit([], [])
        self.assertTrue(result['verified_cpu'])
        self.assertEqual(result['flags'], [])
        self.assertEqual(result['sessions'], [])

    def test_more_than_one_block_and_240_bar_sessions(self):
        rows = [(10 + (i % 31) / 100, 11 + (i % 11) / 100,
                 9 - (i % 7) / 100, 10.1, float(i)) for i in range(1440)]
        rows[129] = (20, 11, 9, 10, 10)
        result = self.auditor.audit(rows, [(i, i+240) for i in range(0, 1440, 240)])
        self.assertTrue(result['verified_cpu'])
        self.assertEqual(result['invalid_rows'], 1)
        self.assertEqual(result['flags'][129], 2)
        self.assertEqual([s['count'] for s in result['sessions']], [240] * 6)


if __name__ == '__main__':
    unittest.main()
