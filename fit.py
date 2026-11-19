"""Shrink fonts so the contract body fits 2 pages and the specification 1 page."""
import io
import logging
from zipfile import ZipFile, ZIP_DEFLATED
from xml.etree import ElementTree as ET

from templates import W, parse_xml, serialize_xml
from pdf_export import ExportError, convert_bytes, page_count, page_texts

MAIN_PAGES, SPEC_PAGES = 2, 1
DEFAULT_SIZE = 22          # Half-points; Normal style of the supplied template.
MIN_MAIN, MIN_SPEC = 15, 14  # 7.5pt / 7pt — still readable when printed.
MAX_STEPS = 10


def split_paragraph(body):
    """Index of the first top-level block that starts a new page (the specification)."""
    for index, block in enumerate(list(body)):
        if block.find(f'.//{W}pageBreakBefore') is not None:
            return index
        for br in block.iter(W + 'br'):
            if br.get(W + 'type') == 'page':
                return index + 1
    return None


def block_text(block):
    return ''.join(t.text or '' for t in block.iter(W + 't')).strip()


AFTER_SZ = {W + tag for tag in ('highlight', 'u', 'effect', 'bdr', 'shd', 'fitText', 'vertAlign', 'rtl',
                                 'cs', 'em', 'lang', 'eastAsianLayout', 'specVanish', 'oMath', 'rPrChange')}


def set_size(props, value):
    """Set w:sz and w:szCs keeping the schema order Word expects."""
    for tag in ('sz', 'szCs'):
        node = props.find(W + tag)
        if node is not None:
            props.remove(node)
    children = list(props)
    at = next((i for i, child in enumerate(children) if child.tag in AFTER_SZ), len(children))
    for offset, tag in enumerate(('sz', 'szCs')):
        props.insert(at + offset, ET.Element(W + tag, {W + 'val': value}))


def shrink_runs(blocks, delta, minimum):
    if not delta:
        return
    for block in blocks:
        holders = [(run, True) for run in block.iter(W + 'r')]
        holders += [(p.find(W + 'pPr'), False) for p in block.iter(W + 'p')]
        for holder, is_run in holders:
            if holder is None:
                continue
            props = holder.find(W + 'rPr')
            if props is None:
                if not is_run:
                    continue  # Paragraph mark keeps its style size.
                props = ET.Element(W + 'rPr')
                holder.insert(0, props)
            sz = props.find(W + 'sz')
            size = int(sz.get(W + 'val')) if sz is not None and (sz.get(W + 'val') or '').isdigit() else DEFAULT_SIZE
            set_size(props, str(max(minimum, size - delta)))


AFTER_SPACING = {W + tag for tag in ('ind', 'contextualSpacing', 'mirrorIndents', 'suppressOverlap', 'jc',
                                      'textDirection', 'textAlignment', 'textboxTightWrap', 'outlineLvl',
                                      'divId', 'cnfStyle', 'rPr', 'sectPr', 'pPrChange')}


def compact_tables(blocks, delta):
    """Long item lists: lower fixed row heights and drop spacing inside table cells."""
    if not delta:
        return
    factor = max(0.35, 1 - 0.12 * delta)
    for block in blocks:
        for height in block.iter(W + 'trHeight'):
            value = height.get(W + 'val') or ''
            if value.isdigit():
                height.set(W + 'val', str(int(int(value) * factor)))
        for cell in block.iter(W + 'tc'):
            for paragraph in cell.iter(W + 'p'):
                props = paragraph.find(W + 'pPr')
                if props is None:
                    props = ET.Element(W + 'pPr')
                    paragraph.insert(0, props)
                spacing = props.find(W + 'spacing')
                if spacing is None:
                    children = list(props)
                    at = next((i for i, child in enumerate(children) if child.tag in AFTER_SPACING), len(children))
                    spacing = ET.Element(W + 'spacing')
                    props.insert(at, spacing)
                spacing.set(W + 'before', '0')
                spacing.set(W + 'after', '0')


def rebuild(parts, original_xml, main_delta, spec_delta):
    tree = parse_xml(original_xml)
    body = tree.find(W + 'body')
    blocks = [block for block in body if block.tag != W + 'sectPr']
    split = split_paragraph(body)
    shrink_runs(blocks[:split], main_delta, MIN_MAIN)
    shrink_runs(blocks[split:], spec_delta, MIN_SPEC)
    compact_tables(blocks[split:], spec_delta)
    out = io.BytesIO()
    with ZipFile(out, 'w', ZIP_DEFLATED) as archive:
        for name, data in parts.items():
            archive.writestr(name, serialize_xml(tree, original_xml) if name == 'word/document.xml' else data)
    return out.getvalue()


def section_pages(pdf, marker):
    texts = page_texts(pdf)
    if texts is None or not marker:
        # Without pdftotext only the total is known: assume a 1-page specification.
        total = page_count(pdf)
        return max(total - SPEC_PAGES, 0), min(total, SPEC_PAGES)
    key = ' '.join(marker.split())[:30]
    for index, text in enumerate(texts):
        if key and key in ' '.join(text.split()):
            return index, len(texts) - index
    return len(texts), 0


def fit_document(docx_bytes, converter=convert_bytes):
    """Return (docx_bytes, pdf_bytes). pdf_bytes is None if LibreOffice failed.

    Documents without a page break before the specification are returned unchanged
    (only converted), so custom templates without that layout are not altered.
    """
    with ZipFile(io.BytesIO(docx_bytes)) as archive:
        parts = {name: archive.read(name) for name in archive.namelist()}
    original = parts.get('word/document.xml')
    body = parse_xml(original).find(W + 'body') if original else None
    split = split_paragraph(body) if body is not None else None
    try:
        pdf = converter(docx_bytes)
    except ExportError as error:
        logging.warning('fit skipped: %s', error)
        return docx_bytes, None
    if split is None:
        return docx_bytes, pdf
    blocks = [block for block in body if block.tag != W + 'sectPr']
    marker = next((block_text(b) for b in blocks[split:] if block_text(b)), '')
    current, main_delta, spec_delta = docx_bytes, 0, 0
    for _ in range(MAX_STEPS):
        main, spec = section_pages(pdf, marker)
        logging.info('fit main_pages=%d spec_pages=%d main_delta=%d spec_delta=%d', main, spec, main_delta, spec_delta)
        if main <= MAIN_PAGES and spec <= SPEC_PAGES:
            return current, pdf
        # Big overflow → bigger step, so long item lists converge quickly.
        if main > MAIN_PAGES:
            main_delta += 2 if main > MAIN_PAGES + 1 else 1
        if spec > SPEC_PAGES:
            spec_delta += 2 if spec > SPEC_PAGES + 1 else 1
        if main_delta > DEFAULT_SIZE or spec_delta > DEFAULT_SIZE:
            break
        candidate = rebuild(parts, original, main_delta, spec_delta)
        if candidate == current:
            break  # Already at the minimum readable size.
        try:
            pdf_candidate = converter(candidate)
        except ExportError as error:
            logging.warning('fit stopped: %s', error)
            break
        current, pdf = candidate, pdf_candidate
    logging.warning('fit: target page count not reached, best effort used')
    return current, pdf
