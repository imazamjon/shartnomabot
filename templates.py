"""Fill a user's Word template, including placeholders split across runs."""
import io
import re
from decimal import Decimal
from xml.etree import ElementTree as ET
from zipfile import ZipFile, BadZipFile, ZIP_DEFLATED
from copy import deepcopy
from contract_values import build_values

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
TOKEN = re.compile(r'\{\{([a-z_]+)\}\}')
ITEM_KEYS = {'item_number','item_name','item_unit','item_quantity','item_unit_price','item_net','item_vat','item_total'}
KEYS = {'number', 'date', 'date_long', 'year', 'items', 'total','total_words','net_total','vat_total','vat_rate','vat_clause','vat_header'} | ITEM_KEYS | {
    prefix + '_' + key for prefix in ('seller', 'buyer')
    for key in ('name', 'stir', 'director', 'address', 'bank', 'account', 'mfo','phone','oked')
}


def checked_parts(data):
    try:
        with ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            if len(entries) > 1000 or sum(item.file_size for item in entries) > 30_000_000:
                raise ValueError('Word shablon juda katta.')
            names = [item.filename for item in entries]
            if 'word/document.xml' not in names or len(set(names)) != len(names):
                raise ValueError('Word shablon noto‘g‘ri.')
            parts = {item.filename: archive.read(item) for item in entries}
    except (BadZipFile, RuntimeError, KeyError):
        raise ValueError('Oddiy .docx Word faylini yuboring.') from None
    for name in parts:
        if 'vbaProject' in name or name.endswith('.bin'):
            raise ValueError('Makrossiz .docx Word faylini yuboring.')
    return parts


def parse_xml(data):
    if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():
        raise ValueError('Word XML formati qo‘llab-quvvatlanmaydi.')
    try:
        return ET.fromstring(data)
    except ET.ParseError:
        raise ValueError('Word XML buzilgan.') from None


def serialize_xml(tree, original):
    # Preserve namespace declarations used by Word's mc:Ignorable attribute.
    # ElementTree drops namespaces that appear only inside attribute values.
    declared = re.findall(rb'\s(xmlns(?::[A-Za-z_][\w.-]*)?)\s*=\s*([\"\'])(.*?)\2', original)
    for prefix, _, uri in declared:
        if prefix.startswith(b'xmlns:'):
            try:
                ET.register_namespace(prefix[6:].decode(), uri.decode())
            except ValueError:
                pass
    data = ET.tostring(tree, encoding='utf-8', xml_declaration=True)
    start = data.find(b'<', data.find(b'?>') + 2)
    end = data.find(b'>', start)
    root = data[start:end]
    additions = b''
    for prefix, _, uri in declared:
        if re.search(rb'\s' + re.escape(prefix) + rb'\s*=', root + additions):
            continue
        additions += b' ' + prefix + b'="' + uri.replace(b'"', b'&quot;') + b'"'
    return data[:end] + additions + data[end:]


def inspect_template(data):
    parts = checked_parts(data)
    tokens = set()
    for name, part in parts.items():
        if name.startswith('word/') and name.endswith('.xml'):
            tree = parse_xml(part)
            for paragraph in tree.iter(W + 'p'):
                tokens.update(TOKEN.findall(''.join(t.text or '' for t in paragraph.iter(W + 't'))))
    unknown = tokens - KEYS
    if unknown:
        raise ValueError('Noma’lum shablon maydonlari: ' + ', '.join(sorted(unknown)))
    if (not {'number', 'buyer_name', 'seller_name', 'total'} <= tokens
            or not tokens & {'date', 'date_long'} or not tokens & {'items', 'item_name'}):
        raise ValueError('Shablonda raqam, sana, sotuvchi, xaridor, tovarlar va jami summa maydonlari bo‘lishi kerak.')
    return parts


def replace_paragraph(paragraph, values):
    nodes = list(paragraph.iter(W + 't'))
    text = ''.join(node.text or '' for node in nodes)
    matches = list(TOKEN.finditer(text))
    if not matches:
        return False
    for match in reversed(matches):
        if match[1] not in values:
            raise ValueError('Tovar jadvalidagi maydon qator ichida bo‘lishi kerak: ' + match[1])
        offset = 0
        for node in nodes:
            original = node.text or ''
            end = offset + len(original)
            if offset < match.end() and end > match.start():
                left = max(0, match.start() - offset)
                right = min(len(original), match.end() - offset)
                replacement = values[match[1]] if offset <= match.start() < end else ''
                node.text = original[:left] + replacement + original[right:]
            offset = end
    for run in paragraph.iter(W + 'r'):
        for node in list(run):
            if node.tag != W + 't':
                continue
            index = list(run).index(node)
            chunks = (node.text or '').split('\n')
            run.remove(node)
            for i, chunk in enumerate(chunks):
                if i:
                    run.insert(index, ET.Element(W + 'br')); index += 1
                t = ET.Element(W + 't', {'{http://www.w3.org/XML/1998/namespace}space': 'preserve'})
                t.text = chunk; run.insert(index, t); index += 1
    return True


def fill_template(data, number, date, seller, session):
    parts = inspect_template(data)
    values, item_rows = build_values(number, date, seller, session)
    for name, part in list(parts.items()):
        if not name.startswith('word/') or not name.endswith('.xml'):
            continue
        tree = parse_xml(part)
        changed = False
        for table in tree.iter(W + 'tbl'):
            for row in list(table):
                if row.tag != W + 'tr':
                    continue
                text = ''.join(t.text or '' for t in row.iter(W + 't'))
                if '{{item_name}}' not in text:
                    continue
                at = list(table).index(row)
                table.remove(row)
                for i, row_values in enumerate(item_rows):
                    cloned = deepcopy(row)
                    for paragraph in cloned.iter(W + 'p'):
                        replace_paragraph(paragraph, {**values, **row_values})
                    table.insert(at + i, cloned)
                changed = True
        for paragraph in tree.iter(W + 'p'):
            changed = replace_paragraph(paragraph, values) or changed
        if changed:
            parts[name] = serialize_xml(tree, part)
    out = io.BytesIO()
    with ZipFile(out, 'w', ZIP_DEFLATED) as archive:
        for name, part in parts.items():
            archive.writestr(name, part)
    return out.getvalue()
