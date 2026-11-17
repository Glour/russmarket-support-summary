import copy
import json
import unittest
from pathlib import Path
from solution import summarize, markdown

EXAMPLE = json.loads((Path(__file__).parent / 'example.json').read_text())


class SummaryTest(unittest.TestCase):
    def test_four_cases_and_priority(self):
        out = summarize(EXAMPLE)
        self.assertEqual([x['id'] for x in out], ['П-08', 'С-24', 'С-17', 'П-09'])
        self.assertEqual([x['priority'] for x in out], [1, 1, 3, 4])
        self.assertFalse(out[1]['crm']['manager_confirmed'])
        self.assertEqual(out[2]['crm']['documents'], 'pending')
        self.assertIn('Переписка', markdown(EXAMPLE, out))

    def test_deadline_and_timezones(self):
        data = copy.deepcopy(EXAMPLE)
        data['cases'][2].pop('signals')
        data['as_of'] = '2026-11-16T06:59:00+00:00'
        self.assertEqual(next(x for x in summarize(data) if x['id'] == 'П-08')['priority'], 3)
        data['as_of'] = '2026-11-16T07:00:00+00:00'
        self.assertEqual(next(x for x in summarize(data) if x['id'] == 'П-08')['priority'], 1)

    def test_contradiction_and_stale_data_are_visible(self):
        data = copy.deepcopy(EXAMPLE)
        data['cases'][3]['conflict_requires_review'] = True
        self.assertEqual(next(x for x in summarize(data) if x['id'] == 'П-09')['priority'], 2)
        data['cases'][3].pop('conflict_requires_review')
        data['cases'][3]['crm_updated_at'] = '2026-11-14T09:00:00+03:00'
        item = next(x for x in summarize(data) if x['id'] == 'П-09')
        self.assertEqual(item['priority'], 2)
        self.assertIn('старше', item['warnings'][0])

    def test_chat_does_not_confirm_crm(self):
        data = copy.deepcopy(EXAMPLE)
        data['cases'][1]['chat'][0]['text'] = 'Руководитель подтвердил увольнение'
        item = next(x for x in summarize(data) if x['id'] == 'С-24')
        self.assertEqual(item['priority'], 1)
        self.assertFalse(item['crm']['manager_confirmed'])

    def test_bad_case_does_not_hide_other_cases(self):
        data = copy.deepcopy(EXAMPLE)
        data['cases'][0]['crm']['documents'] = 'unrecognized'
        data['cases'].append({'id': 'broken', 'type': 'delivery', 'crm': {'status': 'in_transit'}, 'chat': []})
        out = summarize(data)
        self.assertEqual(len(out), 5)
        self.assertEqual(next(x for x in out if x['id'] == 'С-17')['priority'], 2)
        self.assertIn('Ошибка данных', next(x for x in out if x['id'] == 'broken')['warnings'][0])

    def test_missing_and_future_updates(self):
        data = copy.deepcopy(EXAMPLE)
        del data['cases'][3]['crm_updated_at']
        self.assertEqual(next(x for x in summarize(data) if x['id'] == 'П-09')['priority'], 2)
        data['cases'][3]['crm_updated_at'] = '2026-11-17T10:00:00+03:00'
        self.assertIn('будущем', next(x for x in summarize(data) if x['id'] == 'П-09')['warnings'][0])

    def test_duplicate_and_boolean_validation(self):
        data = copy.deepcopy(EXAMPLE)
        data['cases'].append(copy.deepcopy(data['cases'][0]))
        data['cases'][1]['crm']['manager_confirmed'] = 'false'
        out = summarize(data)
        self.assertEqual(len(out), 5)
        self.assertEqual(next(x for x in out if x['id'] == 'С-24')['priority'], 2)
        self.assertTrue(any('повторный' in str(x['warnings']) for x in out))

    def test_chat_delay_detected_before_deadline(self):
        data = copy.deepcopy(EXAMPLE)
        data['as_of'] = '2026-11-16T09:59:00+03:00'
        item = next(x for x in summarize(data) if x['id'] == 'П-08')
        self.assertEqual(item['priority'], 1)
        self.assertIn('не новый подтверждённый срок', item['warnings'][0])
        self.assertEqual(item['signals'][0]['message_index'], 0)

    def test_invalid_signal_does_not_hide_urgent_case(self):
        data = copy.deepcopy(EXAMPLE)
        data['cases'][2]['signals'][0]['message_index'] = 8
        item = next(x for x in summarize(data) if x['id'] == 'П-08')
        self.assertEqual(item['priority'], 1)
        self.assertIn('не связан', item['warnings'][0])

    def test_incomplete_or_future_receipt_needs_review(self):
        for timestamp in (None, '2026-11-16T11:00:00+03:00'):
            data = copy.deepcopy(EXAMPLE)
            if timestamp is None:
                del data['cases'][3]['crm']['accepted_at']
            else:
                data['cases'][3]['crm']['accepted_at'] = timestamp
            item = next(x for x in summarize(data) if x['id'] == 'П-09')
            self.assertEqual(item['priority'], 2)
            self.assertIn('Ошибка данных', item['warnings'][0])

    def test_missing_case_id_requires_review(self):
        data = copy.deepcopy(EXAMPLE)
        del data['cases'][3]['id']
        self.assertEqual(next(x for x in summarize(data) if x['id'] == 'строка 4')['priority'], 2)

    def test_naive_clock_rejected(self):
        data = copy.deepcopy(EXAMPLE)
        data['as_of'] = '2026-11-16T10:00:00'
        with self.assertRaises(ValueError):
            summarize(data)


if __name__ == '__main__':
    unittest.main()
