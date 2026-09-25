"""Explicit subscription choices and channel-link addition."""
import unittest
from unittest.mock import patch, Mock
from pathlib import Path
import test_v303 as fixtures
app=fixtures.app
CID='UC'+'a'*22

class ChannelSubscriptionTests(unittest.TestCase):
    setUp=fixtures.DownloadTests.setUp
    job=fixtures.DownloadTests.job

    def post(self,path,payload):
        return self.client.post(path,json=payload,headers={'X-CSRF-Token':'test-token'})

    def test_add_handle_and_restore_suppressed_channel_without_full_sync(self):
        with app.db() as conn:
            conn.execute("INSERT INTO manually_deleted_channels(channel_id,title,deleted_at) VALUES(?,?,?)",(CID,'Channel',app.now_iso()))
        channel={'channel_id':CID,'channel_title_api':'New channel','channel_avatar_url':'https://example.test/image.jpg'}
        with patch.object(app,'load_credentials',return_value=object()),patch.object(app,'google_write_scope_ready',return_value=True),patch.object(app,'youtube_channel_details_from_url',return_value=channel) as resolve,patch.object(app,'youtube_api_request',return_value=Mock(json=lambda:{'items':[]})),patch.object(app,'youtube_subscribe',return_value={'id':'subscription-id'}) as subscribe,patch.object(app,'refresh_subscriptions',side_effect=AssertionError('Full refresh not needed')):
            result=self.post('/api/subscriptions/add',{'url':'@example'})
            self.assertEqual(result.status_code,200,result.json)
            self.assertEqual(resolve.call_args.args[1],'https://www.youtube.com/@example')
            subscribe.assert_not_called()
            self.assertFalse(result.json["subscription"]["youtube_subscribed"])
            self.assertTrue(result.json["subscription"]["local_only"])
        with app.db() as conn:
            row=conn.execute('SELECT * FROM subscriptions WHERE channel_id=?',(CID,)).fetchone()
            self.assertTrue(row['active']);self.assertEqual(row['title'],'New channel')
            self.assertIsNone(conn.execute('SELECT * FROM manually_deleted_channels WHERE channel_id=?',(CID,)).fetchone())

    def test_invalid_links_and_readonly_access_do_not_subscribe(self):
        with patch.object(app,'youtube_subscribe') as subscribe:
            for value in ['https://youtube.com.evil.test/@x','https://example.test/@x','https://youtube.com/watch?v=x','', 'https://user@youtube.com/@x']:
                with patch.object(app,'load_credentials',return_value=object()),patch.object(app,'google_write_scope_ready',return_value=True),patch.object(app,'youtube_channel_details_from_url',return_value={}):
                    self.assertEqual(self.post('/api/subscriptions/add',{'url':value}).status_code,400)
            subscribe.assert_not_called()
        with app.db() as conn:conn.execute("UPDATE users SET role='viewer'")
        with patch.object(app,'youtube_subscribe') as subscribe:
            self.post('/api/subscriptions/add',{'url':'@example'})
            subscribe.assert_not_called()

    def test_removal_choices_keep_or_delete_exact_channel_media(self):
        for mode in ('keep','media','channel','everything'):
            with self.subTest(mode=mode):
                self.setUp()
                self.job('shows/Example channel/episode.mp4')
                single=self.job('Single Downloads/episode.mp4',source='single')
                other=app.DOWNLOAD_ROOT/'shows/Other channel/episode.mp4';other.parent.mkdir(parents=True);other.write_bytes(b'other')
                self.job('queued.mp4',status='queued',exists=False)
                app.set_setting('unsubscribe_policy','remove_delete')
                with patch.object(app,'youtube_unsubscribe') as unsubscribe:
                    response=self.post('/api/subscriptions/UCsample/subscription-choice',{'mode':mode})
                    self.assertEqual(response.status_code,200,response.json)
                    unsubscribe.assert_called_once()
                self.assertEqual((app.DOWNLOAD_ROOT/'shows/Example channel/episode.mp4').exists(),mode in ('keep','channel'))
                self.assertTrue(single.exists());self.assertTrue(other.exists())
                with app.db() as conn:
                    row=conn.execute("SELECT * FROM subscriptions WHERE channel_id='UCsample'").fetchone()
                    self.assertEqual(row is None,mode in ('channel','everything'))
                    if row:self.assertFalse(row['active']);self.assertFalse(row['download_enabled'])
                    self.assertEqual(conn.execute("SELECT status FROM downloads WHERE job_id='queued.mp4'").fetchone()[0],'cancelled')

    def test_busy_invalid_and_failed_remote_actions_keep_files(self):
        media=self.job('shows/Example channel/episode.mp4')
        self.job('working.mp4',status='processing')
        with patch.object(app,'youtube_unsubscribe') as unsubscribe:
            self.assertEqual(self.post('/api/subscriptions/UCsample/subscription-choice',{'mode':'everything'}).status_code,409)
            self.assertEqual(self.post('/api/subscriptions/UCsample/subscription-choice',{'mode':'invalid'}).status_code,400)
            unsubscribe.assert_not_called()
        with patch.object(app,'youtube_unsubscribe',side_effect=RuntimeError('API unavailable')):
            self.assertEqual(self.post('/api/subscriptions/UCsample/subscription-choice',{'mode':'keep'}).status_code,400)
        self.assertTrue(media.exists())
        with app.db() as conn:self.assertTrue(conn.execute("SELECT active FROM subscriptions WHERE channel_id='UCsample'").fetchone()[0])

    def test_existing_youtube_subscription_does_not_insert_again(self):
        channel={'channel_id':CID,'channel_title_api':'Channel','channel_avatar_url':''}
        with patch.object(app,'resolve_subscription_channel',return_value=(object(),channel)),patch.object(app,'youtube_api_request',return_value=Mock(json=lambda:{'items':[{'id':'existing'}]})),patch.object(app,'youtube_subscribe') as subscribe:
            result=self.post('/api/youtube/subscribe',{'channel_id':CID})
            self.assertEqual(result.status_code,200,result.json);self.assertTrue(result.json['already_subscribed'])
            subscribe.assert_not_called()
