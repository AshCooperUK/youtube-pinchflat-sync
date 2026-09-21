"""Independent guide channel visibility and cached browsing."""
import unittest
from unittest.mock import patch
import test_v307 as fixtures
app=fixtures.app

class GuideVisibilityTests(unittest.TestCase):
    setUp=fixtures.GuideTests.setUp
    save_channel=fixtures.GuideTests.save_channel
    get=fixtures.GuideTests.get

    def test_unmonitored_subscriptions_show_and_index_but_hidden_and_inactive_do_not(self):
        with app.db() as conn:
            conn.execute("UPDATE subscriptions SET download_enabled=0 WHERE channel_id='UCsample'")
        with patch.object(app,'youtube_api_request',side_effect=AssertionError('Read used YouTube')):
            self.assertEqual(self.guide.enabled_ids(),['UCsample'])
            self.assertEqual(self.get()['channels'][0]['channel_id'],'UCsample')
        with app.db() as conn:conn.execute("INSERT INTO guide_channel_preferences VALUES('UCsample',0)")
        self.assertEqual(self.guide.enabled_ids(),[])
        self.assertEqual(self.get()['channels'],[])
        with app.db() as conn:
            conn.execute('DELETE FROM guide_channel_preferences')
            conn.execute('UPDATE subscriptions SET active=0')
        self.assertEqual(self.guide.enabled_ids(),[])

    def test_settings_persist_visibility_without_changing_downloads_and_new_channels_default_visible(self):
        payload={'_csrf':'test-token','guide_timezone':'Europe/London','guide_refresh_time':'04:00','guide_history':'year','guide_daily_budget':'500','guide_channels_present':'1','guide_show_thumbnails':'1'}
        response=self.client.post('/settings/guide',data=payload)
        self.assertEqual(response.status_code,302)
        self.assertEqual(self.get()['channels'],[])
        self.assertTrue(self.get()['show_thumbnails'])
        self.assertFalse(self.get()['forecasts']['enabled'])
        with app.db() as conn:
            self.assertEqual(conn.execute('SELECT download_enabled FROM subscriptions').fetchone()[0],1)
            conn.execute("INSERT INTO subscriptions(channel_id,title,channel_url,first_seen_at,active,download_enabled) VALUES('UCnew','New channel','https://youtube.com/channel/UCnew',?,1,0)",(app.now_iso(),))
        self.assertEqual(self.guide.enabled_ids(),['UCnew'])
        payload['guide_channel_ids']=['UCsample','UCnew'];payload['guide_predictions_enabled']='1'
        self.client.post('/settings/guide',data=payload)
        self.assertEqual(len(self.get()['channels']),2)
        self.assertTrue(self.get()['forecasts']['enabled'])

    def test_guide_preferences_require_admin_and_csrf(self):
        self.assertEqual(self.client.post('/settings/guide',data={'guide_channels_present':'1'}).status_code,400)
        with app.db() as conn:conn.execute("UPDATE users SET role='viewer' WHERE id=1")
        self.client.post('/settings/guide',data={'_csrf':'test-token','guide_channels_present':'1'})
        self.assertEqual(self.guide.enabled_ids(),['UCsample'])
