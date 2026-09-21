"""Automation migration and live scheduler regression checks."""
from pathlib import Path
import unittest
from unittest.mock import patch
import test_v303 as fixtures
app = fixtures.app

class AutomationTests(unittest.TestCase):
    setUp = fixtures.DownloadTests.setUp

    def test_scan_schedule_routes_preserve_intervals_and_return_to_automation(self):
        for route in ['/settings/automation/scan-schedule', '/settings/downloader/scan-schedule', '/settings/pinchflat/force-index']:
            response = self.client.post(route, data={'_csrf': 'test-token', 'pinchflat_force_index_favourite_minutes': '30', 'pinchflat_force_index_nonfavourite_minutes': '180'})
            self.assertEqual(response.status_code, 302)
            self.assertTrue(response.location.endswith('#automation'))
            self.assertEqual(app.current_pinchflat_force_index_interval(True), 30)
            self.assertEqual(app.current_pinchflat_force_index_interval(False), 180)

    def test_saved_interval_reschedules_actual_registered_native_job(self):
        self.assertIsNotNone(app.scheduler.get_job('native-downloader-sync'))
        app.set_setting('pinchflat_sync_interval_minutes', '120')
        with patch.object(app.scheduler, 'reschedule_job', wraps=app.scheduler.reschedule_job) as reschedule:
            app.reschedule_sync_job()
        reschedule.assert_any_call('native-downloader-sync', trigger='interval', minutes=120)
        self.assertEqual(app.scheduler.get_job('native-downloader-sync').trigger.interval.total_seconds(), 7200)

    def test_schedule_form_is_only_in_automation_and_not_nested(self):
        from bs4 import BeautifulSoup
        source = (Path(app.__file__).parent/'templates/index.html').read_text()
        soup = BeautifulSoup(source, 'html.parser')
        forms = soup.select('form[action="/settings/automation/scan-schedule"]')
        self.assertEqual(len(forms), 1)
        form = forms[0]
        self.assertEqual(form.find_parent('section')['data-panel'], 'automation')
        self.assertIsNone(form.find_parent('form'))
        self.assertEqual(len(form.select('select')), 2)
        self.assertNotIn('pinchflat-source-sync', Path(app.__file__).read_text())
