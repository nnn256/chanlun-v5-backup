"""Run native source-rule tests and delivery integration tests in this bundle."""
import sys
import unittest
from pathlib import Path

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
sys.path.insert(0,str(HERE/'engine'))
suite=unittest.TestSuite()
for module in ['tests.test_engine','tests.test_recursive_v2','tests.test_complete_study',
               'tests.test_complete_upgrade','test_full_data','test_multiframe_delivery',
               'test_period_catalog']:
    suite.addTests(unittest.defaultTestLoader.loadTestsFromName(module))
result=unittest.TextTestRunner(verbosity=1).run(suite)
raise SystemExit(0 if result.wasSuccessful() else 1)
