"""v3.0.4: optional subtitles, accurate phases and portable channel folders."""
from pathlib import Path
import copy
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import shutil
import subprocess
import threading
import unittest
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET

from PIL import Image

import test_v303 as fixtures
from downloader_media import MediaYoutubeDL, safe_media_component

app = fixtures.app


class MediaTests(unittest.TestCase):
    setUp = fixtures.DownloadTests.setUp
    job = fixtures.DownloadTests.job

    def test_subtitle_transfer_never_claims_video_processing_or_replaces_identity(self):
        self.job('test.mp4', status='queued')
        hook = app._download_progress_hook('test.mp4', 85)
        for status in ('downloading', 'finished'):
            hook({'status': status, 'filename': 'Example.en.vtt', 'total_bytes': 120,
                  'downloaded_bytes': 120, 'info_dict': {'ext': 'vtt'}})
            row = app.download_job_row('test.mp4')
            self.assertEqual(row['status'], 'downloading')
            self.assertEqual(row['progress'], 0)
            self.assertEqual(row['title'], 'test.mp4')
            self.assertNotIn('FFmpeg', row['phase'])
            self.assertFalse(app.pinchflat_download_overview()['latest_download'])
        hook({'status': 'finished', 'filename': 'Example.f137.mp4', 'info_dict': {'id': 'abcdefghijk'}})
        self.assertEqual(app.download_job_row('test.mp4')['status'], 'downloading')
        app._download_postprocessor_hook('test.mp4', 85)({'status': 'started', 'postprocessor': 'Merger'})
        self.assertEqual(app.pinchflat_download_overview()['active'][0]['status'], 'FFmpeg · Merger')

    def test_subtitle_failure_is_optional_and_does_not_hide_media_errors(self):
        notices = []
        opts = {'quiet': True, 'no_warnings': True, 'writesubtitles': True,
                'outtmpl': str(app.DOWNLOAD_ROOT / '%(title)s [%(id)s].%(ext)s'), 'ignoreerrors': False}
        info = {'id': 'abcdefghijk', 'title': 'Caption fixture', 'ext': 'mp4',
                'requested_subtitles': {'en-GB': {'ext': 'vtt', 'url': 'https://example.test/good'},
                                        'en': {'ext': 'vtt', 'url': 'https://example.test/fail'}}}
        with MediaYoutubeDL(opts, output_root=app.DOWNLOAD_ROOT, sidecar_notice=notices.append) as ydl:
            def download(path, sub, subtitle=False):
                if sub['url'].endswith('/fail'):
                    raise app.yt_dlp.utils.DownloadError('HTTP Error 429: Too Many Requests')
                Path(path).write_text('WEBVTT\n\n')
                return True, True
            with patch.object(ydl, 'dl', side_effect=download):
                result = ydl._write_subtitles(info, ydl.prepare_filename(info))
            self.assertEqual(list(info['requested_subtitles']), ['en-GB'])
            self.assertEqual(len(result), 1)
            self.assertTrue(Path(result[0][0]).is_file())
            self.assertFalse(ydl.params['ignoreerrors'])
            self.assertIn('en', notices[0])
            with self.assertRaises(app.yt_dlp.utils.DownloadError):
                ydl.report_error('Video stream failed')

    def test_portable_names_preserve_unicode_and_original_metadata(self):
        cases = {'Autoalex Cars ': 'Autoalex Cars', 'CON': '_CON', 'NUL.txt': '_NUL.txt',
                 'A/B\\C: D?*<>|"': 'A-B-C- D------', 'Cafe\u0301 電気 ⚡': 'Café 電気 ⚡',
                 ' . ': 'YouTube', 'Channel... ': 'Channel', 'LPT¹': '_LPT¹'}
        for original, expected in cases.items():
            self.assertEqual(safe_media_component(original), expected)
        opts = {'quiet': True, 'outtmpl': app._v3_subscription_template()}
        info = {'id': 'abcdefghijk', 'title': 'Can You Put a Socket in a Bathroom? 🔌',
                'uploader': 'Autoalex Cars ', 'upload_date': '20260920', 'ext': 'mp4'}
        with MediaYoutubeDL(opts, output_root=app.DOWNLOAD_ROOT) as ydl:
            result = Path(ydl.prepare_filename(info))
        self.assertEqual(result.relative_to(app.DOWNLOAD_ROOT).parts[1], 'Autoalex Cars')
        self.assertNotRegex(result.name, r'[<>:"/\\|?*]')
        self.assertIn('🔌', result.name)
        self.assertIn('[abcdefghijk]', result.name)
        self.assertTrue(info['title'].endswith('? 🔌'))
        self.assertTrue(info['uploader'].endswith(' '))

    def test_long_names_are_bounded_and_ids_survive(self):
        info = {'id': 'abcdefghijk', 'title': '電' * 300, 'uploader': 'チャンネル' * 40,
                'upload_date': '20260920', 'ext': 'mp4'}
        with MediaYoutubeDL({'quiet': True, 'outtmpl': app._v3_subscription_template()}, output_root=app.DOWNLOAD_ROOT) as ydl:
            path = Path(ydl.prepare_filename(info))
        self.assertLessEqual(len(path.parent.parent.name.encode()), 80)
        self.assertLessEqual(len(path.name.encode()), 240)
        self.assertIn('[abcdefghijk]', path.name)

    def test_channel_folder_repair_updates_records_without_overwriting(self):
        old = self.job('shows/Example channel /Season 2026/video.mp4')
        root = app.subscription_output_directory({'channel_id': 'UCsample', 'title': 'Example channel'})
        new = root / 'Season 2026' / 'video.mp4'
        self.assertEqual(root.name, 'Example channel')
        self.assertTrue(new.exists())
        self.assertFalse(old.exists())
        self.assertEqual(app.download_job_row('shows/Example channel /Season 2026/video.mp4')['output_path'], str(new))
        with app.db() as conn:
            conn.execute("UPDATE subscriptions SET title='A new display name' WHERE channel_id='UCsample'")
        self.assertEqual(app.subscription_output_directory({'channel_id': 'UCsample'}), root)

    def test_folder_repair_preserves_conflicting_or_busy_folders(self):
        old = self.job('shows/Example channel /Season 2026/video.mp4', status='processing')
        with self.assertRaisesRegex(RuntimeError, 'current download'):
            app.subscription_output_directory({'channel_id': 'UCsample'})
        self.assertTrue(old.exists())
        app.update_download_job('shows/Example channel /Season 2026/video.mp4', status='completed')
        destination = app.DOWNLOAD_ROOT / 'shows' / 'Example channel'
        destination.mkdir()
        (destination / 'keep.txt').write_text('keep')
        with self.assertRaisesRegex(RuntimeError, 'No folders were merged'):
            app.subscription_output_directory({'channel_id': 'UCsample'})
        self.assertTrue(old.exists())
        self.assertEqual((destination / 'keep.txt').read_text(), 'keep')

    def test_channel_name_collision_uses_separate_directories(self):
        with app.db() as conn:
            conn.execute("INSERT INTO subscriptions(channel_id,title,channel_url,first_seen_at) VALUES ('UCother','Example channel','https://www.youtube.com/channel/UCother',?)", (app.now_iso(),))
        first = app.subscription_output_directory({'channel_id': 'UCsample'})
        second = app.subscription_output_directory({'channel_id': 'UCother'})
        self.assertNotEqual(first.name.casefold(), second.name.casefold())
        self.assertTrue(first.is_dir() and second.is_dir())

    def test_artwork_is_written_once_before_video_then_episode_nfo_after(self):
        sub = {'channel_id': 'UCsample', 'title': 'Example channel'}
        root = app.subscription_output_directory(sub)
        with patch.object(app, 'youtube_channel_artwork', return_value={'thumbnail_url': 'avatar'}), patch.object(app, '_download_image', side_effect=lambda url: Image.new('RGB', (32,32), 'red') if url else None) as download:
            app.prepare_subscription_metadata(sub, root)
            self.assertTrue((root / 'tvshow.nfo').is_file())
            self.assertTrue(all((root / name).is_file() for name in ('fanart.jpg','banner.jpg','poster.jpg')))
            initial_calls = download.call_count
            app.prepare_subscription_metadata(sub, root)
            self.assertEqual(download.call_count, initial_calls)
            media = root / 'Season 2026' / 'video.mp4'
            media.parent.mkdir()
            media.write_bytes(b'fixture')
            app.write_direct_download_series_metadata({'id':'abcdefghijk','title':'An episode','channel':'Example channel', 'upload_date':'20260920'}, str(media), channel_root=True)
            self.assertEqual(download.call_count, initial_calls)
            self.assertEqual(ET.parse(media.with_suffix('.nfo')).findtext('title'), 'An episode')
            self.assertEqual(ET.parse(media.with_suffix('.nfo')).findtext('uniqueid'), 'abcdefghijk')

    def test_output_cannot_escape_root_through_template_or_symlink(self):
        for template in (str(app.DOWNLOAD_ROOT / '..' / 'outside' / '%(id)s.mp4'), '/tmp/outside/%(id)s.mp4'):
            with MediaYoutubeDL({'quiet':True,'outtmpl':template},output_root=app.DOWNLOAD_ROOT) as ydl:
                with self.assertRaises(ValueError):
                    ydl.prepare_filename({'id':'abcdefghijk','ext':'mp4'})
        (app.DOWNLOAD_ROOT / 'linked').symlink_to(Path(self.tmp.name))
        with MediaYoutubeDL({'quiet':True,'outtmpl':str(app.DOWNLOAD_ROOT / 'linked' / '%(id)s.mp4')},output_root=app.DOWNLOAD_ROOT) as ydl:
            with self.assertRaises(ValueError):
                ydl.prepare_filename({'id':'abcdefghijk','ext':'mp4'})

    def test_completed_caption_notice_and_real_failure_are_visible(self):
        self.job('with-notice.mp4')
        app.record_download_notice('with-notice.mp4','Subtitles unavailable: en.')
        self.assertIn('Subtitles unavailable',app.pinchflat_download_overview()['latest_download']['warning'])
        self.job('failed.mp4',status='failed',exists=False)
        app.update_download_job('failed.mp4',error='Video stream unavailable')
        data=app.pinchflat_download_overview()
        self.assertEqual(data['latest_download']['state'],'completed')
        self.assertEqual(data['recent'][0]['error'],'Video stream unavailable')
        self.assertEqual(data['summary']['completed'],1)

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
    def test_real_worker_downloads_video_when_one_subtitle_request_fails(self):
        served = Path(self.tmp.name) / 'http'
        served.mkdir()
        subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-f','lavfi','-i',
                        'color=c=blue:s=128x72:r=10','-f','lavfi','-i','sine=frequency=440',
                        '-t','0.3','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',str(served/'video.mp4')],check=True)
        (served/'good.vtt').write_text('WEBVTT\n\n00:00.000 --> 00:00.300\nCaption fixture\n')
        class Handler(SimpleHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_GET(self):
                if self.path == '/missing.vtt':
                    self.send_error(429)
                else:
                    super().do_GET()
        server = ThreadingHTTPServer(('127.0.0.1',0), partial(Handler,directory=str(served)))
        thread = threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base = f'http://127.0.0.1:{server.server_port}'
        info = {'id':'abcdefghijk','title':'A test video? 🔌','channel':'Example channel',
                'uploader':'Example channel ', 'channel_id':'UCsample','upload_date':'20260920',
                'url':base+'/video.mp4','ext':'mp4','vcodec':'h264','acodec':'aac',
                'extractor':'fixture','extractor_key':'Fixture','webpage_url':'https://www.youtube.com/watch?v=abcdefghijk',
                'subtitles':{'en-GB':[{'ext':'vtt','url':base+'/good.vtt'}],
                             'en':[{'ext':'vtt','url':base+'/missing.vtt'}]}}
        opts=app._v3_profile_ydl_options('720p')
        opts.update({'quiet':True,'no_warnings':True,'outtmpl':str(served/'original'/'%(id)s.%(ext)s'),
                     'postprocessors':[]})
        # Reproduce the old failure: a .vtt remains, with no video or JSON.
        with app.yt_dlp.YoutubeDL(opts) as original:
            with self.assertRaises(app.yt_dlp.utils.DownloadError):
                original.process_ie_result(copy.deepcopy(info),download=True)
        self.assertTrue((served/'original'/'abcdefghijk.en-GB.vtt').is_file())
        self.assertFalse((served/'original'/'abcdefghijk.mp4').exists())
        self.assertFalse((served/'original'/'abcdefghijk.info.json').exists())

        app.set_setting('downloader_compatibility_profile','automatic')
        app.set_setting('downloader_sponsorblock_behaviour','disabled')
        app.set_setting('downloader_embed_thumbnail','0')
        app.set_setting('downloader_download_thumbnail','0')
        self.job('fixture-job',status='queued',exists=False)
        class FixtureYoutubeDL(MediaYoutubeDL):
            def extract_info(self, url, download=True, **kwargs):
                return self.process_ie_result(copy.deepcopy(info),download=download)
        with patch.object(app,'MediaYoutubeDL',FixtureYoutubeDL), patch.object(app,'emby_configured',return_value=False), patch.object(app,'storage_snapshot'), patch.object(app,'youtube_channel_artwork',return_value={'thumbnail_url':'avatar'}), patch.object(app,'_download_image',side_effect=lambda url: Image.new('RGB',(32,32),'red') if url else None):
            app.run_download_job('fixture-job')
        row = app.download_job_row('fixture-job')
        self.assertEqual(row['status'],'completed',row['error'])
        self.assertIn('Subtitles unavailable: en.',row['warning'])
        path=Path(row['output_path'])
        self.assertTrue(path.is_file())
        self.assertTrue(path.with_suffix('.info.json').is_file())
        self.assertTrue(path.with_suffix('.nfo').is_file())
        self.assertEqual(app._probe_single_download_codecs(path),('h264','aac'))
        self.assertTrue(any(s['codec_type']=='subtitle' for s in app._probe_download_payload(path)['streams']))
        root=path.parent.parent
        self.assertEqual(root.name,'Example channel')
        self.assertTrue(all((root/name).is_file() for name in ('tvshow.nfo','fanart.jpg','banner.jpg','poster.jpg')))
        self.assertEqual(ET.parse(root/'tvshow.nfo').findtext('title'),'Example channel')

    def test_rescan_repairs_subtitle_only_channel_folder(self):
        folder=app.DOWNLOAD_ROOT/'shows'/'Example channel '
        (folder/'Season 2026').mkdir(parents=True)
        (folder/'Season 2026'/'unfinished.en.vtt').write_text('WEBVTT\n')
        with patch.object(app,'youtube_channel_artwork',return_value={'thumbnail_url':'avatar'}), patch.object(app,'_download_image',side_effect=lambda url: Image.new('RGB',(32,32),'red') if url else None), patch.object(app,'storage_snapshot'):
            app.refresh_existing_channel_artwork()
        repaired=folder.with_name('Example channel')
        self.assertFalse(folder.exists())
        self.assertTrue((repaired/'Season 2026'/'unfinished.en.vtt').is_file())
        self.assertTrue(all((repaired/name).is_file() for name in ('tvshow.nfo','fanart.jpg','banner.jpg','poster.jpg')))

    def test_import_does_not_register_temporary_media_as_complete(self):
        folder=app.DOWNLOAD_ROOT/'shows'/'Example channel'
        folder.mkdir(parents=True)
        for name in ('Video [abcdefghijk].f137.mp4','.Video.compat-deadbeef.mp4','Video [abcdefghijk].en.vtt'):
            (folder/name).write_bytes(b'fixture')
        with patch.object(app,'storage_snapshot'):
            result=app.reconcile_existing_library(force=True)
        self.assertEqual(result['scanned'],0)
        self.assertEqual(result['imported'],0)


if __name__ == '__main__':
    unittest.main()
