"""Read Orginfo's public HTML pages; no private API or authentication."""
from __future__ import annotations

import json
import re
import time
import logging
from pathlib import Path
from html.parser import HTMLParser
from urllib.parse import urlencode, urljoin, urlsplit
import requests

BASE = 'https://orginfo.uz'
_SESSION = requests.Session()


class LookupUnavailable(Exception):
    """Network, access restriction, or unexpected page layout."""


class TemporaryUnavailable(LookupUnavailable):
    """Transient network/upstream error, eligible for cached fallback."""


class Page(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.links, self.schemas, self.text = [], [], []
        self.script = None
        self.ignored = 0
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'a':
            href = attrs.get('href', '')
            if re.fullmatch(r'/uz/organization/[a-zA-Z0-9-]+/', href):
                if href not in self.links:
                    self.links.append(href)
        if tag in ('script', 'style'):
            self.ignored += 1
        if tag == 'script' and attrs.get('type') == 'application/ld+json':
            self.script = []

    def handle_data(self, data):
        if self.script is not None:
            self.script.append(data)
        if not self.ignored and data.strip():
            self.text.append(' '.join(data.split()))

    def handle_endtag(self, tag):
        if tag == 'script' and self.script is not None:
            try:
                self.schemas.append(json.loads(''.join(self.script)))
            except (ValueError, TypeError):
                pass
            self.script = None
        if tag in ('script', 'style'):
            self.ignored = max(0, self.ignored - 1)


def entities(value):
    if isinstance(value, list):
        for item in value:
            yield from entities(item)
    elif isinstance(value, dict):
        if value.get('@type') == 'Organization':
            yield value
        for key in ('mainEntity', '@graph'):
            if key in value:
                yield from entities(value[key])


def parse_detail(html, stir, url):
    page = Page(html)
    for schema in page.schemas:
        for org in entities(schema):
            # Never trust search position or a STIR in page title/navigation.
            if str(org.get('taxID', '')).strip() != stir:
                continue
            address = org.get('address', {})
            if isinstance(address, dict):
                address = ', '.join(str(address[key]).strip() for key in
                                    ('addressRegion', 'addressLocality', 'streetAddress') if address.get(key))
            employee = org.get('employee', {})
            people = employee if isinstance(employee, list) else [employee]
            director = next((person.get('name', '') for person in people
                             if isinstance(person, dict) and person.get('jobTitle') == 'Rahbar'), '')
            result = {
                'name': ' '.join(str(org.get('alternateName') or org.get('name', '')).split()),
                'stir': stir, 'director': director, 'address': str(address),
                'bank': '', 'account': '', 'mfo': '',
                'source_url': url, 'retrieved_at': int(time.time()),
            }
            if 'IFUT' in page.text:
                index = page.text.index('IFUT')
                if index + 1 < len(page.text):
                    match = re.match(r'([0-9]{5})\b', page.text[index + 1])
                    if match:
                        result['oked'] = match[1]
            if not result['name']:
                raise LookupUnavailable('Orginfo sahifa formati o‘zgargan.')
            return result
    raise LookupUnavailable('Orginfo sahifasidagi STIR yoki ma’lumot formati mos kelmadi.')


def fetch_html(path):
    headers = {
        'User-Agent': 'ShartnomaBot/0.2 (company lookup)',
        'Accept': 'text/html', 'Accept-Language': 'uz',
    }
    for attempt in range(2):
        url = BASE + path
        try:
            for redirect in range(3):
                with _SESSION.get(url, headers=headers, timeout=(3, 5), stream=True,
                                  allow_redirects=False) as response:
                    status = response.status_code
                    if status in (301, 302, 303, 307, 308):
                        target = urljoin(url, response.headers.get('Location', ''))
                        if urlsplit(target).scheme != 'https' or urlsplit(target).netloc != 'orginfo.uz':
                            raise LookupUnavailable('Orginfo boshqa saytga yo‘naltirdi.')
                        url = target
                        continue
                    if status in (403, 429):
                        raise TemporaryUnavailable('Orginfo hozir kirishni chekladi. Keyinroq urinib ko‘ring.')
                    if status >= 500:
                        break  # One retry for upstream errors only.
                    if status != 200:
                        raise LookupUnavailable(f'Orginfo sahifasi ochilmadi (HTTP {status}).')
                    data = bytearray()
                    for chunk in response.iter_content(65536):
                        data.extend(chunk)
                        if len(data) > 2_000_000:
                            raise LookupUnavailable('Orginfo javobi juda katta.')
                    return bytes(data).decode('utf-8')
            else:
                raise LookupUnavailable('Orginfo yo‘naltirishlari juda ko‘p.')
        except (requests.Timeout, requests.ConnectionError):
            pass
        except requests.RequestException:
            raise TemporaryUnavailable('Orginfo bilan ulanishda xato.') from None
        except UnicodeError:
            raise LookupUnavailable('Orginfo sahifasi matnini o‘qib bo‘lmadi.') from None
        if attempt == 0:
            time.sleep(.2)
    raise TemporaryUnavailable('Orginfo hozir sekin javob bermoqda. Keyinroq urinib ko‘ring.')


class Orginfo:
    def __init__(self, fetch=fetch_html, ttl=21600, cache_path=None, stale_ttl=604800):
        self.fetch, self.ttl, self.cache = fetch, ttl, {}
        self.cache_path = Path(cache_path) if cache_path else None
        self.stale_ttl = stale_ttl
        if self.cache_path:
            try:
                saved = json.loads(self.cache_path.read_text())
                if isinstance(saved, dict):
                    for stir, company in list(saved.items())[-128:]:
                        if self.valid_cached(stir, company):
                            self.cache[stir] = company
            except FileNotFoundError:
                pass
            except (OSError, ValueError, TypeError):
                logging.warning('Orginfo keshini o‘qib bo‘lmadi; jonli qidiruv ishlatiladi.')

    def valid_cached(self, stir, company):
        if not isinstance(company, dict) or not isinstance(stir, str) or not re.fullmatch(r'[0-9]{9}', stir):
            return False
        stamp = company.get('retrieved_at')
        return (company.get('stir') == stir and isinstance(company.get('name'), str) and bool(company['name'])
                and isinstance(stamp, (int, float)) and 0 <= time.time() - stamp < self.stale_ttl
                and isinstance(company.get('source_url'), str)
                and re.fullmatch(r'https://orginfo\.uz/uz/organization/[a-zA-Z0-9-]+/', company['source_url']) is not None
                and all(isinstance(company.get(key, ''), str) for key in ('director', 'address', 'bank', 'account', 'mfo')))

    def save_cache(self):
        if not self.cache_path:
            return
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.cache_path.with_suffix('.tmp')
            temp.write_text(json.dumps(self.cache, ensure_ascii=False))
            temp.chmod(0o600)
            temp.replace(self.cache_path)
        except OSError:
            logging.warning('Orginfo keshi diskka saqlanmadi; xotiradagi natija mavjud.')

    def lookup(self, stir):
        if not re.fullmatch(r'[0-9]{9}', stir):
            raise ValueError('STIR 9 ta raqam bo‘lishi kerak.')
        cached = self.cache.get(stir)
        if cached and time.time() - cached['retrieved_at'] < self.ttl:
            return dict(cached, cache_status='cached')
        try:
            result = self.lookup_live(stir)
        except TemporaryUnavailable as error:
            if cached and self.valid_cached(stir, cached):
                return dict(cached, cache_status='stale', lookup_warning=str(error))
            raise
        if result:
            self.cache.pop(stir, None)
            self.cache[stir] = result
            while len(self.cache) > 128:
                self.cache.pop(next(iter(self.cache)))
        else:
            self.cache.pop(stir, None)
        self.save_cache()
        return dict(result, cache_status='live') if result else None

    def lookup_live(self, stir):
        path = '/uz/search/organizations/?' + urlencode({'q': stir})
        search = Page(self.fetch(path))
        if not search.links:
            if any('Hech narsa topilmadi' in text for text in search.text):
                return None
            raise LookupUnavailable('Orginfo qidiruv sahifasini o‘qib bo‘lmadi.')
        # STIR search should yield one result; don't crawl unrelated companies.
        if len(search.links) != 1:
            raise LookupUnavailable('Orginfo qidiruvida yagona korxona aniqlanmadi.')
        detail = search.links[0]
        result = parse_detail(self.fetch(detail), stir, BASE + detail)
        return dict(result)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Orginfo STIR qidiruvini sinash')
    parser.add_argument('stir')
    args = parser.parse_args()
    try:
        print(json.dumps(Orginfo(cache_path=Path(__file__).resolve().parent / 'data/orginfo-cache.json').lookup(args.stir), ensure_ascii=False, indent=2))
    except (LookupUnavailable, ValueError) as error:
        parser.exit(1, str(error) + '\n')
