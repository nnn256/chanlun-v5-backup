import math
import unittest

from workbench.hardware_indicators import compute
from chanmodel.gpu_macd import batch_macd,CudaUnavailable


class HardwareIndicatorTests(unittest.TestCase):
    def test_complete_cpu_result_and_auto_small_scope(self):
        value=compute({'prices':[[10,11,12],[15,14,16]],'backend':'auto'})
        self.assertEqual(value['shape'],(2,3,3));self.assertEqual(len(value['values']),18)
        self.assertEqual(value['backend'],'cpu');self.assertFalse(value['gpu_kernel_active'])
        self.assertFalse(value['execution_allowed'])

    def test_invalid_matrix_or_budget_is_rejected(self):
        for values in ([[1],[1,2]],[[None]],[[0]],[[]]):
            with self.assertRaises(ValueError):compute({'prices':values})
        with self.assertRaises(ValueError):compute({'prices':[[10]]*1025})

    def test_empty_explicit_gpu_does_not_claim_kernel_execution(self):
        value=compute({'prices':[],'backend':'gpu'})
        self.assertFalse(value['gpu_kernel_active'])

    def test_actual_gpu_matches_double_precision_cpu_on_same_full_batch(self):
        values=[[10+math.sin(i*.1+j) for i in range(64)] for j in range(40)]
        a=batch_macd(values,backend='cpu')
        try:b=batch_macd(values,backend='gpu')
        except CudaUnavailable as exc:self.skipTest(str(exc))
        self.assertEqual(a['values'],b['values']);self.assertTrue(b['gpu_kernel_active'])


if __name__=='__main__':unittest.main()
