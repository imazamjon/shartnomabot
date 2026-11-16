import json
import unittest
import tempfile
import time
from pathlib import Path
from unittest.mock import patch, Mock
import requests

from orginfo import Orginfo, LookupUnavailable, TemporaryUnavailable, parse_detail, fetch_html
import test_bot
from test_bot import COMPANY
from bot import NEW, CONFIRM

STIR = '310514454'
PATH = '/uz/organization/cf68f132a2f4/'


def detail(stir=STIR):
    # Same public JSON-LD structure observed on Orginfo, no network in unit tests.
    entity = {'@type': 'Organization', 'name': 'ORGINFO', 'alternateName': 'ORGINFO MCHJ',
              'taxID': stir, 'employee': {'@type': 'Person', 'name': 'Rahbar Ismi', 'jobTitle': 'Rahbar'},
              'address': {'addressLocality': 'Qo‘qon', 'streetAddress': 'Guzar 2'}}
    return ('<script type="application/ld+json">' + json.dumps([
        {'@type': 'WebPage', 'mainEntity': entity}]) + '</script><span>IFUT</span><span>63110 - Xizmatlar</span>')


class OrginfoTests(unittest.TestCase):
    def test_live_schema_and_cache(self):
        calls = []
        def fetch(path):
            calls.append(path)
            return '<a href="' + PATH + '">ORGINFO</a>' if 'search' in path else detail()
        client = Orginfo(fetch=fetch)
        company = client.lookup(STIR)
        self.assertEqual(company['stir'], STIR)
        self.assertEqual(company['director'], 'Rahbar Ismi')
        self.assertEqual(company['address'], 'Qo‘qon, Guzar 2')
        self.assertEqual(company['oked'], '63110')
        self.assertEqual(company['bank'], '')
        company['name'] = 'Changed'
        self.assertEqual(client.lookup(STIR)['name'], 'ORGINFO MCHJ')
        self.assertEqual(len(calls), 2)

    def test_wrong_stir_rejected(self):
        with self.assertRaises(LookupUnavailable):
            parse_detail(detail('123456789'), STIR, 'https://orginfo.uz' + PATH)

    def test_not_found_and_changed_page_distinguished(self):
        self.assertIsNone(Orginfo(fetch=lambda p: '<h6>Hech narsa topilmadi</h6>').lookup(STIR))
        for html in ['<html>Access denied</html>', '<script type="application/ld+json">broken</script>']:
            with self.assertRaises(LookupUnavailable):
                Orginfo(fetch=lambda p: html).lookup(STIR)

    def test_external_links_ignored(self):
        client = Orginfo(fetch=lambda p: '<a href="https://other.org/uz/organization/x/">Wrong</a>')
        with self.assertRaises(LookupUnavailable):
            client.lookup(STIR)

    def test_network_failure(self):
        with patch('orginfo._SESSION.get', side_effect=requests.Timeout), patch('orginfo.time.sleep'):
            with self.assertRaises(LookupUnavailable):
                fetch_html('/uz/search/organizations/?q=' + STIR)

    def test_retry_after_timeout(self):
        from test_speed import response
        ok = response(content=b'<html>OK</html>')
        with patch('orginfo._SESSION.get', side_effect=[requests.Timeout, ok]) as get, patch('orginfo.time.sleep'):
            self.assertEqual(fetch_html('/uz/search/organizations/?q=' + STIR), '<html>OK</html>')
            self.assertEqual(get.call_count, 2)

    def test_access_restrictions_not_retried(self):
        from test_speed import response
        for status in [403, 429]:
            with patch('orginfo._SESSION.get', return_value=response(status=status)) as get:
                with self.assertRaises(TemporaryUnavailable):
                    fetch_html('/uz/search/organizations/?q=' + STIR)
                self.assertEqual(get.call_count, 1)

    def test_redirect_cannot_leave_orginfo(self):
        from test_speed import response
        redirect = response(status=302)
        redirect.headers = {'Location': 'https://other.org/'}
        with patch('orginfo._SESSION.get', return_value=redirect) as get:
            with self.assertRaises(LookupUnavailable):
                fetch_html('/uz/search/organizations/?q=' + STIR)
            self.assertEqual(get.call_count, 1)

    def test_persistent_cache_survives_restart(self):
        def fetch(path):
            return '<a href="' + PATH + '">ORGINFO</a>' if 'search' in path else detail()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'cache.json'
            first = Orginfo(fetch=fetch, cache_path=path).lookup(STIR)
            self.assertEqual(first['cache_status'], 'live')
            fetch = Mock(side_effect=AssertionError('Network not needed'))
            second = Orginfo(fetch=fetch, cache_path=path).lookup(STIR)
            self.assertEqual(second['cache_status'], 'cached')
            self.assertEqual(second['retrieved_at'], first['retrieved_at'])
            fetch.assert_not_called()

    def test_stale_cache_fallback_is_marked(self):
        client = Orginfo(fetch=Mock(side_effect=TemporaryUnavailable('Timeout')), ttl=1)
        company = parse_detail(detail(), STIR, 'https://orginfo.uz' + PATH)
        company['retrieved_at'] = int(time.time()) - 120
        client.cache[STIR] = company
        found = client.lookup(STIR)
        self.assertEqual(found['cache_status'], 'stale')
        self.assertEqual(found['retrieved_at'], company['retrieved_at'])

    def test_parser_error_never_uses_stale_cache(self):
        client = Orginfo(fetch=lambda path: '<html>Changed layout</html>', ttl=1)
        client.cache[STIR] = {**parse_detail(detail(), STIR, 'https://orginfo.uz' + PATH), 'retrieved_at': int(time.time()) - 120}
        with self.assertRaises(LookupUnavailable):
            client.lookup(STIR)

    def test_bad_cache_and_too_old_cache_ignored(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'cache.json'
            path.write_text('broken json')
            self.assertEqual(Orginfo(cache_path=path).cache, {})
            company = parse_detail(detail(), STIR, 'https://orginfo.uz' + PATH)
            company['retrieved_at'] = int(time.time()) - 700000
            path.write_text(json.dumps({STIR: company}))
            self.assertEqual(Orginfo(cache_path=path).cache, {})

    def test_not_found_removes_stale_entry(self):
        client = Orginfo(fetch=lambda p: '<h6>Hech narsa topilmadi</h6>', ttl=1)
        client.cache[STIR] = {**parse_detail(detail(), STIR, 'https://orginfo.uz' + PATH), 'retrieved_at': int(time.time()) - 120}
        self.assertIsNone(client.lookup(STIR))
        self.assertNotIn(STIR, client.cache)


class IntegrationTests(unittest.TestCase):
    setUp = test_bot.Tests.setUp
    tearDown = test_bot.Tests.tearDown
    send = test_bot.Tests.send
    def test_new_stir_after_timeout_starts_new_lookup(self):
        self.bot.lookup = Mock(side_effect=LookupUnavailable('Timeout'))
        self.send(NEW)
        self.send('308859640')
        self.send('313405706')
        self.assertEqual(self.bot.lookup.call_args_list, [unittest.mock.call('308859640'), unittest.mock.call('313405706')])
        self.assertEqual(self.store.session(7)['stir'], '313405706')
        self.assertIn('STIR: 313405706', self.api.messages[-1])
        self.assertNotIn('STIR: 308859640', self.api.messages[-1])

    def test_new_stir_clears_previous_company_prefill(self):
        self.bot.lookup = Mock(side_effect=[{**COMPANY, 'source_url': 'https://orginfo.uz' + PATH}, None])
        self.send(NEW); self.send(COMPANY['stir'])
        self.assertIn('prefill', self.store.session(7))
        self.send('313405706')
        self.assertNotIn('prefill', self.store.session(7))
        self.assertNotIn('buyer', self.store.session(7))

    def test_same_stir_can_be_retried(self):
        self.bot.lookup = Mock(return_value=None)
        self.send(NEW); self.send('308859640'); self.send('308859640')
        self.assertEqual(self.bot.lookup.call_count, 2)

    def test_nine_digit_amount_is_not_a_stir_search(self):
        self.bot.lookup = Mock(return_value=None)
        for value in [NEW, COMPANY['stir'], test_bot.TEXT, CONFIRM, 'Tovar', '123456789']:
            self.send(value)
        self.assertEqual(self.bot.lookup.call_count, 1)
        self.assertEqual(self.store.session(7)['items'][0]['amount'], '123456789.00')

    def test_orginfo_bank_completion(self):
        found = {**COMPANY, 'bank': '', 'account': '', 'mfo': '',
                 'source_url': 'https://orginfo.uz' + PATH}
        self.bot.lookup = lambda stir: found
        self.send(NEW)
        self.send(COMPANY['stir'])
        self.assertIn('Orginfo’dan topildi', self.api.messages[-1])
        self.send('Bank: Bank\nHisob: 20208000000000000001\nMFO: 00450')
        s = self.store.session(7)
        self.assertEqual(s['step'], 'buyer_confirm')
        self.assertEqual(s['buyer']['name'], COMPANY['name'])
        self.send(CONFIRM)
        self.assertEqual(self.store.session(7)['step'], 'item')

    def test_orginfo_unavailable_falls_back(self):
        def unavailable(stir):
            raise LookupUnavailable('Orginfo javob bermadi')
        self.bot.lookup = unavailable
        self.send(NEW)
        self.send(COMPANY['stir'])
        self.assertIn('qo‘lda', self.api.messages[-1])
        self.assertEqual(self.store.session(7)['step'], 'buyer')

    def test_prefill_stir_cannot_be_overridden(self):
        self.bot.lookup = lambda stir: {**COMPANY, 'source_url': 'https://orginfo.uz' + PATH}
        self.send(NEW)
        self.send(COMPANY['stir'])
        self.send('STIR: 987654321')
        self.assertIn('farq', self.api.messages[-1])
        self.assertEqual(self.store.session(7)['step'], 'buyer_confirm')
