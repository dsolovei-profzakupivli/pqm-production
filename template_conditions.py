"""Provider-neutral Stage 2C grammar. Data comparisons only; never eval."""
import re
from dataclasses import dataclass

KEY = r'[a-z_][a-z0-9_]*(?:\.[a-z_][a-z0-9_]*)+'
OPEN = re.compile(r'\{\{#if\s+(' + KEY + r')\s*==\s*"([^"\\\r\n{}]*)"\s*\}\}')


class ConditionalError(ValueError):
    pass


def field_spec(key, fields, document_type):
    field = next((f for f in fields if f['key'] == key), None)
    if field is None:
        raise ConditionalError('Невідоме поле: ' + key)
    if document_type not in field['available_for'] or not field['active'] or field['deprecated']:
        raise ConditionalError('Поле недоступне для документа: ' + key)
    if field.get('binding_status') != 'VALID':
        raise ConditionalError('Поле не має перевіреного binding: ' + key)
    return field


@dataclass(frozen=True)
class Condition:
    key: str
    literal: str

    def evaluate(self, context, fields, document_type):
        field = field_spec(self.key, fields, document_type)
        value = context.get(self.key)
        if not isinstance(value, str):
            raise ConditionalError('Відсутнє або некоректне значення: ' + self.key)
        if field['value_type'] == 'enum' and value not in field['enum_values']:
            raise ConditionalError('Невідоме значення enum: ' + self.key)
        return value == self.literal


def parse_marker(text, fields, document_type):
    text = text.strip()
    if text == '{{/if}}':
        return 'close'
    match = OPEN.fullmatch(text)
    if not match:
        raise ConditionalError('Непідтримувана умова або marker: ' + text)
    key, literal = match.groups()
    field = field_spec(key, fields, document_type)
    if field['value_type'] not in ('string', 'enum'):
        raise ConditionalError('Умова потребує string/enum: ' + key)
    if field['value_type'] == 'enum':
        if not field.get('enum_values') or literal not in field['enum_values']:
            raise ConditionalError('Недопустимий enum literal: ' + key)
    return Condition(key, literal)
