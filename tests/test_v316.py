"""Local channel independence and persistent Diagnostics error paging."""
import unittest
from unittest.mock import patch
import test_v303 as fixtures
app = fixtures.app

class DiagnosticsTests(unittest.TestCase):
    setUp = fixtures.DownloadTests.setUp
    job = fixtures.DownloadTests.job

    def test_persistent_errors_and_older_history_are_accessible(self):
        self.job('failed.mp4',status='failed',exists=False)
        with app.db() as conn:
            conn.execute("UPDATE subscriptions SET last_error='Channel scan failed' WHERE channel_id='UCsample'")
            conn.execute("UPDATE downloads SET error='Download failed'")
        for i in range(65):
            app.log_activity('test','Failure '+str(i),'Error details','error','UCsample')
        first=self.client.get('/api/activity?filter=errors').json
        second=self.client.get('/api/activity?filter=errors&offset=50').json
        self.assertTrue(first['ok']);self.assertTrue(first['has_more'])
        self.assertEqual(first['total'],67)
        rows=first['activity']+second['activity']
        self.assertEqual(len(rows),67)
        self.assertTrue(any(row['title']=='Failed download' and row['video_id']=='abcdefghijk' for row in rows))
        self.assertTrue(any(row['message']=='Channel scan failed' for row in rows))
        self.assertEqual(self.client.get('/api/activity?offset=invalid').status_code,400)

    def test_local_channel_survives_remote_refresh(self):
        with app.db() as conn:
            conn.execute("UPDATE subscriptions SET local_only=1,active=1,download_enabled=1 WHERE channel_id='UCsample'")
        with patch.object(app,'load_credentials',return_value=object()),patch.object(app,'youtube_subscriptions',return_value=[]):
            app.refresh_subscriptions()
        with app.app.test_request_context('/'):
            sub=app.subscription_ajax_payload('UCsample')
        self.assertTrue(sub['active']);self.assertTrue(sub['download_enabled'])
        self.assertFalse(sub['youtube_subscribed'])

    def test_local_add_accepts_read_only_and_enables_scan(self):
        channel={'channel_id':'UC'+'b'*22,'channel_title_api':'Local channel','channel_avatar_url':''}
        with patch.object(app,'load_credentials',return_value=object()),patch.object(app,'google_write_scope_ready',return_value=False),patch.object(app,'youtube_channel_details_from_url',return_value=channel),patch.object(app,'youtube_subscribe') as remote,patch.object(app,'apply_subscription_source_authority') as scan:
            response=self.client.post('/api/subscriptions/add',json={'url':'@local'},headers={'X-CSRF-Token':'test-token'})
            self.assertEqual(response.status_code,200,response.json)
            self.assertTrue(response.json['subscription']['download_enabled'])
            self.assertFalse(response.json['subscription']['youtube_subscribed'])
            remote.assert_not_called();scan.assert_called_once()

    def test_legacy_errors_settings_are_removed(self):
        app.set_setting('page_show_summary_errors','1')
        app.set_setting('page_summary_order','google,errors,downloads')
        app.init_v3_db()
        with app.db() as conn:
            self.assertIsNone(conn.execute("SELECT value FROM settings WHERE key='page_show_summary_errors'").fetchone())
            self.assertEqual(conn.execute("SELECT value FROM settings WHERE key='page_summary_order'").fetchone()[0],'google,downloads')
