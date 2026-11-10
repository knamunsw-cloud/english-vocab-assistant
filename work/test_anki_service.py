import sys
from pathlib import Path
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import anki_service as service


class AnkiServiceTests(unittest.TestCase):
    def setUp(self):
        self.words = [{"word": "test", "meaning": "kiểm tra < & >",
                       "ipa": "/test/", "part_of_speech": "Noun"}]

    @patch('anki_service.call_anki')
    def test_success_and_html(self, api):
        api.side_effect = [['Front', 'Back'], 1, [123]]
        report = service.export_to_anki_via_api(self.words)
        self.assertTrue(report['ok'])
        self.assertEqual(report['added'], 1)
        action, params = api.call_args.args
        self.assertEqual(action, 'addNotes')
        self.assertIn('&lt; &amp; &gt;', params['notes'][0]['fields']['Back'])
        self.assertFalse(params['notes'][0]['options']['allowDuplicate'])

    @patch('anki_service.call_anki', side_effect=RuntimeError('Anki chưa mở'))
    def test_connection_failure_returned(self, api):
        report = service.export_to_anki_via_api(self.words)
        self.assertFalse(report['ok'])
        self.assertEqual(report['error'], 'Anki chưa mở')

    @patch('anki_service.call_anki')
    def test_partial_success(self, api):
        api.side_effect = [['Front', 'Back'], 1, [123, None]]
        report = service.export_to_anki_via_api(self.words * 2)
        self.assertFalse(report['ok'])
        self.assertEqual(report['added'], 1)
        self.assertEqual(report['not_added'], ['test'])

    @patch('anki_service.call_anki')
    def test_localized_fields(self, api):
        api.side_effect = [['Mặt trước', 'Mặt sau'], 1, [123]]
        with patch.object(service, 'FRONT_FIELD', 'Mặt trước'), patch.object(service, 'BACK_FIELD', 'Mặt sau'):
            report = service.export_to_anki_via_api(self.words)
        self.assertTrue(report['ok'])
        self.assertIn('Mặt trước', api.call_args.args[1]['notes'][0]['fields'])

    @patch('anki_service.call_anki')
    def test_invalid_data_does_not_write(self, api):
        report = service.export_to_anki_via_api([{'word': 'test'}])
        self.assertFalse(report['ok'])
        api.assert_not_called()


if __name__ == '__main__':
    unittest.main()
