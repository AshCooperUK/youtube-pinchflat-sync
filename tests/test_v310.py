"""Guide/provider fixes, source NFOs, scan dispatch and real Shorts membership."""
import copy
from datetime import datetime, timezone
import functools
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import queue
import shutil
import subprocess
import threading
import unittest
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET

import test_v303 as fixtures
from downloader_media import MediaYoutubeDL
from source_metadata import normalise_source_info, metadata_json

app = fixtures.app
BBC = {'id': 'm002test', 'extractor': 'bbc.co.uk', 'extractor_key': 'BBCCoUk',
       'title': 'Example Programme, Series 1, Episode 2',
       'description': 'An episode description supplied by the broadcaster.',
       'webpage_url': 'https://www.bbc.co.uk/iplayer/episode/m002test/example-programme',
       'duration': 3534, 'release_timestamp': 1758398400,
       'thumbnail': 'https://example.test/episode.jpg'}


class SourceTests(unittest.TestCase):
    job = fixtures.DownloadTests.job

    def setUp(self):
        fixtures.DownloadTests.setUp(self)
        patcher = patch.object(app, 'download_queue', queue.Queue())
        patcher.start(); self.addCleanup(patcher.stop)

    def external_job(self, info=None, name='Single Downloads/Unknown Channel/old.mp4'):
        info = info or BBC
        path = self.job(name, source='single', video_id='media:bbccouk:m002test')
        path.with_suffix('.info.json').write_text(json.dumps(info))
        with app.db() as conn:
            conn.execute("UPDATE downloads SET job_id='external',youtube_url=?,title=?,channel_title=NULL,channel_id=NULL WHERE job_id=?",
                         (BBC['webpage_url'], info['title'], name))
        return path

    def test_bbc_metadata_repair_moves_media_and_sidecars_preserves_user_fields_and_refreshes(self):
        old = self.external_job()
        old.with_suffix('.nfo').write_text('<movie><title>YouTube</title><playcount>3</playcount><userrating>8</userrating></movie>')
        old.with_suffix('.en.vtt').write_text('WEBVTT')
        before = old.read_bytes()
        with patch.object(app, 'emby_configured', return_value=True), patch.object(app, 'emby_refresh_download_library') as refresh, \
                patch.object(app, 'youtube_api_request', side_effect=AssertionError('Repair queried YouTube')):
            result = app.repair_source_downloads()
            self.assertEqual(result, {'updated': 1, 'errors': 0})
            self.assertEqual(app.repair_source_downloads(), {'updated': 0, 'errors': 0})
        refresh.assert_called_once_with('Single Downloads', 'One-time metadata repair')
        row = app.download_job_row('external')
        target = Path(row['output_path'])
        self.assertEqual(target.parent.name, 'Season 1')
        self.assertEqual(target.parent.parent.name, 'Example Programme')
        self.assertTrue(target.name.startswith('S01E02 - '))
        self.assertEqual(target.read_bytes(), before)
        self.assertFalse(old.exists())
        self.assertEqual(target.with_suffix('.en.vtt').read_text(), 'WEBVTT')
        nfo = ET.parse(target.with_suffix('.nfo')).getroot()
        self.assertEqual(nfo.tag, 'episodedetails')
        self.assertEqual(nfo.findtext('title'), 'Episode 2')
        self.assertEqual(nfo.findtext('showtitle'), 'Example Programme')
        self.assertEqual((nfo.findtext('season'), nfo.findtext('episode')), ('1', '2'))
        self.assertEqual(nfo.findtext('plot'), BBC['description'])
        self.assertEqual(nfo.findtext('runtime'), '59')
        self.assertEqual(nfo.findtext('playcount'), '3')
        self.assertEqual(nfo.findtext('userrating'), '8')
        self.assertEqual(nfo.findtext('aired'), '2025-09-20')
        self.assertEqual(ET.parse(target.parent.parent/'tvshow.nfo').findtext('title'), 'Example Programme')
        data = self.client.get('/downloads/external/metadata').json['item']
        self.assertEqual(data['description'], BBC['description'])
        self.assertEqual(data['provider'], 'BBC iPlayer')
        self.assertEqual(data['duration'], '58:54')
        discovered = self.client.get('/api/discover?kind=downloaded').json['results'][0]
        self.assertEqual(discovered['channel_title'], 'Example Programme')
        self.assertEqual(discovered['description'], BBC['description'])
        self.assertTrue(discovered['is_external'])
        self.assertEqual(app.pinchflat_download_overview()['latest_download']['series'], 'Example Programme')

    def test_metadata_respects_custom_paths_and_nfo_setting_and_refuses_outside_root(self):
        old = self.external_job()
        app.set_setting('single_download_output_template', 'Custom/%(title)s.%(ext)s')
        app.set_setting('single_download_write_nfo', '0')
        app.repair_source_downloads()
        self.assertEqual(app.download_job_row('external')['output_path'], str(old))
        self.assertFalse(list(app.DOWNLOAD_ROOT.rglob('*.nfo')))
        self.assertNotEqual(app.app.test_client().get('/downloads/external/metadata').status_code, 200)
        outside = Path(self.tmp.name)/'private.mp4'; outside.write_bytes(b'private')
        app.update_download_job('external', output_path=str(outside))
        self.assertEqual(self.client.get('/downloads/external/metadata').status_code, 404)

    def test_repair_collision_leaves_original_and_destination_untouched(self):
        old = self.external_job()
        options = {'quiet': True, '_ytsd_single_series_root': str(app.DOWNLOAD_ROOT/'Single Downloads'),
                   '_ytsd_source_key': app.hashlib.sha256(BBC['webpage_url'].encode()).hexdigest()[:12]}
        with MediaYoutubeDL(options, output_root=app.DOWNLOAD_ROOT) as ydl:
            target = Path(ydl.prepare_filename({**BBC, 'ext': 'mp4'}))
        target.parent.mkdir(parents=True); target.write_bytes(b'existing')
        self.assertEqual(app.repair_source_downloads()['errors'], 1)
        self.assertEqual(target.read_bytes(), b'existing')
        self.assertEqual(old.read_bytes(), b'fixture-video')
        self.assertEqual(app.download_job_row('external')['output_path'], str(old))

    def test_provider_fields_are_curated_and_generic_title_is_not_guessed_as_tv(self):
        data = normalise_source_info({**BBC, 'http_headers': {'Authorization': 'secret'}, 'formats': [{'url': 'secret'}]})
        self.assertEqual(data['series'], 'Example Programme')
        self.assertNotIn('secret', metadata_json(data))
        self.assertFalse(normalise_source_info({'title': BBC['title'], 'extractor_key': 'Generic'}).get('series'))

    def test_rescan_does_not_attach_external_media_to_youtube_by_title_or_id_length(self):
        info = {**BBC, 'id':'abcdefghijk', 'extractor_key':'Generic', 'channel':'Example channel'}
        self.external_job(info=info)
        unknown = app.DOWNLOAD_ROOT/'Loose clip [bcdefghijkl].mp4'
        unknown.write_bytes(b'provider-video')
        unknown.with_suffix('.info.json').write_text(json.dumps({**info, 'id':'bcdefghijkl'}))
        result = app.reconcile_existing_library(force=True, enable_channels=True)
        self.assertEqual(result['imported'], 0)
        self.assertEqual(result['enabled'], 0)
        self.assertFalse(app.download_job_row('external')['channel_id'])
        with app.db() as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM downloads').fetchone()[0], 1)

    @unittest.skipUnless(shutil.which('ffmpeg'), 'FFmpeg is needed for real transfer coverage')
    def test_real_episode_transfer_writes_provider_nfo_and_immediately_notifies_emby(self):
        root = Path(self.tmp.name)/'http'; root.mkdir()
        source = root/'episode.mp4'
        subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-f', 'lavfi', '-i',
                        'color=c=blue:s=160x90:d=0.2', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(source)], check=True)
        class Quiet(SimpleHTTPRequestHandler):
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Quiet, directory=str(root)))
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        def extract(ydl, url, download=True):
            info = {**BBC, 'thumbnail': None, 'url': f'http://127.0.0.1:{server.server_port}/episode.mp4', 'ext': 'mp4'}
            return ydl.process_ie_result(copy.deepcopy(info), download=download)
        try:
            job, _ = app.enqueue_download(BBC['webpage_url'])
            with patch.object(MediaYoutubeDL, 'extract_info', extract), patch.object(app, 'emby_configured', return_value=True), \
                    patch.object(app, 'emby_refresh_download_library') as refresh, \
                    patch.object(app, 'storage_snapshot', side_effect=AssertionError('Slow inventory delayed refresh')):
                app.run_download_job(job)
                row = app.download_job_row(job)
                self.assertEqual(row['status'], 'completed', row['error'])
                refresh.assert_called_once_with('Single Downloads', 'One-time Download')
            record = app.download_job_row(job)
            self.assertEqual(record['status'], 'completed', record['error'])
            path = Path(record['output_path'])
            self.assertEqual(path.parent.name, 'Season 1')
            self.assertTrue(path.with_suffix('.info.json').is_file())
            self.assertEqual(ET.parse(path.with_suffix('.nfo')).findtext('showtitle'), 'Example Programme')
            self.assertIn(BBC['description'], record['metadata_json'])
        finally:
            server.shutdown(); server.server_close(); thread.join(5)

    def test_emby_separate_single_library_and_parent_mount_selection(self):
        folders = [{'Name': 'Main media', 'ItemId': 'main', 'Locations': ['/emby/YouTube']},
                   {'Name': 'One-time media', 'ItemId': 'single', 'Locations': ['/emby/YouTube/Single Downloads']}]
        with patch.object(app, 'emby_configured', return_value=True), patch.object(app, '_download_host_mount_source', return_value='/host/YouTube'), \
                patch.object(app, '_emby_container_mount_mappings', return_value=[{'source':'/host/YouTube','destination':'/emby/YouTube'}]), \
                patch.object(app, 'emby_virtual_folders', return_value=folders), \
                patch.object(app, 'emby_detect_youtube_library', side_effect=AssertionError('Incorrect fallback')):
            self.assertEqual(app.emby_detect_download_library('Single Downloads')['item_id'], 'single')
            self.assertEqual(app.emby_detect_download_library('Single Downloads/Example Programme')['item_id'], 'single')
        with patch.object(app, 'emby_configured', return_value=True), patch.object(app, '_download_host_mount_source', return_value=''), \
                patch.object(app, '_emby_container_mount_mappings', return_value=[]), patch.object(app, 'emby_virtual_folders', return_value=folders), \
                patch.object(app, 'emby_detect_youtube_library', side_effect=AssertionError('Exact separate library ignored')):
            self.assertEqual(app.emby_detect_download_library('Single Downloads')['item_id'], 'single')


class ScanTests(unittest.TestCase):
    job = fixtures.DownloadTests.job

    def setUp(self):
        fixtures.DownloadTests.setUp(self)
        for name in ('download_queue', 'scan_queue'):
            patcher = patch.object(app, name, queue.Queue()); patcher.start(); self.addCleanup(patcher.stop)
        with app.db() as conn:
            conn.execute("UPDATE subscriptions SET active=1,download_enabled=1,source_authorised=1,pinchflat_added=1,pinchflat_source_id='UCsample',history_mode='this_month'")

    def test_force_scan_checks_feed_first_queues_regular_and_excludes_watch_url_short(self):
        entries = [{'video_id':vid, 'title':title, 'video_url':'https://www.youtube.com/watch?v='+vid, 'published_at':app.now_iso()}
                   for vid,title in [('abcdefghijk','Normal 25 second video'), ('bcdefghijkl','A YouTube Short')]]
        calls = []
        def tab(channel, tab, limit=50):
            calls.append((tab,limit))
            if limit == 500:
                self.assertEqual(app.download_queue.qsize(), 1, 'Recent video was not dispatched before deep history')
                return []
            return [{'id':'abcdefghijk','media_type':'video','duration':25}] if tab == 'videos' else [{'id':'bcdefghijkl','media_type':'short'}] if tab == 'shorts' else []
        with patch.object(app, 'youtube_channel_feed', return_value=entries), patch.object(app, '_v3_channel_tab', side_effect=tab), \
                patch.object(app, 'prepare_subscription_metadata', side_effect=AssertionError('Artwork blocked scanning')):
            result = app.v3_scan_subscription('UCsample', deep=True)
        self.assertEqual((result['queued'], result['excluded']), (1, 1))
        row = app.download_job_row(app.download_queue.get_nowait())
        self.assertEqual(row['video_id'], 'abcdefghijk')
        self.assertEqual(row['status'], 'queued')
        log = self.client.get('/api/activity').json['activity']
        short = next(item for item in log if item['video_id'] == 'bcdefghijkl')
        self.assertIn('Shorts are switched off', short['message'])
        self.assertTrue(short['thumbnail_url'])

    def test_force_endpoint_dispatches_scan_and_reports_suppression(self):
        response = self.client.post('/api/subscriptions/UCsample/source-action', json={'action':'force_scan'}, headers={'X-CSRF-Token':'test-token'})
        self.assertEqual(response.status_code, 200, response.json)
        scan_id = app.scan_queue.get_nowait()
        with app.db() as conn:
            self.assertEqual(conn.execute('SELECT status FROM subscription_scan_jobs WHERE id=?',(scan_id,)).fetchone()['status'], 'queued')
        entry = {'video_id':'abcdefghijk','media_type':'video','title':'An eligible upload', 'published_at':app.now_iso()}
        with patch.object(app, 'youtube_channel_feed', return_value=[entry]), patch.object(app, '_v3_channel_tab', return_value=[]):
            app.run_subscription_scan_job(scan_id)
            app.run_subscription_scan_job(scan_id)  # Duplicate delivery does not rescan.
        self.assertEqual(app.download_queue.qsize(), 1)
        with app.db() as conn:
            self.assertEqual(conn.execute('SELECT status FROM subscription_scan_jobs WHERE id=?',(scan_id,)).fetchone()['status'], 'completed')
        app.set_setting('pinchflat_task_block_enabled','1')
        response = self.client.post('/api/subscriptions/UCsample/source-action', json={'action':'force_scan'}, headers={'X-CSRF-Token':'test-token'})
        self.assertEqual(response.status_code, 400)
        self.assertIn('suppressed', response.json['error'])

    def test_worker_checks_real_tab_membership_before_transfer_and_unknown_is_not_downloaded(self):
        app._v3_record_video_types('UCsample', [{'id':'abcdefghijk'}], 'short')
        match = app._v3_profile_ydl_options('720p')['match_filter']
        info = {'id':'abcdefghijk','channel_id':'UCsample','extractor_key':'Youtube', 'webpage_url':'https://www.youtube.com/watch?v=abcdefghijk'}
        with patch.object(app, '_v3_channel_tab', side_effect=AssertionError('Cached type used network')):
            with self.assertRaises(app.SubscriptionMediaExcluded) as error:
                match(info)
        self.assertEqual(error.exception.code, 'shorts_excluded')
        with patch.object(app, '_v3_channel_tab', return_value=[]):
            with self.assertRaises(app.SubscriptionMediaExcluded) as error:
                match({**info,'id':'bcdefghijkl'})
        self.assertEqual(error.exception.code, 'media_type_unverified')
        app._v3_record_video_types('UCsample', [{'id':'cdefghijklm'}], 'video')
        self.assertIsNone(match({**info,'id':'cdefghijklm','duration':25}))

    def test_real_ytdlp_worker_blocks_cached_short_without_explicit_short_flag(self):
        app.set_setting('downloader_sponsorblock_behaviour', 'off')
        self.job('cached-short', status='queued', exists=False)
        app._v3_record_video_types('UCsample', [{'id':'abcdefghijk'}], 'short')
        info = {'id':'abcdefghijk', 'title':'Watch URL without a Shorts flag',
                'channel_id':'UCsample', 'extractor':'youtube', 'extractor_key':'Youtube',
                'webpage_url':'https://www.youtube.com/watch?v=abcdefghijk',
                'url':'https://fixture.invalid/short.mp4', 'ext':'mp4', 'duration':175}
        def extract(ydl, url, download=True):
            return ydl.process_ie_result(copy.deepcopy(info), download=download)
        with patch.object(MediaYoutubeDL, 'extract_info', extract), \
                patch.object(MediaYoutubeDL, 'dl', side_effect=AssertionError('Short was transferred')) as transfer, \
                patch.object(app, 'prepare_subscription_metadata'):
            app.run_download_job('cached-short')
        self.assertEqual(app.download_job_row('cached-short')['failure_code'], 'shorts_excluded')
        transfer.assert_not_called()
        self.assertFalse(list(app.DOWNLOAD_ROOT.rglob('*.mp4')))
        self.assertIsNone(app.pinchflat_download_overview()['latest_download'])

    def test_cutoff_and_publication_use_same_configured_timezone(self):
        app.set_setting('guide_timezone','Europe/London')
        clock = datetime(2026,9,20,23,30,tzinfo=timezone.utc)
        with patch.object(app, 'datetime', wraps=datetime) as times:
            times.now.side_effect = lambda tz=None: clock.astimezone(tz)
            self.assertEqual(app.resolve_history_cutoff(mode='today'), '2026-09-21')
        self.assertEqual(app._v3_parse_entry_date({'published_at':'2026-09-20T23:30:00Z'}).isoformat(), '2026-09-21')


if __name__ == '__main__':
    unittest.main()
