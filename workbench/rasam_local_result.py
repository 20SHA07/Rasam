"""Recover independent, valid fields from a local model's invoice draft.

This is a narrow adapter for imperfect schema following by small local models,
not a replacement for invoice validation. It never guesses aliases, currencies,
dates, separator locales, identifiers, or missing amounts. The original strict
validator and printed-amount guard run on every returned result.
"""
from datetime import date
from decimal import Decimal, InvalidOperation
import math
import re

from rasam_ai import CURRENCIES, DECIMAL_PATTERN, FIELD_NAMES, ExtractionError, validate_invoice
from rasam_groq import validate_text_result
from rasam_text import _issue_date, _number, _tax_identifier, draft_from_text

_KEYS = set(FIELD_NAMES) | {'is_invoice', 'warnings', 'field_warnings', 'line_items'}
_LINE_KEYS = {'description', 'quantity', 'unit_price', 'net_amount'}
_DIGITS = str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹', '01234567890123456789')
_EMPTY = {'', 'null', 'none', 'n/a'}
_ARABIC_AMOUNT = re.compile(r'^-?(?:0|[1-9][0-9]*|[1-9][0-9]{0,2}(?:٬[0-9]{3})+)(?:[.٫][0-9]+)?$')


def _text(value, limit):
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or len(value) > limit:
        return None
    return value


def _amount(value):
    """Return an exact plain decimal, or None. Never round or infer a locale."""
    if isinstance(value, str):
        value = value.strip().translate(_DIGITS)
        if len(value) > 100:
            return None
        if '٬' in value or '٫' in value:
            if _ARABIC_AMOUNT.fullmatch(value):
                value = value.replace('٬', '').replace('٫', '.')
        if not DECIMAL_PATTERN.fullmatch(value):
            # Use the same conservative explicit-literal rules as the local
            # parser: currency labels and clear grouping are formatting, while
            # ambiguous single separators and spaced columns remain unknown.
            value, _warning = _number(value)
            if value is None:
                return None
    elif type(value) is int:
        # Avoid converting extremely large untrusted integers to strings.
        if value.bit_length() > 333:
            return None
        value = str(value)
    elif isinstance(value, Decimal) or type(value) is float:
        if type(value) is float and not math.isfinite(value):
            return None
        number = value if isinstance(value, Decimal) else Decimal(str(value))
        if not number.is_finite():
            return None
        # Bound fixed-format expansion before allocating the output string.
        if number.adjusted() > 98 or number.as_tuple().exponent < -98:
            return None
        value = format(number, 'f')
    else:
        return None
    if len(value) > 100 or not DECIMAL_PATTERN.fullmatch(value):
        return None
    try:
        return value if Decimal(value).is_finite() else None
    except InvalidOperation:
        return None


def _main_value(field, value):
    if value is None:
        return None
    if isinstance(value, str) and value.strip().lower() in _EMPTY:
        return None
    if field in ('net', 'vat', 'total'):
        return _amount(value)
    if field == 'vatRate':
        if isinstance(value, str):
            value = value.strip().translate(_DIGITS)
            value = re.sub(r'\s*[%٪]\s*$', '', value).replace('٫', '.')
            # A comma is decimal formatting only for a plain percentage, never
            # a thousands separator or a mixed list of tax rates.
            if re.fullmatch(r'[0-9]+,[0-9]{1,2}', value):
                value = value.replace(',', '.')
            if not DECIMAL_PATTERN.fullmatch(value):
                return None
        value = _amount(value)
        return value if value is not None and 0 <= Decimal(value) <= 100 else None
    if field == 'supplierVatNumber':
        if not isinstance(value, str):
            return None
        value, _warning = _tax_identifier(value)
        return value
    value = _text(value, 1000)
    if value is None:
        return None
    if field == 'currency':
        value = value.upper()
        return value if value in CURRENCIES else None
    if field == 'date':
        if not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', value):
            # Written month names and day/month pairs with one value over 12
            # are explicit. The shared parser rejects uncertain day/month order
            # and two-digit years instead of assuming a locale or century.
            value, _warning = _issue_date(value)
            return value
        try:
            date.fromisoformat(value)
        except ValueError:
            return None
    return value


def normalize_local_result(invoice, text):
    """Normalize known fields independently, then enforce the strict contract.

    Unrecognized root keys, wrapped results, and uncertain document identity are
    rejected wholesale. Invalid individual values are cleared with review notes.
    The caller's object is not modified and raw failed values are not echoed.
    """
    if (not isinstance(invoice, dict) or not set(invoice).issubset(_KEYS)
            or type(invoice.get('is_invoice')) is not bool):
        raise ExtractionError('invalid_response',
                              'The local AI did not return a recognizable invoice draft. Use local OCR or try again.')

    changes = []
    own_fields = []
    result = {'is_invoice': invoice['is_invoice']}
    for field in FIELD_NAMES:
        raw = invoice.get(field)
        value = _main_value(field, raw)
        result[field] = value
        if field not in invoice:
            own_fields.append({'field': field, 'message': 'The local AI omitted this field. Check the original.'})
        elif raw is not None and value is None:
            own_fields.append({'field': field, 'message': 'The local AI value was missing or invalid and was left empty. Check the original.'})

    warnings = invoice.get('warnings', [])
    clean_warnings = []
    if not isinstance(warnings, list):
        changes.append('Invalid AI review notes were omitted.')
    else:
        for warning in warnings[:30]:
            clean = _text(warning, 1000)
            if clean is not None:
                clean_warnings.append(clean)
        if len(clean_warnings) != len(warnings):
            changes.append('Invalid or excess AI review notes were omitted.')

    field_warnings = invoice.get('field_warnings', [])
    clean_fields = []
    if not isinstance(field_warnings, list):
        changes.append('Invalid AI field notes were omitted.')
    else:
        for warning in field_warnings[:30]:
            if (isinstance(warning, dict) and set(warning) == {'field', 'message'}
                    and isinstance(warning['field'], str) and warning['field'] in FIELD_NAMES):
                message = _text(warning['message'], 1000)
                if message is not None:
                    clean_fields.append({'field': warning['field'], 'message': message})
        if len(clean_fields) != len(field_warnings):
            changes.append('Invalid or excess AI field notes were omitted.')

    items = invoice.get('line_items', [])
    clean_items = []
    items_changed = not isinstance(items, list)
    if isinstance(items, list):
        items_changed = len(items) > 50
        for item in items[:50]:
            if not isinstance(item, dict) or not set(item).issubset(_LINE_KEYS):
                items_changed = True
                continue
            description = _text(item.get('description'), 2000)
            if description is None or description.lower() in _EMPTY:
                items_changed = True
                continue
            clean_item = {'description': description}
            for field in ('quantity', 'unit_price', 'net_amount'):
                raw = item.get(field)
                value = _amount(raw) if raw is not None else None
                clean_item[field] = value
                if field not in item or (raw is not None and value is None):
                    items_changed = True
            clean_items.append(clean_item)
    if items_changed:
        changes.append('Invalid or excess AI line details were omitted or left empty. Check the original line items.')

    if not result['is_invoice']:
        for field in FIELD_NAMES:
            result[field] = None
        clean_items = []
        changes.append('The local AI did not identify one invoice. Fields were left empty; check the file before continuing.')
    partial_note = 'Some local AI fields were left empty. Valid draft fields were kept; review every value against the original.'
    if own_fields:
        changes.append(partial_note)

    # Preserve the adapter's notices when a model fills the entire warning budget.
    result['warnings'] = clean_warnings[:30 - len(changes)] + changes
    # Reserve five notes for amount, percentage and tax identifier grounding.
    result['field_warnings'] = clean_fields[:25 - len(own_fields)] + own_fields
    result['line_items'] = clean_items
    result = validate_text_result(result, text)

    # A small local model can miss a clear label even after OCR read it. Recover
    # only these supported fields, only from a parser-confirmed single invoice,
    # and never replace a usable AI field or infer a missing date/rate/number.
    fields = ('date', 'vatRate', 'supplierVatNumber')
    if result['is_invoice'] and any(result[field] is None for field in fields):
        source = draft_from_text(text)
        filled = []
        if source['is_invoice']:
            for field in fields:
                if result[field] is None and source[field] is not None:
                    result[field] = source[field]
                    filled.append(field)
        if filled:
            # Notes about the model's discarded suggestion no longer describe
            # the copied value. Its source and need for review are explicit.
            result['field_warnings'] = [note for note in result['field_warnings']
                                        if note['field'] not in filled]
            if all(result[note['field']] is not None for note in own_fields):
                result['warnings'] = [note for note in result['warnings'] if note != partial_note]
            labels = {'date': 'invoice date', 'vatRate': 'VAT percentage',
                      'supplierVatNumber': 'supplier VAT number'}
            note = ('Filled ' + ', '.join(labels[field] for field in filled)
                    + ' from labeled OCR text; review these fields against the original.')
            result['warnings'] = result['warnings'][:29] + [note]
    return validate_invoice(result)
