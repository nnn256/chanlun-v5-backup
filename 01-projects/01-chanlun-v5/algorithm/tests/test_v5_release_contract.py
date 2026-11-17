import os
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from functools import partial
from unittest.mock import patch

from workbench import backtests, store
from workbench.v5_engine import MAX_RANK
from launch_v5 import matches_health


class V5ReleaseContractTests(unittest.TestCase):
    def test_v5_backtest_uses_sibling_market_data_by_default(self):
        with patch.object(backtests, 'ROOT', Path('D:/chanlun/algorithm')):
            with patch.dict(os.environ, {}, clear=True):
                self.assertEqual(
                    backtests.default_cache_dir(),
                    Path('D:/chanlun/data/market_data').resolve(),
                )

    def test_market_data_override_is_respected(self):
        with patch.dict(os.environ, {'CHANLUN_MARKET_DATA_DIR': 'D:/cache/custom'}):
            self.assertEqual(
                backtests.default_cache_dir(),
                Path('D:/cache/custom').resolve(),
            )

    def test_launch_uses_v5_data_cache_when_cache_is_omitted(self):
        with TemporaryDirectory() as tmp:
            state = Path(tmp)
            database = state / 'test.sqlite3'
            store.initialize(database)
            with store.connect(database) as db:
                db.execute(
                    'INSERT INTO universe(symbol,code,name,exchange,active) VALUES(?,?,?,?,1)',
                    ('sh600000', '600000', '浦发银行', 'sh'),
                )
            project=state/'algorithm'
            cache=state/'data'/'market_data'
            (cache/'tdx'/'day'/'ohlcv').mkdir(parents=True)
            with patch.object(backtests, 'connect', partial(store.connect, database)), \
                 patch.object(backtests, 'STATE', state), \
                 patch.object(backtests, 'ROOT', project), \
                 patch.dict(os.environ, {}, clear=True), \
                 patch.object(backtests.subprocess, 'Popen') as spawn:
                spawn.return_value.pid = 12345
                backtests.launch({'scope': 'selected', 'symbols': ['sh600000'], 'workers': 1})
            request = next((state / 'backtests').glob('*/request.json'))
            self.assertEqual(
                json.loads(request.read_text(encoding='utf-8'))['cache'],
                str(cache.resolve()),
            )

    def test_launch_normalizes_worker_text_from_a_stale_browser_tab(self):
        with TemporaryDirectory() as tmp:
            state=Path(tmp);database=state/'test.sqlite3';store.initialize(database)
            cache=state/'market_data';(cache/'tdx'/'day'/'ohlcv').mkdir(parents=True)
            with store.connect(database) as db:
                db.execute('INSERT INTO universe(symbol,code,name,exchange,active) VALUES(?,?,?,?,1)',
                           ('sh600000','600000','浦发银行','sh'))
            with patch.object(backtests,'connect',partial(store.connect,database)), \
                 patch.object(backtests,'STATE',state), \
                 patch.object(backtests,'ROOT',state/'algorithm'), \
                 patch.object(backtests.subprocess,'Popen') as spawn:
                spawn.return_value.pid=23456
                result=backtests.launch({'scope':'selected','symbols':['sh600000'],
                                         'workers':'16','cache':str(cache)})
            self.assertEqual(result['workers'],16)
            request=next((state/'backtests').glob('*/request.json'))
            self.assertEqual(json.loads(request.read_text(encoding='utf-8'))['workers'],16)
            spawn.assert_called_once()

    def test_recursive_rank_cap_matches_release_profile(self):
        self.assertEqual(MAX_RANK, 8)

    def test_launcher_does_not_reuse_legacy_engine_or_another_database(self):
        expected=Path('D:/workbench-v5/workbench.sqlite3')
        health={'service':'chanlun-workbench-v1','release':'V5','version':'5.0.0',
                'workbench_profile':'course_feature_sequence_recursive_v2','database':str(expected)}
        self.assertTrue(matches_health(health,expected))
        self.assertFalse(matches_health({**health,'release':'V4'},expected))
        self.assertFalse(matches_health({**health,'workbench_profile':'pinned_reference_engine'},expected))
        self.assertFalse(matches_health({**health,'database':'D:/another/workbench.sqlite3'},expected))


if __name__ == '__main__':
    unittest.main()
