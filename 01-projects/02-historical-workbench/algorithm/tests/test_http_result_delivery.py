"""Real HTTP responses retain complete JSON while negotiating compression."""
import gzip
from http.server import ThreadingHTTPServer
import json
import threading
import unittest
from unittest.mock import patch
import urllib.request

from workbench.server import Handler, accepts_gzip


LARGE = {'candles': [{'index': i, 'open': 10, 'high': 12, 'low': 8, 'close': 11} for i in range(2000)]}


class DeliveryHandler(Handler):
    def do_GET(self):
        if self.path == '/png':
            return self.send(b'\x89PNG\r\n' + b'x' * 80000, content_type='image/png')
        if self.path == '/small':
            return self.send({'small': True})
        return self.send(LARGE)


class HttpResultDeliveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.http = ThreadingHTTPServer(('127.0.0.1', 0), DeliveryHandler)
        cls.thread = threading.Thread(target=cls.http.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f'http://127.0.0.1:{cls.http.server_port}'
        cls.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.http.server_close()
        cls.thread.join()

    def response(self, path='/', encoding=None):
        headers = {} if encoding is None else {'Accept-Encoding': encoding}
        with self.opener.open(urllib.request.Request(self.url + path, headers=headers)) as response:
            return response.headers, response.read()

    def test_large_chart_json_is_lossless_gzip_with_correct_wire_length_and_security_headers(self):
        headers, raw = self.response(encoding='gzip, deflate')
        self.assertEqual(headers['Content-Encoding'], 'gzip')
        self.assertEqual(headers['Vary'], 'Accept-Encoding')
        self.assertEqual(int(headers['Content-Length']), len(raw))
        self.assertEqual(json.loads(gzip.decompress(raw)), LARGE)
        self.assertLess(len(raw), len(json.dumps(LARGE).encode()) // 5)
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertIn("connect-src 'self'", headers['Content-Security-Policy'])
        self.assertEqual(headers['X-Content-Type-Options'], 'nosniff')

    def test_plain_or_declined_gzip_remains_complete_json(self):
        for encoding in (None, 'gzip;q=0, *;q=1', 'br'):
            headers, raw = self.response(encoding=encoding)
            self.assertIsNone(headers['Content-Encoding'])
            self.assertEqual(int(headers['Content-Length']), len(raw))
            self.assertEqual(json.loads(raw), LARGE)

    def test_small_json_and_binary_png_are_not_reencoded(self):
        headers, raw = self.response('/small', 'gzip')
        self.assertIsNone(headers['Content-Encoding'])
        self.assertEqual(json.loads(raw), {'small': True})
        headers, raw = self.response('/png', 'gzip')
        self.assertIsNone(headers['Content-Encoding'])
        self.assertEqual(headers['Content-Type'], 'image/png')
        self.assertTrue(raw.startswith(b'\x89PNG\r\n'))
        self.assertEqual(int(headers['Content-Length']), len(raw))

    def test_quality_values_respect_explicit_decline_and_wildcard(self):
        for value in ('gzip', 'GZIP;q=0.5', '*;q=1'):
            self.assertTrue(accepts_gzip(value), value)
        for value in ('gzip;q=0,*;q=1', 'gzip;q=bad', 'gzip;q=2', 'br', ''):
            self.assertFalse(accepts_gzip(value), value)

    def test_client_abort_during_headers_or_body_does_not_attempt_a_second_response(self):
        class Aborted:
            headers = {}
            calls = 0
            def send_response(self, status):
                self.calls += 1
            def send_header(self, name, value):
                pass
            def end_headers(self):
                raise ConnectionAbortedError(10053, 'client navigated away')
        aborted = Aborted()
        Handler.send(aborted, {'value': True})
        self.assertEqual(aborted.calls, 1)
        aborted.end_headers = lambda: None
        class BrokenWriter:
            def write(self, raw):
                raise ConnectionResetError('closed')
        aborted.wfile = BrokenWriter()
        Handler.send(aborted, {'value': True})
        self.assertEqual(aborted.calls, 2)

    def test_live_stock_entrypoints_request_the_interactive_startup_budget(self):
        service = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=service.serve_forever, daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{service.server_port}'
        try:
            with patch('workbench.services.ensure_tdx') as ensure, \
                 patch('workbench.live.live_stock', return_value={'available': True}):
                for path in ('/api/live-stock/sh600000', '/api/stock/sh600000?live=1'):
                    with self.opener.open(base + path) as response:
                        self.assertTrue(json.load(response)['available'])
                self.assertEqual(ensure.call_count, 2)
                self.assertTrue(all(call.kwargs == {'timeout': 8} for call in ensure.call_args_list))
        finally:
            service.shutdown()
            service.server_close()
            thread.join()


if __name__ == '__main__':
    unittest.main()
