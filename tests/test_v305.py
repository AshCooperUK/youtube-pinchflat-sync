"""Shorts exclusions, explicit import enabling and truthful scan outcomes."""
import copy
import json
from pathlib import Path
import queue
import unittest
from unittest.mock import patch

import test_v303 as fixtures
from downloader_media import MediaYoutubeDL

app = fixtures.app


class SubscriptionTests(unittest.TestCase):
    job = fixtures.DownloadTests.job

    def setUp(self):
        fixtures.DownloadTests.setUp(self)
        patcher = patch.object(app, 'download_queue', queue.Queue())
        patcher.start()
        self.addCleanup(patcher.stop)

    def subscription(self):
        with app.db() as conn:
            return dict(conn.execute("SELECT * FROM subscriptions WHERE channel_id='UCsample'").fetchone())

    def media(self, name, info=None):
        path = app.DOWNLOAD_ROOT / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'fixture-video')
        if info:
            path.with_suffix('.info.json').write_text(json.dumps(info))
        return path

    def test_watch_link_short_is_skipped_before_any_transfer_by_real_ytdlp(self):
        self.job('short-job', status='queued', exists=False)
        info = {'id':'abcdefghijk', 'title':'A Short supplied as a watch URL',
                'media_type':'short', 'duration':175, 'upload_date':'20260920',
                'webpage_url':'https://www.youtube.com/watch?v=abcdefghijk',
                'url':'https://fixture.invalid/video.mp4', 'ext':'mp4',
                'channel_id':'UCsample', 'channel':'Example channel',
                'extractor':'fixture', 'extractor_key':'Fixture'}
        def extract(ydl, url, download=True):
            return ydl.process_ie_result(copy.deepcopy(info), download=download)
        with patch.object(MediaYoutubeDL, 'extract_info', extract), \
                patch.object(MediaYoutubeDL, 'dl', side_effect=AssertionError('Short transferred')) as transfer, \
                patch.object(app, 'prepare_subscription_metadata'):
            app.run_download_job('short-job')
        record = app.download_job_row('short-job')
        self.assertEqual(record['status'], 'skipped', record['error'])
        self.assertEqual(record['failure_code'], 'shorts_excluded')
        self.assertFalse(record['error'])
        transfer.assert_not_called()
        self.assertFalse(list(app.DOWNLOAD_ROOT.rglob('*.vtt')))
        self.assertFalse(list(app.DOWNLOAD_ROOT.rglob('*.mp4')))
        overview = app.pinchflat_download_overview()
        self.assertFalse(overview['active'])
        self.assertEqual(overview['recent'][0]['state'], 'skipped')
        self.assertIn('Shorts are switched off', overview['recent'][0]['status'])

    def test_short_filter_respects_switch_without_rejecting_short_normal_videos(self):
        match = app._v3_profile_ydl_options('720p')['match_filter']
        self.assertIsNone(match({'media_type':'video', 'duration':25, 'width':1920, 'height':1080}))
        self.assertIsNone(match({'id':'abcdefghijk'}, incomplete=True))
        with self.assertRaises(app.SubscriptionMediaExcluded):
            match({'webpage_url':'https://www.youtube.com/watch?v=abcdefghijk',
                   'original_url':'https://www.youtube.com/shorts/abcdefghijk'})
        app.set_setting('downloader_include_shorts', '1')
        self.assertIsNone(app._v3_profile_ydl_options('720p')['match_filter']({'media_type':'short'}))
        app.set_setting('downloader_include_livestreams', '0')
        with self.assertRaises(app.SubscriptionMediaExcluded) as raised:
            app._v3_profile_ydl_options('720p')['match_filter']({'media_type':'livestream', 'live_status':'was_live'})
        self.assertEqual(raised.exception.code, 'livestream_excluded')
        self.assertNotIn('match_filter', app.parse_custom_yt_dlp_options('{"match_filter":null}'))

    def test_skipped_short_stays_excluded_on_scans_then_becomes_eligible_when_enabled(self):
        self.job('excluded', status='skipped', exists=False)
        app.update_download_job('excluded', failure_code='shorts_excluded')
        entry = {'id':'abcdefghijk', 'title':'Known Short', 'published_at':app.now_iso()}
        self.assertFalse(app._v3_queue_entry(self.subscription(), entry))
        self.assertFalse(app._v3_queue_entry(self.subscription(), entry, redownload=True))
        self.assertEqual(app.download_queue.qsize(), 0)
        # The Downloader switches apply to subscriptions, not explicit single downloads.
        _, single_created = app.enqueue_download('https://www.youtube.com/watch?v=abcdefghijk', video_id='abcdefghijk')
        self.assertTrue(single_created)
        app.set_setting('downloader_include_shorts', '1')
        jobs = []
        self.assertTrue(app._v3_queue_entry(self.subscription(), entry, job_ids=jobs))
        self.assertEqual(len(jobs), 1)
        self.assertEqual(app.download_job_row(jobs[0])['status'], 'queued')

    def test_scan_job_count_matches_only_new_eligible_jobs(self):
        with app.db() as conn:
            conn.execute("UPDATE subscriptions SET download_enabled=1,history_mode='today'")
        self.job('excluded', status='skipped', exists=False)
        app.update_download_job('excluded', failure_code='shorts_excluded')
        entries = [{'video_id':vid, 'title':vid, 'video_url':url, 'published_at':app.now_iso()}
                   for vid,url in [('abcdefghijk','https://www.youtube.com/watch?v=abcdefghijk'),
                                   ('bcdefghijkl','https://www.youtube.com/shorts/bcdefghijkl'),
                                   ('cdefghijklm','https://www.youtube.com/watch?v=cdefghijklm')]]
        with patch.object(app, 'youtube_channel_feed', return_value=entries), patch.object(app, 'prepare_subscription_metadata'):
            result = app.v3_scan_all_enabled()
            again = app.v3_scan_all_enabled()
        self.assertEqual(result['queued'], 1)
        self.assertEqual(len(result['job_ids']), 1)
        self.assertEqual(again['queued'], 0)
        self.assertEqual(app.scan_download_outcomes(result)['waiting'], 1)
        self.assertEqual(app.download_queue.qsize(), 1)

    def test_manual_import_enables_new_and_already_imported_channels_keeps_preferences(self):
        self.media('shows/Example channel/Season 2026/video [abcdefghijk].mp4')
        with app.db() as conn:
            conn.execute("UPDATE subscriptions SET history_mode='this_week',media_profile_id='720p'")
        with patch.object(app, 'storage_snapshot'), patch('threading.Thread.start'):
            response = self.client.post('/settings/downloader/library/import', data={'_csrf':'test-token'})
        self.assertEqual(response.status_code, 302)
        sub = self.subscription()
        self.assertEqual(sub['download_enabled'], 1)
        self.assertEqual(sub['source_authorised'], 1)
        self.assertEqual(sub['pinchflat_source_id'], 'UCsample')
        self.assertEqual(sub['history_mode'], 'this_week')
        self.assertEqual(sub['media_profile_id'], '720p')
        with self.client.session_transaction() as session:
            self.assertIn('Enabled 1 matched channel(s)', session['_flashes'][-1][1])
        with app.db() as conn:
            conn.execute("UPDATE subscriptions SET download_enabled=0")
        with patch.object(app, 'storage_snapshot'):
            result = app.reconcile_existing_library(force=True, enable_channels=True)
        self.assertEqual((result['imported'], result['known'], result['enabled']), (0, 1, 1))

    def test_startup_import_and_sidecars_do_not_enable_channels(self):
        self.media('shows/Example channel/Season 2026/video [abcdefghijk].mp4')
        with patch.object(app, 'storage_snapshot'):
            result = app.reconcile_existing_library(force=True)
        self.assertEqual(result['imported'], 1)
        self.assertEqual(self.subscription()['download_enabled'], 0)
        with app.db() as conn:
            conn.execute("DELETE FROM downloads")
        for path in app.DOWNLOAD_ROOT.rglob('*.mp4'):
            path.unlink()
        self.media('shows/Example channel/Season 2026/video.en.vtt')
        self.media('shows/Example channel/fanart.jpg')
        with patch.object(app, 'storage_snapshot'):
            result = app.reconcile_existing_library(force=True, enable_channels=True)
        self.assertEqual((result['scanned'], result['enabled']), (0, 0))

    def test_import_matches_channel_identity_and_avoids_ambiguous_titles(self):
        with app.db() as conn:
            conn.execute("INSERT INTO subscriptions(channel_id,title,channel_url,first_seen_at) VALUES ('UCother','Example channel','https://www.youtube.com/channel/UCother',?)", (app.now_iso(),))
        self.media('shows/Example channel/Season 2026/ambiguous [abcdefghijk].mp4')
        with patch.object(app, 'storage_snapshot'):
            result = app.reconcile_existing_library(force=True, enable_channels=True)
        self.assertEqual(result['enabled'], 0)
        named = self.media('shows/Old channel name/Season 2026/known [bcdefghijkl].mp4')
        (named.parent.parent / 'tvshow.nfo').write_text('<tvshow><uniqueid type="youtube">UCsample</uniqueid></tvshow>')
        with patch.object(app, 'storage_snapshot'):
            result = app.reconcile_existing_library(force=True, enable_channels=True)
        self.assertEqual(result['enabled'], 1)
        self.assertEqual(self.subscription()['download_enabled'], 1)
        with app.db() as conn:
            self.assertEqual(conn.execute("SELECT download_enabled FROM subscriptions WHERE channel_id='UCother'").fetchone()[0], 0)

    def test_import_known_path_matches_saved_channel_folder(self):
        self.job('shows/Saved folder/Season 2026/video.mp4')
        with app.db() as conn:
            conn.execute("UPDATE downloads SET channel_id=NULL")
            conn.execute("UPDATE subscriptions SET download_folder='Saved folder'")
        with patch.object(app, 'storage_snapshot'):
            result = app.reconcile_existing_library(force=True, enable_channels=True)
        self.assertEqual((result['imported'], result['known'], result['enabled']), (0, 1, 1))
        self.assertEqual(app.download_job_row('shows/Saved folder/Season 2026/video.mp4')['channel_id'], 'UCsample')

    def test_sync_reports_finished_and_failed_jobs_and_keeps_errors_visible(self):
        self.job('finished.mp4')
        self.job('failed', status='failed', exists=False)
        app.update_download_job('failed', error='Video stream unavailable')
        with app.db() as conn:
            conn.execute("UPDATE subscriptions SET last_error='Video download failed: unavailable'")
        scan = {'checked':13,'found':20,'queued':2,'errors':0,'job_ids':['finished.mp4','failed']}
        with patch.object(app, 'refresh_subscriptions', return_value={'total':636,'new':0,'removed':0,'policy_errors':0}), \
                patch.object(app, 'pinchflat_health', return_value=True), \
                patch.object(app, 'reconcile_active_source_authority', return_value={'changed':0,'errors':0}), \
                patch.object(app, 'add_pending_sources', return_value={'added':0,'errors':0}), \
                patch.object(app, 'v3_scan_all_enabled', return_value=scan), \
                patch.object(app, 'sync_emby_download_playlist', return_value={'queued':0}):
            result = app.sync_once()
        self.assertEqual(result['status'], 'completed_with_errors')
        self.assertIn('Added 2 download job(s) during this scan', result['message'])
        self.assertIn('1 completed, 1 failed', result['message'])
        self.assertEqual(result['errors'], 1)
        self.assertIn('Video download failed', self.subscription()['last_error'])
        overview = self.client.get('/api/pinchflat/download-overview').get_json()
        self.assertEqual(overview['summary']['waiting'], 0)
        self.assertEqual({item['state'] for item in overview['recent']}, {'completed','failed'})
        self.assertEqual(next(item for item in overview['recent'] if item['state']=='failed')['error'], 'Video stream unavailable')


if __name__ == '__main__':
    unittest.main()
