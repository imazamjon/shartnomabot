import copy
import json
import unittest
from unittest.mock import Mock

from ihamkor import Ihamkor, parse_company
from orginfo import LookupUnavailable
from test_speed import response

SAMPLE = {
    'data': {'company': [{'name': '"MIZAN ACC" MCHJ', 'tin': '308859640',
                         'address': "Наманганская область, Янгикурганский район, Vodiy MFY, Amir Temur ko'chasi, 118-uy",
                         'state': 'active'}], 'product': []},
    'success': True, 'totalCompanies': 1, 'totalProducts': 0,
}


class IhamkorTests(unittest.TestCase):
    def test_supplied_schema(self):
        found = parse_company(SAMPLE, '308859640')
        self.assertEqual(found['name'], '"MIZAN ACC" MCHJ')
        self.assertEqual(found['stir'], '308859640')
        self.assertIn('118-uy', found['address'])
        self.assertEqual(found['director'], '')
        self.assertEqual(found['account'], '')

    def test_wrong_stir_rejected(self):
        with self.assertRaises(LookupUnavailable):
            parse_company(SAMPLE, '313405706')

    def test_empty_result(self):
        self.assertIsNone(parse_company({'success': True, 'data': {'company': []}, 'totalCompanies': 0}, '308859640'))

    def test_duplicate_stir_rejected(self):
        payload = copy.deepcopy(SAMPLE)
        payload['data']['company'] *= 2
        with self.assertRaises(LookupUnavailable):
            parse_company(payload, '308859640')

    def test_http_json_response(self):
        session = Mock()
        res = response(content=json.dumps(SAMPLE).encode())
        res.headers = {'Content-Type': 'application/json; charset=UTF-8'}
        session.get.return_value = res
        self.assertEqual(Ihamkor(session).lookup('308859640')['stir'], '308859640')
        self.assertEqual(session.get.call_args.kwargs['params'], {'q': '308859640'})

    def test_403_not_retried(self):
        session = Mock()
        session.get.return_value = response(status=403)
        with self.assertRaisesRegex(LookupUnavailable, '403'):
            Ihamkor(session).lookup('308859640')
        session.get.assert_called_once()

    def test_200_html_challenge_rejected(self):
        session = Mock()
        res = response(content=b'<html>Cloudflare</html>')
        res.headers = {'Content-Type': 'text/html'}
        session.get.return_value = res
        with self.assertRaises(LookupUnavailable):
            Ihamkor(session).lookup('308859640')
