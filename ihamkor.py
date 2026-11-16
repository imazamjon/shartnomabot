"""Adapter for the public quick-search response supplied by the user.

No browser telemetry tokens, session cookies, or Cloudflare bypasses are used.
The provider must permit the server's access before production activation.
"""
import re
from urllib.parse import urlencode

import requests
from orginfo import LookupUnavailable

BASE = 'https://ihamkor.uz/api/search/quick'


def parse_company(payload, stir):
    if not isinstance(payload, dict) or payload.get('success') is not True:
        raise LookupUnavailable('iHamkor qidiruv javobini tasdiqlamadi.')
    data = payload.get('data')
    if not isinstance(data, dict) or not isinstance(data.get('company'), list):
        raise LookupUnavailable('iHamkor javob formati o‘zgargan.')
    companies = data['company']
    matches = [c for c in companies if isinstance(c, dict) and str(c.get('tin', '')) == stir]
    if not matches:
        if companies:
            raise LookupUnavailable('iHamkor natijasidagi STIR so‘ralgan STIRga mos kelmadi.')
        if payload.get('totalCompanies') != 0:
            raise LookupUnavailable('iHamkor to‘liq qidiruv natijasini qaytarmadi.')
        return None
    if len(matches) != 1:
        raise LookupUnavailable('iHamkor yagona korxonani aniqlamadi.')
    company = matches[0]
    name = company.get('name') or company.get('company_name_company')
    address = company.get('address') or ''
    if not isinstance(name, str) or not name.strip() or not isinstance(address, str):
        raise LookupUnavailable('iHamkor korxona ma’lumotlari to‘liq emas.')
    return {
        'name': name.strip(), 'stir': stir, 'address': address.strip(),
        # These fields are absent from quick-search; do not invent them.
        'director': '', 'bank': '', 'account': '', 'mfo': '',
        'status': company.get('state', ''),
        'source_url': BASE + '?' + urlencode({'q': stir}),
    }


class Ihamkor:
    def __init__(self, session=None):
        self.session = session or requests.Session()

    def lookup(self, stir):
        if not re.fullmatch(r'[0-9]{9}', stir):
            raise ValueError('STIR 9 ta raqam bo‘lishi kerak.')
        try:
            with self.session.get(BASE, params={'q': stir}, headers={
                'Accept': 'application/json',
                'User-Agent': 'ShartnomaBot/0.3 (company lookup)',
            }, timeout=(3, 6), allow_redirects=False, stream=True) as response:
                if response.status_code == 403:
                    raise LookupUnavailable('iHamkor dasturdan kirishni chekladi (403). Rasmiy API ruxsatini tekshiring.')
                if response.status_code == 429:
                    raise LookupUnavailable('iHamkor so‘rovlar chegarasiga yetildi. Keyinroq urinib ko‘ring.')
                if response.status_code != 200:
                    raise LookupUnavailable(f'iHamkor javob bermadi (HTTP {response.status_code}).')
                if 'application/json' not in response.headers.get('Content-Type', '').lower():
                    raise LookupUnavailable('iHamkor JSON o‘rniga boshqa sahifa qaytardi.')
                data = bytearray()
                for chunk in response.iter_content(65536):
                    data.extend(chunk)
                    if len(data) > 500_000:
                        raise LookupUnavailable('iHamkor javobi juda katta.')
        except requests.RequestException:
            raise LookupUnavailable('iHamkor bilan ulanishda xato. Keyinroq urinib ko‘ring.') from None
        import json
        try:
            payload = json.loads(data)
        except (ValueError, UnicodeError):
            raise LookupUnavailable('iHamkor JSON javobini o‘qib bo‘lmadi.') from None
        return parse_company(payload, stir)
