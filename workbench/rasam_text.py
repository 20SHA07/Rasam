"""Conservative invoice drafts from OCR text, without a model or API key.

This is a label-based fallback, not learned accounting or an accuracy score.
Only explicit document values are copied. The caller must retain the source and
require human review before accepting any draft.
"""
from datetime import date
from decimal import Decimal, InvalidOperation
import re

from rasam_ai import FIELD_NAMES, validate_invoice


_DIGITS = str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹', '01234567890123456789')
_DIRECTION_MARKS = re.compile('[\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]')
_CURRENCY_PATTERNS = {
    'SAR': r'\bSAR\b|\bSaudi\s+riyals?\b|ريال\s+سعودي|ر\.\s?س\.?',
    'AED': r'\bAED\b|\bUAE\s+dirhams?\b|\bEmirati\s+dirhams?\b|درهم\s+إماراتي|درهم\s+اماراتي|د\.\s?إ\.?',
    'USD': r'\bUSD\b|\bUS\s+dollars?\b|US\$|دولار\s+أمريكي|دولار\s+امريكي',
    'EUR': r'\bEUR\b|\beuros?\b|€|يورو',
    'GBP': r'\bGBP\b|\bpounds?\s+sterling\b|£|جنيه\s+إسترليني|جنيه\s+استرليني',
}
_CURRENCY_RE = re.compile('|'.join('(?:' + pattern + ')' for pattern in _CURRENCY_PATTERNS.values()), re.I)
_UNSUPPORTED_CURRENCY = re.compile(r'\b(?:KWD|BHD|OMR|QAR|INR|PKR|EGP|JPY|CNY)\b', re.I)
_LABELS = {
    'supplier': r'(?:supplier(?:\s+name)?|seller(?:\s+name)?|vendor(?:\s+name)?|from|اسم\s+المورد|المورد|اسم\s+البائع|البائع|من)',
    'invoiceNumber': r'(?:invoice\s*(?:number|no\.?|#)|(?:رقم\s+(?:ال)?فاتورة))',
    'date': r'(?:invoice\s+date|issue\s+date|date\s+of\s+issue|date|تاريخ\s+(?:إصدار\s+|اصدار\s+)?(?:ال)?فاتورة|تاريخ\s+الإصدار|تاريخ\s+الاصدار|التاريخ)',
    'net': r'(?:net(?:\s+(?:amount|total))?(?:\s+(?:excluding|excl\.?)\s+(?:VAT|tax))?|sub\s*total(?:\s+(?:excluding|excl\.?)\s+(?:VAT|tax))?|total\s+(?:excluding|excl\.?)\s+(?:VAT|tax)|taxable\s+amount|الإجمالي\s+قبل\s+الضريبة|الاجمالي\s+قبل\s+الضريبة|إجمالي\s+بدون\s+الضريبة|اجمالي\s+بدون\s+الضريبة|المجموع\s+الفرعي|صافي\s+المبلغ)',
    'vat': r'(?:total\s+(?:VAT|tax)(?:\s+amount)?|VAT(?:\s+amount)?|tax\s+amount|ضريبة\s+القيمة\s+المضافة|مبلغ\s+(?:ضريبة\s+القيمة\s+المضافة|الضريبة)|إجمالي\s+الضريبة|اجمالي\s+الضريبة)',
    'total': r'(?:grand\s+total|invoice\s+total|total\s+(?:including|incl\.?)\s+(?:VAT|tax)|total\s+amount(?:\s+including\s+(?:VAT|tax))?|total|الإجمالي\s+شامل\s+الضريبة|الاجمالي\s+شامل\s+الضريبة|إجمالي\s+الفاتورة|اجمالي\s+الفاتورة|المجموع\s+الكلي|الإجمالي\s+النهائي|الاجمالي\s+النهائي|الإجمالي|الاجمالي)',
}
_MONTHS = {}
for _index, _names in enumerate((
    ('january', 'jan', 'يناير'), ('february', 'feb', 'فبراير'),
    ('march', 'mar', 'مارس'), ('april', 'apr', 'أبريل', 'ابريل'),
    ('may', 'مايو'), ('june', 'jun', 'يونيو'), ('july', 'jul', 'يوليو'),
    ('august', 'aug', 'أغسطس', 'اغسطس'), ('september', 'sep', 'sept', 'سبتمبر'),
    ('october', 'oct', 'أكتوبر', 'اكتوبر'), ('november', 'nov', 'نوفمبر'),
    ('december', 'dec', 'ديسمبر'),
), 1):
    for _name in _names:
        _MONTHS[_name] = _index


def _normalize(text):
    return _DIRECTION_MARKS.sub('', text).translate(_DIGITS).replace('\u00a0', ' ')


def _label_value(line, field):
    label = _LABELS[field]
    if field == 'vat':
        label += r'(?:\s*\(?\s*[0-9]+(?:[.,٫][0-9]+)?\s*[%٪]\s*\)?)?'
    # A colon or whitespace separates a label from a value. Never consume a
    # minus sign as punctuation: a credit amount must keep its printed sign.
    separator = r'(?:\s*[:：]\s*|\s+)'
    if field == 'invoiceNumber':
        separator = r'(?:\s*[:：]\s*|\s+|(?<=[#\.]))'
    match = re.fullmatch(r'\s*' + label + separator + r'(.+?)\s*', line, re.I)
    return match.group(1).strip() if match else None


def _number(value):
    value = _normalize(value)
    value = _CURRENCY_RE.sub('', value).strip()
    # A bare dollar is not enough to identify currency, but the printed numeric
    # amount is still useful. Currency ambiguity is reported separately.
    value = value.replace('$', '').strip()
    negative = value.startswith('(') and value.endswith(')')
    if negative:
        value = value[1:-1].strip()
    if not value or not re.fullmatch(r'-?[0-9][0-9\s.,٫٬]*', value):
        return None, 'The label does not have one clear printed amount; review the source.'
    sign = '-' if value.startswith('-') or negative else ''
    value = value.removeprefix('-')
    if re.search(r'\s', value):
        # OCR can flatten adjacent table columns into "100 115.00". Without
        # layout evidence, joining those numbers could invent a larger amount.
        return None, 'Spaces could be thousands grouping or separate table values; review this amount on the source.'
    if '٬' in value:
        if not re.fullmatch(r'[0-9]{1,3}(?:٬[0-9]{3})+(?:[٫.][0-9]+)?', value):
            return None, 'The amount has unclear grouping separators.'
        value = value.replace('٬', '')
    if '٫' in value:
        if not re.fullmatch(r'[0-9]+٫[0-9]+', value):
            return None, 'The amount has mixed or unclear decimal separators.'
        value = value.replace('٫', '.')
    elif ',' in value and '.' in value:
        # Both separators determine the locale only with valid grouping and a
        # one/two-digit decimal part. Never guess which of two amounts is total.
        decimal_separator = ',' if value.rfind(',') > value.rfind('.') else '.'
        grouping = '.' if decimal_separator == ',' else ','
        pattern = r'[0-9]{1,3}(?:' + re.escape(grouping) + r'[0-9]{3})+' + re.escape(decimal_separator) + r'[0-9]{1,2}'
        if not re.fullmatch(pattern, value):
            return None, 'The amount has mixed or unclear decimal separators.'
        value = value.replace(grouping, '').replace(decimal_separator, '.')
    elif ',' in value or '.' in value:
        separator = ',' if ',' in value else '.'
        if value.count(separator) > 1:
            if not re.fullmatch(r'[0-9]{1,3}(?:' + re.escape(separator) + r'[0-9]{3}){2,}', value):
                return None, 'The amount has unclear grouping separators.'
            value = value.replace(separator, '')
        else:
            whole, fractional = value.split(separator)
            if not whole or not fractional or len(fractional) > 2:
                return None, 'The decimal or thousands separator is ambiguous; enter the amount from the source.'
            value = whole + '.' + fractional
    if len(value) > 98:
        return None, 'The printed amount is too long to extract safely.'
    try:
        number = Decimal(sign + value)
    except InvalidOperation:
        return None, 'The printed amount could not be read as a number.'
    # Decimal removes leading zeroes without changing precision or calculating.
    return format(number, 'f'), None


def _issue_date(value):
    value = _normalize(value).strip()
    if re.search(r'هجري|هجريه|hijri|(?:\s|[0-9])هـ?\s*$', value, re.I):
        return None, 'The date may be Hijri; enter the Gregorian issue date after review.'
    year = month = day = None
    match = re.fullmatch(r'([0-9]{4})([-/])([0-9]{1,2})\2([0-9]{1,2})', value)
    if match:
        year, month, day = int(match[1]), int(match[3]), int(match[4])
    else:
        match = re.fullmatch(r'([0-9]{1,2})([-/])([0-9]{1,2})\2([0-9]{4})', value)
        if match:
            first, second, year = int(match[1]), int(match[3]), int(match[4])
            if first <= 12 and second <= 12 and first != second:
                return None, 'Day/month order is ambiguous; confirm the issue date from the source.'
            if first > 12:
                day, month = first, second
            else:
                month, day = first, second
        else:
            cleaned = re.sub(r'[,،]', ' ', value.casefold())
            parts = cleaned.split()
            if len(parts) == 3 and parts[2].isdigit():
                year = int(parts[2])
                if parts[0].isdigit() and parts[1].rstrip('.') in _MONTHS:
                    day, month = int(parts[0]), _MONTHS[parts[1].rstrip('.')]
                elif parts[1].isdigit() and parts[0].rstrip('.') in _MONTHS:
                    month, day = _MONTHS[parts[0].rstrip('.')], int(parts[1])
    if year is None or month is None or day is None or not 1900 <= year <= 2199:
        return None, 'No unambiguous Gregorian issue date was found beside this label.'
    try:
        return date(year, month, day).isoformat(), None
    except ValueError:
        return None, 'The printed issue date is invalid or was misread.'


def _identifier(value):
    value = _normalize(value)
    if not re.fullmatch(r'[\w][\w./-]{0,199}', value, re.UNICODE):
        return None, 'The invoice identifier is unclear; confirm it is not a purchase order or payment reference.'
    if value.casefold() in {'number', 'no', 'date', 'رقم', 'تاريخ'}:
        return None, 'No invoice identifier was printed beside the invoice number label.'
    return value, None


def _supplier(value):
    # Do not turn an entire OCR row containing several columns into a seller.
    if len(value) > 1000 or re.search(r'(?:invoice|customer|buyer|bill\s+to|tax\s+id|VAT\s+number)\s*[:#]|(?:رقم\s+الفاتورة|العميل)\s*:', value, re.I):
        return None, 'The supplier label shares an unclear row with other fields; review the source.'
    if not any(character.isalpha() for character in value):
        return None, 'The supplier name is unclear; review the issuing seller on the source.'
    return value.strip(), None


def draft_from_text(text, warnings=None):
    """Return a schema-valid, review-required draft from explicit OCR labels.

    Missing values stay null, including VAT. Distinct invoice identifiers reject
    the whole file rather than merge documents. No line items or GL coding are
    inferred by this fallback.
    """
    result = {field: None for field in FIELD_NAMES}
    result.update(is_invoice=False, warnings=[], field_warnings=[], line_items=[])

    def warn(message):
        message = str(message).strip()[:1000]
        if message and message not in result['warnings'] and len(result['warnings']) < 30:
            result['warnings'].append(message)

    def field_warn(field, message):
        entry = {'field': field, 'message': message[:1000]}
        if entry not in result['field_warnings'] and len(result['field_warnings']) < 30:
            result['field_warnings'].append(entry)

    warn('Local OCR draft: recognition and field matching can be wrong. Review every value against the source before approval.')
    if warnings:
        # Reserve space for the parser's own document-level findings, including
        # credit-note and multiple-invoice warnings, even after a noisy OCR run.
        for warning in ([warnings] if isinstance(warnings, str) else warnings)[:20]:
            if isinstance(warning, str):
                warn(warning)
    if not isinstance(text, str) or not text.strip():
        warn('No readable invoice text was found. Enter the fields manually or try a clearer file.')
        return validate_invoice(result)
    if len(text) > 200000:
        warn('The extracted text is too long to review as one invoice. Split the file and try again.')
        return validate_invoice(result)
    original_lines = [_DIRECTION_MARKS.sub('', line).strip() for line in text.splitlines() if line.strip()]
    lines = [_normalize(line) for line in original_lines]
    candidates = {field: [] for field in FIELD_NAMES if field != 'currency'}
    parsers = {'supplier': _supplier, 'invoiceNumber': _identifier, 'date': _issue_date,
               'net': _number, 'vat': _number, 'total': _number}
    for original, line in zip(original_lines, lines):
        for field in candidates:
            value = _label_value(original if field == 'supplier' else line, field)
            if value is not None:
                candidates[field].append(parsers[field](value))
    identifiers = {value for value, _ in candidates['invoiceNumber'] if value is not None}
    if len(identifiers) > 1:
        warn('Different invoice numbers were found. This may contain multiple invoices or an unclear correction; split or review the file before extracting one invoice.')
        return validate_invoice(result)

    anchor = any(re.match(r'^(?:(?:simplified\s+)?tax\s+invoice|invoice|credit\s+note|فاتورة(?:\s+ضريبية)?|الفاتورة|إشعار\s+دائن|اشعار\s+دائن)(?:\b|\s|[:#])', line, re.I) for line in lines)
    explicit_id_and_amount = bool(identifiers) and any(value is not None for field in ('net', 'vat', 'total') for value, _ in candidates[field])
    non_posting = any(re.match(r'^(?:pro[ -]?forma\s+invoice|quotation|purchase\s+order|عرض\s+سعر|أمر\s+شراء|امر\s+شراء)(?:\b|\s|[:#])', line, re.I) for line in lines)
    if non_posting or not (anchor or explicit_id_and_amount):
        warn('This text does not clearly identify a single invoice for review. Purchase orders, quotations and pro forma documents must not become invoice drafts.')
        return validate_invoice(result)
    result['is_invoice'] = True

    for field, values in candidates.items():
        if not values:
            field_warn(field, 'No clear ' + {'invoiceNumber': 'invoice number', 'net': 'invoice net amount excluding tax', 'vat': 'printed VAT amount', 'total': 'invoice grand total'}.get(field, field) + ' label and value were found; enter it from the source.')
            continue
        invalid = [reason for value, reason in values if value is None]
        if invalid:
            field_warn(field, invalid[0])
            continue
        if field in ('net', 'vat', 'total'):
            unique = {Decimal(value) for value, _ in values}
        else:
            unique = {re.sub(r'\s+', ' ', value).casefold() for value, _ in values}
        if len(unique) != 1:
            field_warn(field, 'Conflicting values were found for this field; choose the correct invoice-level value from the source.')
            continue
        result[field] = values[0][0]

    normalized = '\n'.join(lines)
    currencies = {code for code, pattern in _CURRENCY_PATTERNS.items() if re.search(pattern, normalized, re.I)}
    unsupported = sorted(set(match.upper() for match in _UNSUPPORTED_CURRENCY.findall(normalized)))
    bare_dollar = '$' in _CURRENCY_RE.sub('', normalized)
    if len(currencies) == 1 and not unsupported and not (bare_dollar and 'USD' not in currencies):
        result['currency'] = currencies.pop()
    elif unsupported:
        field_warn('currency', 'Printed currency ' + ', '.join(unsupported) + ' is not supported by this register; do not substitute a different currency.')
    elif len(currencies) > 1:
        field_warn('currency', 'Multiple currencies were found; confirm the invoice currency from the source.')
    elif bare_dollar:
        field_warn('currency', 'A bare $ does not identify which dollar currency is used; confirm the currency.')
    else:
        field_warn('currency', 'No explicit supported invoice currency was found; do not infer it from the supplier or country.')
    if re.search(r'\bcredit\s+note\b|إشعار\s+دائن|اشعار\s+دائن', normalized, re.I) or any(result[field] is not None and Decimal(result[field]) < 0 for field in ('net', 'vat', 'total')):
        warn('This is a credit note or contains negative amounts. Printed signs are preserved; this register may not support approving credit notes.')
    if all(result[field] is not None for field in ('net', 'vat', 'total')):
        if Decimal(result['net']) + Decimal(result['vat']) != Decimal(result['total']):
            warn('The printed net plus VAT does not equal the printed total. Other charges or an OCR error may explain this; no amounts were changed.')
    warn('Local field matching does not map line items or account codes. Review the original invoice for those details.')
    return validate_invoice(result)
