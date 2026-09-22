"""Isolate unavailable Guide playlists without losing cached uploads."""
import unittest
from unittest.mock import Mock, patch
from datetime import timedelta
import requests
import test_v307 as fixtures
from test_v307 import app, catalogue, NOW, video


class GuideRecoveryTests(unittest.TestCase):
    setUp = fixtures.GuideTests.setUp
    save_channel = fixtures.GuideTests.save_channel
    get = fixtures.GuideTests.get
    job = fixtures.GuideTests.job

    def error(self, reason='playlistNotFound', status=404):
        response = Mock(status_code=status)
        response.json.return_value = {'error': {'errors': [{'reason': reason}]}}
        return requests.HTTPError('secret request URL', response=response)

    def second_channel(self):
        with app.db() as conn:
            conn.execute("INSERT INTO subscriptions(channel_id,title,active,channel_url,first_seen_at) VALUES('UCzhealthy','Healthy channel',1,'https://youtube.com/channel/UCzhealthy',?)", (app.now_iso(),))
        self.save_channel('UCzhealthy')

    def test_missing_playlist_continues_and_cooldown_survives_restart(self):
        self.second_channel()
        self.guide.save_videos([video()])
        calls = []
        def request(creds, path, params):
            calls.append((path, params))
            if params.get('playlistId') == 'UUUCsample':
                raise self.error()
            return {'items': []}
        with patch.object(app, 'load_credentials', return_value=object()), patch.object(self.guide, '_request', side_effect=request):
            self.assertTrue(self.guide.tick())
        with app.db() as conn:
            self.assertEqual(conn.execute("SELECT initialised FROM guide_sync WHERE channel_id='UCzhealthy'").fetchone()[0], 1)
            self.assertEqual(conn.execute('SELECT retry_at FROM guide_runtime').fetchone()[0], '')
        data = self.get()
        self.assertEqual(len(data['coverage']['channel_errors']), 1)
        self.assertIn('playlistNotFound', data['channels'][0]['coverage']['error'])
        self.assertEqual(len(data['channels'][0]['events']), 1)
        self.assertNotIn('secret', str(data))
        restarted = catalogue.UploadGuide(app)
        with patch.object(app, 'load_credentials', return_value=object()), patch.object(restarted, '_request', side_effect=AssertionError('Cooldown ignored')):
            self.assertTrue(restarted.tick())

    def test_retry_refreshes_playlist_id_then_clears_error(self):
        self.guide.request_refresh()
        self.guide._failure(self.error(), 'UCsample')
        def request(creds, path, params):
            if path == 'channels':
                return {'items': [{'id': 'UCsample', 'snippet': {'title': 'Example'}, 'contentDetails': {'relatedPlaylists': {'uploads': 'UUrepaired'}}}]}
            self.assertEqual(params['playlistId'], 'UUrepaired')
            self.assertNotIn('pageToken', params)
            return {'items': []}
        with patch.object(catalogue, 'now', return_value=NOW+timedelta(hours=25)), patch.object(app, 'load_credentials', return_value=object()), patch.object(self.guide, '_request', side_effect=request):
            self.assertTrue(self.guide.tick())
        with app.db() as conn:
            row = conn.execute('SELECT error,retry_at,initialised FROM guide_sync').fetchone()
            self.assertEqual(tuple(row), (None, '', 1))

    def test_global_quota_and_auth_still_stop_all_channels(self):
        self.second_channel()
        for reason, status in [('quotaExceeded', 403), ('authError', 401)]:
            with app.db() as conn:
                conn.execute("UPDATE guide_runtime SET retry_at='',last_error=''")
            with patch.object(app, 'load_credentials', return_value=object()), patch.object(self.guide, '_request', side_effect=self.error(reason, status)) as request:
                self.assertFalse(self.guide.tick())
                self.assertFalse(self.guide.tick())
                self.assertEqual(request.call_count, 1)
            self.assertIn(reason, self.get()['coverage']['error'])

    def test_backfill_failure_does_not_starve_other_channels(self):
        self.second_channel(); self.guide.request_refresh()
        with app.db() as conn:
            conn.execute("UPDATE guide_sync SET initialised=1,history_complete=0,backfill_cursor='page2',refresh_requested=0,channel_refresh_requested=0,recent_checked_at=?", (catalogue.stamp(),))
            conn.execute('UPDATE guide_runtime SET scheduled_at=?', (self.guide.scheduled_boundary(),))
        def request(creds, path, params):
            if params.get('playlistId') == 'UUUCsample':
                raise self.error('playlistItemsNotAccessible', 403)
            return {'items': []}
        with patch.object(app, 'load_credentials', return_value=object()), patch.object(self.guide, '_request', side_effect=request):
            self.assertTrue(self.guide.tick())
        with app.db() as conn:
            self.assertEqual(conn.execute("SELECT history_complete FROM guide_sync WHERE channel_id='UCzhealthy'").fetchone()[0], 1)

    def test_upgrade_unblocks_legacy_playlist_pause_but_preserves_quota(self):
        for reason, cleared in [('playlistNotFound', True), ('quotaExceeded', False)]:
            with app.db() as conn:
                conn.execute('ALTER TABLE guide_sync DROP COLUMN retry_at')
                conn.execute('UPDATE guide_runtime SET last_error=?,retry_at=?', (f'YouTube guide refresh paused ({reason}).', catalogue.stamp(NOW+timedelta(days=1))))
            catalogue.init_guide_db(app.db)
            with app.db() as conn:
                row = conn.execute('SELECT last_error,retry_at FROM guide_runtime').fetchone()
                self.assertEqual(not any(row), cleared)
