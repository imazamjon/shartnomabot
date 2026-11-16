"""Exact totals and Russian amount words for the supplied contract."""
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime

ONES = ['', 'один', 'два', 'три', 'четыре', 'пять', 'шесть', 'семь', 'восемь', 'девять']
TEENS = ['десять','одиннадцать','двенадцать','тринадцать','четырнадцать','пятнадцать','шестнадцать','семнадцать','восемнадцать','девятнадцать']
TENS = ['', '', 'двадцать','тридцать','сорок','пятьдесят','шестьдесят','семьдесят','восемьдесят','девяносто']
HUNDREDS = ['', 'сто','двести','триста','четыреста','пятьсот','шестьсот','семьсот','восемьсот','девятьсот']
SCALES = [('', '', ''), ('тысяча','тысячи','тысяч'), ('миллион','миллиона','миллионов'),
          ('миллиард','миллиарда','миллиардов'), ('триллион','триллиона','триллионов')]


def words_ru(number):
    number = int(number)
    if number == 0:
        return 'ноль'
    if not 0 <= number < 10 ** 15:
        raise ValueError('Сумма за пределами поддерживаемого диапазона.')
    chunks, scale = [], 0
    while number:
        group = number % 1000
        if group:
            parts = [HUNDREDS[group // 100]] if group >= 100 else []
            tens = group % 100
            if 10 <= tens <= 19:
                parts.append(TEENS[tens - 10])
            else:
                if tens >= 20:
                    parts.append(TENS[tens // 10])
                if tens % 10:
                    unit = ONES[tens % 10]
                    if scale == 1 and tens % 10 in (1, 2):
                        unit = {1:'одна', 2:'две'}[tens % 10]
                    parts.append(unit)
            if scale:
                form = 2 if 11 <= group % 100 <= 14 else (0 if group % 10 == 1 else 1 if 2 <= group % 10 <= 4 else 2)
                parts.append(SCALES[scale][form])
            chunks.insert(0, ' '.join(parts))
        number //= 1000
        scale += 1
    return ' '.join(chunks)


def fmt(value):
    return f'{Decimal(value).quantize(Decimal(".01"), rounding=ROUND_HALF_UP):,.2f}'.replace(',', ' ')


def calculate_item(item, rate='12', price_mode='included'):
    rate = Decimal(str(rate))
    if not rate.is_finite() or not 0 <= rate <= 100:
        raise ValueError('QQS stavkasi 0–100 oralig‘ida bo‘lsin.')
    q = Decimal(str(item.get('quantity', '1')))
    if not q.is_finite() or q <= 0:
        raise ValueError('Miqdor 0 dan katta bo‘lsin.')
    cent = Decimal('.01')
    if 'price' in item:
        price = Decimal(str(item['price']))
        if not price.is_finite() or price <= 0:
            raise ValueError('Narx 0 dan katta bo‘lsin.')
        if price_mode == 'included':
            unit = price * 100 / (100 + rate)
            gross = (price * q).quantize(cent, rounding=ROUND_HALF_UP)
            net = (unit * q).quantize(cent, rounding=ROUND_HALF_UP)
            vat = gross - net
        elif price_mode == 'excluded':
            unit = price.quantize(cent, rounding=ROUND_HALF_UP)
            net = (unit * q).quantize(cent, rounding=ROUND_HALF_UP)
            vat = (net * rate / 100).quantize(cent, rounding=ROUND_HALF_UP)
            gross = net + vat
        else:
            raise ValueError('Narx turi noto‘g‘ri.')
    else:  # Previously saved contracts with line totals.
        gross = Decimal(item['amount']).quantize(cent, rounding=ROUND_HALF_UP)
        net = (gross * 100 / (100 + rate)).quantize(cent, rounding=ROUND_HALF_UP)
        vat = gross - net
        unit = (net / q).quantize(cent, rounding=ROUND_HALF_UP) if item.get('quantity') else None
    if gross > Decimal('999999999999.99'):
        raise ValueError('Tovar jami summasi 999 999 999 999.99 dan oshmasin.')
    return unit, net, vat, gross


def build_values(number, date, seller, session):
    moment = datetime.strptime(date, '%d.%m.%Y')
    months = ['января','февраля','марта','апреля','мая','июня','июля','августа','сентября','октября','ноября','декабря']
    values = {'number':str(number), 'date':date, 'year':str(moment.year),
              'date_long':f'«{moment.day:02d}» {months[moment.month-1]} {moment.year} г.'}
    for prefix, company in [('seller', seller), ('buyer', session['buyer'])]:
        for key in ('name','stir','director','address','bank','account','mfo','phone','oked'):
            values[prefix + '_' + key] = str(company.get(key, ''))
    rate = Decimal(str(session.get('vat_rate', '12')))
    if not rate.is_finite() or not 0 <= rate <= 100:
        raise ValueError('QQS stavkasi noto‘g‘ri.')
    rate_text = format(rate.normalize(), 'f')
    values['vat_rate'] = rate_text
    values['vat_clause'] = f'с учетом НДС {rate_text}%' if rate else 'без НДС'
    values['vat_header'] = f'НДС {rate_text} %' if rate else 'Без НДС'
    rows, gross_total, net_total, vat_total = [], Decimal(0), Decimal(0), Decimal(0)
    for i, item in enumerate(session['items'], 1):
        unit, net, vat, gross = calculate_item(item, rate, session.get('price_mode', 'included'))
        rows.append({'item_number':str(i), 'item_name':str(item['name']), 'item_unit':str(item.get('unit') or '—'),
                     'item_quantity':str(item.get('quantity') or '—'), 'item_unit_price':fmt(unit) if unit is not None else '—',
                     'item_net':fmt(net), 'item_vat':fmt(vat), 'item_total':fmt(gross)})
        gross_total += gross; net_total += net; vat_total += vat
    if gross_total > Decimal('999999999999.99'):
        raise ValueError('Shartnoma jami summasi 999 999 999 999.99 dan oshmasin.')
    values.update(total=fmt(gross_total), net_total=fmt(net_total), vat_total=fmt(vat_total),
                  items='\n'.join(f'{row["item_number"]}. {row["item_name"]} — {row["item_total"]} so‘m' for row in rows))
    tiyin = int((gross_total - int(gross_total)) * 100)
    values['total_words'] = words_ru(int(gross_total)).capitalize() + f' сум {tiyin:02d} тийин'
    return values, rows
