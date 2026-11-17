import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.test_recursive_v2 import daily_series
from chanmodel.reference_engine import ReferenceSession
from workbench import incremental, live


class ResidentLiveReuseTests(unittest.TestCase):
    def test_memory_hit_requests_only_the_bounded_tail(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bars = daily_series(96).bars
            session = ReferenceSession('day', observe=True)
            for bar in bars:
                session.append(bar)
            cached = incremental.LiveSession(session, len(bars), last_full_audit=time.time())
            with patch.object(incremental, 'ROOT', root / 'sessions'), \
                 patch.object(incremental, 'MEMORY', incremental.OrderedDict()), \
                 patch.object(live, 'STATE', root / 'state'):
                incremental.MEMORY[('sz000001', 'day')] = cached
                rows = [{'open': b.open, 'high': b.high, 'low': b.low, 'close': b.close,
                         'closed_at': b.closed_at, 'volume': b.volume, 'is_closed': True}
                        for b in bars[-live.TAIL_LIMIT:]]
                receipt = {'requested_at': bars[-1].closed_at, 'received_at': bars[-1].closed_at,
                           'observed_at': bars[-1].closed_at, 'response_sha256': 'tail'}
                with patch.object(live, 'acquire', return_value=(bars[-live.TAIL_LIMIT:], rows, receipt)) as acquire:
                    _, _, _, meta = live._ingest('sz000001', 'day')
                acquire.assert_called_once_with('sz000001', 'day', full=False)
                self.assertTrue(meta['session_reused'])
                self.assertFalse(meta['restored'])
                self.assertFalse(meta['rebuilt'])
                self.assertEqual(meta['appended'], 0)

    def test_no_change_deep_audit_time_is_persisted_without_new_bar(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bars = daily_series(96).bars
            session = ReferenceSession('day', observe=True)
            for bar in bars:
                session.append(bar)
            cached = incremental.LiveSession(session, len(bars), last_full_audit=0.0)
            def rows(values):
                return [{'open': b.open, 'high': b.high, 'low': b.low, 'close': b.close,
                         'closed_at': b.closed_at, 'volume': b.volume, 'is_closed': True}
                        for b in values]
            def receipt(tag):
                stamp = bars[-1].closed_at
                return {'requested_at': stamp, 'received_at': stamp, 'observed_at': stamp,
                        'response_sha256': tag, 'period': 'day'}
            with patch.object(incremental, 'ROOT', root / 'sessions'), \
                 patch.object(incremental, 'STATE', root / 'state'), \
                 patch.object(incremental, 'MEMORY', incremental.OrderedDict()), \
                 patch.object(live, 'STATE', root / 'state'):
                incremental.MEMORY[('sz000001', 'day')] = cached
                with patch.object(live, 'acquire', side_effect=[
                    (bars[-live.TAIL_LIMIT:], rows(bars[-live.TAIL_LIMIT:]), receipt('tail')),
                    (bars, rows(bars), receipt('full'))]) as acquire:
                    live._ingest('sz000001', 'day')
                self.assertEqual([call.kwargs['full'] for call in acquire.call_args_list], [False, True])
                saved_at = cached.last_full_audit
                self.assertGreater(saved_at, 0)
                incremental.clear_memory()
                restored, from_checkpoint = incremental.get('sz000001', 'day')
                self.assertTrue(from_checkpoint)
                self.assertEqual(restored.last_full_audit, saved_at)

    def test_one_new_closed_bar_is_journaled_without_rewriting_engine_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bars = daily_series(97).bars
            session = ReferenceSession('day', observe=True)
            for bar in bars[:96]:
                session.append(bar)
            cached = incremental.LiveSession(session, saved_count=96, last_full_audit=time.time())
            cached.last_load_source = 'memory'
            def rows(values):
                return [{'open': b.open, 'high': b.high, 'low': b.low, 'close': b.close,
                         'closed_at': b.closed_at, 'volume': b.volume, 'is_closed': True}
                        for b in values]
            receipt = {'requested_at': bars[-1].closed_at, 'received_at': bars[-1].closed_at,
                       'observed_at': bars[-1].closed_at, 'response_sha256': 'one-new-bar'}
            with patch.object(incremental, 'ROOT', root / 'sessions'), \
                 patch.object(incremental, 'STATE', root / 'state'), \
                 patch.object(incremental, 'MEMORY', incremental.OrderedDict()), \
                 patch.object(live, 'STATE', root / 'state'):
                incremental.MEMORY[('sz000001', 'day')] = cached
                incremental.save('sz000001', 'day', cached)
                old_checkpoint = incremental._checkpoint_path('sz000001', 'day').read_bytes()
                tail = bars[-live.TAIL_LIMIT:]
                with patch.object(live, 'acquire', return_value=(tail, rows(tail), receipt)) as acquire:
                    _, _, _, meta = live._ingest('sz000001', 'day')
                acquire.assert_called_once_with('sz000001', 'day', full=False)
                self.assertEqual(meta['appended'], 1)
                self.assertEqual(meta['checkpoint_journal_bars'], 1)
                self.assertEqual(incremental._checkpoint_path('sz000001', 'day').read_bytes(), old_checkpoint)
                wal = incremental._journal_path('sz000001', 'day')
                self.assertEqual(len(wal.read_bytes().splitlines()), 1)


if __name__ == '__main__':
    unittest.main()
