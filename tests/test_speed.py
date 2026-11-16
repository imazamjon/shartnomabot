import io
import unittest
from unittest.mock import Mock, patch

import requests
from bot import Telegram
from ocr import read_document, ReadError, MAX_BYTES, _TEXT_CACHE
from test_files import ROOT, FIXTURES


def response(json=None, content=b'', status=200):
    result = Mock()
    result.__enter__ = Mock(return_value=result)
    result.__exit__ = Mock(return_value=False)
    result.status_code = status
    result.json.return_value = json
    result.iter_content.return_value = [content]
    return result


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.api = Telegram('123:SECRET')
        self.session = Mock()
        self.api.local.session = self.session

    def test_connection_reused_and_timeouts_bounded(self):
        self.session.post.return_value = response({'ok': True, 'result': {}})
        self.api.request('getMe')
        self.api.request('getFile', {'file_id': 'x'})
        self.assertEqual(self.session.post.call_count, 2)
        self.assertEqual(self.session.post.call_args.kwargs['timeout'], (4, 12))
        self.assertFalse(self.session.post.call_args.kwargs['allow_redirects'])

    def test_poll_has_separate_long_timeout(self):
        self.session.post.return_value = response({'ok': True, 'result': []})
        self.api.request('getUpdates', {'timeout': 30})
        self.assertEqual(self.session.post.call_args.kwargs['timeout'], (4, 35))

    def test_bad_api_payload_is_sanitized(self):
        for payload in [None, [], {'ok': True}, {'ok': False}]:
            self.session.post.return_value = response(payload)
            with self.assertRaises(RuntimeError):
                self.api.request('getMe')

    def test_token_not_in_network_errors(self):
        self.session.post.side_effect = requests.ReadTimeout('https://api.telegram.org/bot123:SECRET/getFile')
        with self.assertRaises(RuntimeError) as error:
            self.api.request('getFile')
        self.assertNotIn('SECRET', str(error.exception))
        self.assertEqual(self.session.post.call_count, 1)  # no duplicate POST retries

    def test_download_cached_without_network(self):
        self.session.post.return_value = response({'ok': True, 'result': {'file_path': 'photos/a.jpg', 'file_size': 4}})
        self.session.get.return_value = response(content=b'data')
        self.assertEqual(self.api.download('file'), b'data')
        self.assertEqual(self.api.download('file'), b'data')
        self.assertEqual(self.session.post.call_count, 1)
        self.assertEqual(self.session.get.call_count, 1)

    def test_expired_download_retrieved_again(self):
        self.session.post.return_value = response({'ok': True, 'result': {'file_path': 'photos/a.jpg'}})
        self.session.get.return_value = response(content=b'data')
        self.api.download('file')
        self.api.file_cache['file'] = (-10000, b'data')
        self.api.download('file')
        self.assertEqual(self.session.get.call_count, 2)
        self.assertEqual(self.api.cache_size, 4)

    def test_download_stream_limit(self):
        self.session.post.return_value = response({'ok': True, 'result': {'file_path': 'photos/a.jpg'}})
        self.session.get.return_value = response(content=b'x' * (MAX_BYTES + 1))
        with self.assertRaises(ReadError):
            self.api.download('file')
        self.assertFalse(self.api.file_cache)

    def test_file_url_cannot_leave_telegram(self):
        for path in ['https://evil.com/x', '../secret', '/absolute', 'photos/../x']:
            self.session.post.return_value = response({'ok': True, 'result': {'file_path': path}})
            with self.assertRaises(ReadError):
                self.api.download('file')
        self.session.get.assert_not_called()

    def test_keyboard_removal_and_long_reply(self):
        self.session.post.return_value = response({'ok': True, 'result': {}})
        self.api.send(7, 'x' * 5000, [])
        self.assertEqual(self.session.post.call_count, 3)
        import json
        data = json.loads(self.session.post.call_args.kwargs['data'])
        self.assertEqual(data['reply_markup'], {'remove_keyboard': True})


class OCRSpeedTests(unittest.TestCase):
    def setUp(self):
        _TEXT_CACHE.clear()

    def test_repeat_image_skips_ocr(self):
        data = (FIXTURES / 'requisites.png').read_bytes()
        with patch('ocr._read_document', return_value='STIR: 123456789') as reader:
            first = read_document(data, ROOT)
            self.assertEqual(read_document(data, ROOT), first)
            reader.assert_called_once()

    def test_text_pdf_does_not_run_ocr_when_some_fields_missing(self):
        with patch('ocr.run', side_effect=['Pages: 1', 'Nomi: SINOV KORXONASI\nSTIR: 123456789']) as run:
            result = read_document(b'%PDF-test-no-image', ROOT)
            self.assertIn('123456789', result)
            self.assertEqual(run.call_count, 2)

    def test_large_and_broken_pdf_rejected(self):
        with patch('ocr.run', return_value='Pages: 6'):
            with self.assertRaises(ReadError):
                read_document(b'%PDF-six-pages', ROOT)
        with patch('ocr.run', side_effect=ReadError('Buzilgan PDF')):
            with self.assertRaises(ReadError):
                read_document(b'%PDF-broken', ROOT)

    def test_cache_bound(self):
        with patch('ocr._read_document', return_value='text'):
            for i in range(20):
                read_document(b'image-' + str(i).encode(), ROOT)
        self.assertEqual(len(_TEXT_CACHE), 16)
