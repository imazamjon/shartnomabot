"""Print-friendly A4 contract draft, generated without third-party packages."""
import io
from decimal import Decimal
from xml.sax.saxutils import escape
from zipfile import ZipFile, ZIP_DEFLATED

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
REL = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
WIDTH = 9410


def p(text, style=None, bold=False, align=None, after=80, keep=False):
    props = f'<w:spacing w:after="{after}"/>'
    if style:
        props += f'<w:pStyle w:val="{style}"/>'
    if align:
        props += f'<w:jc w:val="{align}"/>'
    if keep:
        props += '<w:keepNext/>'
    props += '<w:widowControl/>'
    run = '<w:rPr><w:b/></w:rPr>' if bold else ''
    safe = escape(str(text or '—'))
    return f'<w:p><w:pPr>{props}</w:pPr><w:r>{run}<w:t xml:space="preserve">{safe}</w:t></w:r></w:p>'


def cell(text, width, bold=False, shade=None, align=None, span=1):
    props = f'<w:tcW w:w="{width}" w:type="dxa"/><w:vAlign w:val="center"/>'
    if shade:
        props += f'<w:shd w:val="clear" w:fill="{shade}"/>'
    if span > 1:
        props += f'<w:gridSpan w:val="{span}"/>'
    return f'<w:tc><w:tcPr>{props}</w:tcPr>{p(text,bold=bold,align=align,after=0)}</w:tc>'


def row(cells, header=False):
    props = '<w:cantSplit/>' + ('<w:tblHeader/>' if header else '')
    return '<w:tr><w:trPr>' + props + '</w:trPr>' + ''.join(cells) + '</w:tr>'


def table(widths, rows):
    grid = ''.join(f'<w:gridCol w:w="{width}"/>' for width in widths)
    borders = ''.join(f'<w:{side} w:val="single" w:sz="4" w:color="D2D2D2"/>'
                      for side in ('top','left','bottom','right','insideH','insideV'))
    return (f'<w:tbl><w:tblPr><w:tblW w:w="{sum(widths)}" w:type="dxa"/>'
            '<w:tblLayout w:type="fixed"/><w:tblBorders>' + borders + '</w:tblBorders>'
            '<w:tblCellMar><w:top w:w="100" w:type="dxa"/><w:left w:w="130" w:type="dxa"/>'
            '<w:bottom w:w="100" w:type="dxa"/><w:right w:w="130" w:type="dxa"/>'
            '</w:tblCellMar></w:tblPr><w:tblGrid>' + grid + '</w:tblGrid>' + ''.join(rows) + '</w:tbl>')


def formatted(value):
    return f'{Decimal(value):,.2f}'.replace(',', ' ')


def document_bytes(number, date, seller, session):
    identifier = f'{number:06d}' if isinstance(number, int) else str(number)
    body = p('Shartnoma loyihasi', style='Title', align='center', after=90)
    body += p(f'Raqami  {identifier}     |     Sana  {date}', align='center', after=160)
    if session.get('demo'):
        body += p('SINOV NAMUNASI — rekvizitlar xayoliy', bold=True, align='center', after=120)
    body += p('Ushbu loyiha tomonlarning rekvizitlari, tovarlar ro‘yxati va umumiy summani tekshirish uchun tayyorlandi.', after=100)
    body += p('Tomonlar rekvizitlari', style='Heading1', after=100, keep=True)
    widths = [1450,3980,3980]
    rows = [row([cell(text,width,bold=True,shade='EFEFEF') for text,width in
                 zip(['Rekvizit','Sotuvchi','Xaridor'],widths)],header=True)]
    for key,label in [('name','Korxona'),('stir','STIR'),('director','Rahbar'),('address','Manzil'),
                      ('bank','Bank'),('account','Hisob raqami'),('mfo','MFO')]:
        rows.append(row([cell(label,widths[0],bold=True),cell(seller.get(key,''),widths[1],bold=key=='name'),
                         cell(session['buyer'].get(key,''),widths[2],bold=key=='name')]))
    body += table(widths,rows)
    body += p('Tovarlar va qiymati',style='Heading1',after=100,keep=True)
    widths = [550,6100,2760]
    rows = [row([cell('№',widths[0],bold=True,shade='EFEFEF',align='center'),
                 cell('Tovar nomi',widths[1],bold=True,shade='EFEFEF'),
                 cell('Summa, so‘m',widths[2],bold=True,shade='EFEFEF',align='right')],header=True)]
    for index,item in enumerate(session['items'],1):
        rows.append(row([cell(index,widths[0],align='center'),cell(item['name'],widths[1]),
                         cell(formatted(item['amount']),widths[2],align='right')]))
    total = sum((Decimal(item['amount']) for item in session['items']),Decimal(0))
    rows.append(row([cell('Jami',sum(widths[:2]),bold=True,shade='F5F5F5',span=2),
                     cell(formatted(total),widths[2],bold=True,shade='F5F5F5',align='right')]))
    body += table(widths,rows)
    body += p('Imzolar',style='Heading1',after=180,keep=True)
    # Tabs keep the signature blocks aligned without a layout-only table.
    body += ('<w:p><w:pPr><w:tabs><w:tab w:val="left" w:pos="4900"/></w:tabs>'
             '<w:spacing w:after="180"/><w:keepNext/></w:pPr>'
             '<w:r><w:rPr><w:b/></w:rPr><w:t>Sotuvchi</w:t><w:tab/><w:t>Xaridor</w:t></w:r></w:p>')
    body += ('<w:p><w:pPr><w:tabs><w:tab w:val="left" w:pos="4900"/></w:tabs>'
             '<w:spacing w:after="160"/></w:pPr><w:r><w:t>______________________</w:t>'
             '<w:tab/><w:t>______________________</w:t></w:r></w:p>')
    body += p('Loyiha holati: tomonlarning kelishilgan shartlari va tasdiqlangan shartnoma matni bilan yakunlanadi.',style='Note',after=0)
    body += ('<w:sectPr><w:footerReference w:type="default" r:id="rFooter"/>'
             '<w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1134" w:right="1248" '
             'w:bottom="1134" w:left="1248" w:header="450" w:footer="500"/></w:sectPr>')
    xml = f'<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="{W}" xmlns:r="{REL}"><w:body>{body}</w:body></w:document>'
    styles = (f'<?xml version="1.0"?><w:styles xmlns:w="{W}">'
              '<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman"/>'
              '<w:sz w:val="22"/><w:color w:val="000000"/></w:rPr></w:rPrDefault><w:pPrDefault><w:pPr>'
              '<w:spacing w:after="80" w:line="260" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>'
              '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>'
              '<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/>'
              '<w:rPr><w:b/><w:sz w:val="38"/><w:color w:val="000000"/></w:rPr></w:style>'
              '<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/>'
              '<w:pPr><w:keepNext/><w:spacing w:before="210" w:after="100"/><w:outlineLvl w:val="0"/></w:pPr>'
              '<w:rPr><w:b/><w:sz w:val="25"/><w:color w:val="000000"/></w:rPr></w:style>'
              '<w:style w:type="paragraph" w:styleId="Note"><w:name w:val="Note"/><w:basedOn w:val="Normal"/>'
              '<w:rPr><w:sz w:val="18"/></w:rPr></w:style></w:styles>')
    footer = (f'<?xml version="1.0"?><w:ftr xmlns:w="{W}"><w:p><w:pPr><w:jc w:val="center"/></w:pPr>'
              '<w:r><w:rPr><w:sz w:val="18"/></w:rPr><w:t xml:space="preserve">Bet </w:t></w:r>'
              '<w:fldSimple w:instr="PAGE"><w:r><w:t>1</w:t></w:r></w:fldSimple>'
              '<w:r><w:t xml:space="preserve"> / </w:t></w:r><w:fldSimple w:instr="NUMPAGES"><w:r><w:t>1</w:t></w:r></w:fldSimple>'
              '</w:p></w:ftr>')
    types = ('<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
             '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
             '<Default Extension="xml" ContentType="application/xml"/>'
             '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
             '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
             '<Override PartName="/word/footer1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/>'
             '</Types>')
    package_rel = ('<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   f'<Relationship Id="rDoc" Type="{REL}/officeDocument" Target="word/document.xml"/></Relationships>')
    document_rel = ('<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                    f'<Relationship Id="rStyles" Type="{REL}/styles" Target="styles.xml"/>'
                    f'<Relationship Id="rFooter" Type="{REL}/footer" Target="footer1.xml"/></Relationships>')
    out = io.BytesIO()
    with ZipFile(out,'w',ZIP_DEFLATED) as archive:
        for name,data in {'[Content_Types].xml':types,'_rels/.rels':package_rel,'word/document.xml':xml,
                          'word/styles.xml':styles,'word/footer1.xml':footer,
                          'word/_rels/document.xml.rels':document_rel}.items():
            archive.writestr(name,data)
    return out.getvalue()
