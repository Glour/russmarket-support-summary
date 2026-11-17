#!/usr/bin/env python3
"""Локальная сводка из структурированных данных. Внешних зависимостей нет."""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path


def date_time(value):
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError('укажите часовой пояс в дате и времени')
    return parsed


def summarize(data):
    now = date_time(data['as_of'])
    if not isinstance(data['cases'], list):
        raise ValueError('cases должен быть списком')
    results = []
    seen = set()
    for index, case in enumerate(data['cases'], 1):
        identifier = case.get('id', f'строка {index}') if isinstance(case, dict) else f'строка {index}'
        item = {'id': identifier, 'priority': 2, 'crm': {}, 'chat': [], 'warnings': []}
        try:
            if not isinstance(case, dict) or not isinstance(identifier, str) or not identifier.strip():
                raise ValueError('нет корректного идентификатора')
            if identifier in seen:
                raise ValueError('повторный идентификатор')
            seen.add(identifier)
            crm, chat = case['crm'], case.get('chat', [])
            if not isinstance(crm, dict) or not isinstance(chat, list):
                raise ValueError('неверный формат CRM или переписки')
            item.update(crm=crm, chat=chat)
            kind = case['type']
            if kind == 'onboarding':
                status = crm['documents']
                if status not in ('pending', 'received'):
                    raise ValueError('неизвестный статус документов')
                if status == 'pending':
                    start = datetime.fromisoformat(crm['first_shift']).date()
                    item.update(priority=2 if start <= now.date() else 3, action='Уточнить получение и передачу документов у руководителя; проверить комплектность и CRM до выхода.')
                else:
                    item.update(priority=4, action='Документы получены по CRM; остальные условия выхода проверить по регламенту.')
            elif kind == 'offboarding':
                confirmed = crm['manager_confirmed']
                if type(confirmed) is not bool:
                    raise ValueError('подтверждение руководителя должно быть true или false')
                if not confirmed:
                    last_day = datetime.fromisoformat(crm['last_working_day']).date()
                    item.update(priority=1 if last_day <= now.date() else 3, action='Получить подтверждение ответственного руководителя и зафиксировать его по регламенту.')
                else:
                    item.update(priority=4, action='Подтверждение есть в CRM; остальные условия увольнения проверить по регламенту.')
            elif kind == 'delivery':
                status = crm['status']
                if status not in ('in_transit', 'accepted'):
                    raise ValueError('неизвестный статус доставки')
                if status == 'accepted':
                    item.update(priority=4, action='Приёмка в CRM подтверждена; дополнительных действий по доставке не требуется при отсутствии расхождений.')
                elif date_time(crm['deadline']) <= now:
                    item.update(priority=1, action='Уточнить срок у курьера, предупредить получателя и проверить факт приёмки.')
                else:
                    item.update(priority=3, action='Следить за доставкой и проверить статус к сроку.')
            else:
                raise ValueError('неизвестный тип операции')
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
            item.update(priority=2, action='Проверить карточку вручную: неполные или некорректные данные.', warnings=[f'Ошибка данных: {exc}'])
        results.append(item)
    return sorted(results, key=lambda item: (item['priority'], str(item['id'])))


def markdown(data, items):
    lines = [f"# Сводка support на {data['as_of']}", '', 'Приоритет: 1 — срочно; 2 — ручная проверка; 3 — в работу; 4 — контроль.', '']
    for item in items:
        lines.extend([f"## {item['id']} · приоритет {item['priority']}", '', f"**CRM:** {json.dumps(item['crm'], ensure_ascii=False)}", '', '**Переписка:**'])
        if item['chat']:
            for msg in item['chat']:
                if isinstance(msg, dict):
                    lines.append(f"- {msg.get('author', 'автор не указан')}: {msg.get('text', '')}")
                else:
                    lines.append('- Некорректное сообщение: проверить источник вручную.')
        else:
            lines.append('- Нет сообщений в предоставленных данных.')
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
