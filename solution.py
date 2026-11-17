#!/usr/bin/env python3
"""Локальная сводка из структурированных данных. Внешних зависимостей нет."""
import argparse
import json
import sys
from collections import Counter
from datetime import date, datetime
from pathlib import Path


def date_time(value):
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError('укажите часовой пояс в дате и времени')
    return parsed


def summarize(data):
    if not isinstance(data, dict):
        raise ValueError('корень JSON должен быть объектом')
    now = date_time(data['as_of'])
    if not isinstance(data['cases'], list):
        raise ValueError('cases должен быть списком')
    results = []
    identifiers = [case.get('id') for case in data['cases'] if isinstance(case, dict) and isinstance(case.get('id'), str) and case['id'].strip()]
    duplicate_ids = {identifier for identifier, count in Counter(identifiers).items() if count > 1}
    for index, case in enumerate(data['cases'], 1):
        identifier = case.get('id') if isinstance(case, dict) else None
        item = {'id': identifier if isinstance(identifier, str) and identifier.strip() else f'строка {index}', 'priority': 2, 'crm': {}, 'chat': [], 'warnings': [], 'signals': []}
        try:
            if not isinstance(case, dict) or not isinstance(identifier, str) or not identifier.strip():
                raise ValueError('нет корректного идентификатора')
            crm, chat = case['crm'], case.get('chat', [])
            if not isinstance(crm, dict) or not isinstance(chat, list):
                raise ValueError('неверный формат CRM или переписки')
            item.update(crm=crm, chat=chat)
            if identifier in duplicate_ids:
                item['warnings'].append('Повторный идентификатор: проверить все связанные карточки.')
            if any(not isinstance(message, dict) or not isinstance(message.get('author'), str) or not message['author'].strip() or not isinstance(message.get('text'), str) or not message['text'].strip() for message in chat):
                item['warnings'].append('Некорректное сообщение: проверить переписку вручную.')
            kind = case['type']
            if kind == 'onboarding':
                status = crm['documents']
                if status not in ('pending', 'received'):
                    raise ValueError('неизвестный статус документов')
                if status == 'pending':
                    start = date.fromisoformat(crm['first_shift'])
                    item.update(priority=2 if start <= now.date() else 3, action='Уточнить получение и передачу документов у руководителя; проверить комплектность и CRM до выхода.')
                else:
                    item.update(priority=4, action='Документы получены по CRM; остальные условия выхода проверить по регламенту.')
            elif kind == 'offboarding':
                confirmed = crm['manager_confirmed']
                if type(confirmed) is not bool:
                    raise ValueError('подтверждение руководителя должно быть true или false')
                if not confirmed:
                    last_day = date.fromisoformat(crm['last_working_day'])
                    item.update(priority=1 if last_day <= now.date() else 3, action='Получить подтверждение ответственного руководителя и зафиксировать его по регламенту.')
                else:
                    item.update(priority=4, action='Подтверждение есть в CRM; остальные условия увольнения проверить по регламенту.')
            elif kind == 'delivery':
                status = crm['status']
                if status not in ('in_transit', 'accepted'):
                    raise ValueError('неизвестный статус доставки')
                if status == 'accepted':
                    accepted_at = date_time(crm['accepted_at'])
                    if accepted_at > now:
                        raise ValueError('приёмка указана в будущем')
                    item.update(priority=4, action='Приёмка в CRM подтверждена; дополнительных действий по доставке не требуется при отсутствии расхождений.')
                elif date_time(crm['deadline']) <= now:
                    item.update(priority=1, action='Уточнить срок у курьера, предупредить получателя и проверить факт приёмки.')
                else:
                    item.update(priority=3, action='Следить за доставкой и проверить статус к сроку.')
            else:
                raise ValueError('неизвестный тип операции')
            # Structured signals are claims from chat, never CRM updates.
            signals = case.get('signals', [])
            if not isinstance(signals, list):
                raise ValueError('signals должен быть списком')
            for signal in signals:
                if not isinstance(signal, dict) or signal.get('type') != 'delivery_not_before' or kind != 'delivery':
                    raise ValueError('неизвестный или неподходящий сигнал переписки')
                index_ref = signal.get('message_index')
                if type(index_ref) is not int or not 0 <= index_ref < len(chat):
                    raise ValueError('сигнал не связан с сообщением')
                message = chat[index_ref]
                if not isinstance(message, dict) or message.get('author') != 'курьер' or not isinstance(message.get('text'), str) or not message['text'].strip():
                    raise ValueError('источник сигнала курьера нужно проверить вручную')
                not_before = date_time(signal['not_before'])
                deadline = date_time(crm['deadline'])
                item['signals'].append({'type': 'delivery_not_before', 'not_before': signal['not_before'], 'message_index': index_ref})
                if not_before > deadline and crm['status'] == 'in_transit':
                    item['priority'] = 1
                    item['action'] = 'Уточнить у курьера риск срыва срока, предупредить получателя и проверить факт приёмки.'
                    item['warnings'].append('Курьер сообщил время не раньше срока CRM; сообщение требует проверки, это не новый подтверждённый срок.')
                elif not_before > deadline and crm['status'] == 'accepted':
                    item['priority'] = min(item['priority'], 2)
                    item['warnings'].append('Приёмка и сообщение о задержке требуют сверки хронологии.')
            if case.get('conflict_requires_review', False) is True:
                item['priority'] = min(item['priority'], 2)
                item['warnings'].append('Отмечено противоречие источников: сверить вручную.')
            elif case.get('conflict_requires_review', False) is not False:
                raise ValueError('признак противоречия должен быть true или false')
            updated = case.get('crm_updated_at')
            if updated is None:
                item['warnings'].append('Время обновления CRM неизвестно; проверить актуальность.')
            else:
                age = now - date_time(updated)
                if age.total_seconds() < 0:
                    item['warnings'].append('Время обновления CRM находится в будущем: проверить часы и часовой пояс.')
                elif age.total_seconds() > 86400:
                    item['warnings'].append('Данные CRM старше 24 часов; проверить актуальность.')
            if item['warnings']:
                item['priority'] = min(item['priority'], 2)
        except (KeyError, ValueError, TypeError, OverflowError) as exc:
            previous_action = item.get('action')
            action = 'Проверить карточку вручную: неполные или некорректные данные.'
            if item['priority'] == 1 and previous_action:
                action += ' ' + previous_action
            item.update(priority=min(item['priority'], 2), action=action, warnings=item['warnings'] + [f'Ошибка данных: {exc}'])
        results.append(item)
    return sorted(results, key=lambda item: (item['priority'], str(item['id'])))


def crm_readable(crm):
    labels = {'first_shift': 'первый выход', 'documents': 'документы',
              'last_working_day': 'последний рабочий день', 'manager_confirmed': 'подтверждение руководителя',
              'deadline': 'срок доставки', 'status': 'статус доставки', 'accepted_at': 'время приёмки'}
    values = {'pending': 'ожидаются', 'received': 'получены', 'in_transit': 'в пути', 'accepted': 'принято'}
    parts = []
    for key, value in crm.items():
        if type(value) is bool:
            display = 'есть' if value else 'отсутствует'
        elif isinstance(value, str):
            display = values.get(value, value)
        else:
            display = str(value)
        parts.append(f'{labels.get(key, key)}: {display}')
    return '; '.join(parts) or 'нет корректных данных'


def markdown(data, items):
    lines = [f"# Сводка support на {data['as_of']}", '', 'Приоритет: 1 — срочно; 2 — ручная проверка; 3 — в работу; 4 — контроль.', '']
    for item in items:
        lines.extend([f"## {item['id']} · приоритет {item['priority']}", '', f"**CRM:** {crm_readable(item['crm'])}", '', '**Переписка:**'])
        if item['chat']:
            for msg in item['chat']:
                if isinstance(msg, dict):
                    lines.append(f"- {msg.get('author', 'автор не указан')}: {msg.get('text', '')}")
                else:
                    lines.append('- Некорректное сообщение: проверить источник вручную.')
        else:
            lines.append('- Нет сообщений в предоставленных данных.')
        for signal in item['signals']:
            lines.append(f"- Сигнал из сообщения №{signal['message_index'] + 1}: не раньше {signal['not_before']} (проверить по источнику).")
        lines.extend(['', f"**Действие:** {item['action']}"])
        for warning in item['warnings']:
            lines.append(f'**Проверить:** {warning}')
        lines.append('')
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path, help='JSON с данными CRM и переписки')
    parser.add_argument('--format', choices=('markdown', 'json'), default='markdown')
    args = parser.parse_args()
    try:
        data = json.loads(args.input.read_text(encoding='utf-8'))
        items = summarize(data)
        print(markdown(data, items) if args.format == 'markdown' else json.dumps(items, ensure_ascii=False, indent=2))
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        print(f'Не удалось составить сводку: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
