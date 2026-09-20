"""Regression coverage for the native download lifecycle and v3.0.3 dashboard."""
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET

from PIL import Image

BOOT = tempfile.TemporaryDirectory()
os.environ['DATA_DIR'] = str(Path(BOOT.name) / 'data')
os.environ['DOWNLOAD_ROOT'] = str(Path(BOOT.name) / 'media')
os.environ['CANONICAL_REDIRECT'] = 'false'
APP_DIR = Path(__file__).resolve().parents[1] / 'app'
sys.path.insert(0, str(APP_DIR))
spec = importlib.util.spec_from_file_location('ytsd_test_app', APP_DIR / 'app.py')
app = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = app
with patch('threading.Thread.start'), patch('apscheduler.schedulers.background.BackgroundScheduler.start'):
    spec.loader.exec_module(app)


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        app.DB_PATH = Path(self.tmp.name) / 'sync.db'
        app.DOWNLOAD_ROOT = Path(self.tmp.name) / 'media'
        app.DOWNLOAD_ROOT.mkdir()
        app.settings_cache.update(updated_at=0, values={})
        app.invalidate_video_inventory()
        app.init_db()
        app.init_v3_db()
        app.init_v303_defaults()
        with app.db() as conn:
            conn.execute("INSERT INTO users(username,password_hash,role,created_at) VALUES ('tester','unused','admin',?)", (app.now_iso(),))
            conn.execute("INSERT INTO subscriptions(channel_id,title,channel_url,first_seen_at,thumbnail_url) VALUES ('UCsample','Example channel','https://www.youtube.com/channel/UCsample',?,'https://example.test/avatar.jpg')", (app.now_iso(),))
        self.client = app.app.test_client()
        with self.client.session_transaction() as session:
            session['auth_user_id'] = 1
            session['auth_session_version'] = 1
            session['_csrf_token'] = 'test-token'

    def job(self, name, status='completed', source='subscription', video_id='abcdefghijk', profile='1080p', exists=True):
        path = app.DOWNLOAD_ROOT / name
        if exists:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'fixture-video')
        with app.db() as conn:
            conn.execute("""INSERT INTO downloads(job_id,source_type,youtube_url,video_id,title,channel_title,channel_id,
                         status,phase,progress,output_path,created_at,finished_at,profile_id)
                         VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                         (name, source, 'https://www.youtube.com/watch?v='+video_id, video_id,
                          name, 'Example channel','UCsample',status,
                          'FFmpeg · converting for Emby / Smart TV' if status=='processing' else status,
                          94 if status=='processing' else 100,str(path),app.now_iso(),app.now_iso(),profile))
        app.invalidate_video_inventory()
        return path

    def test_totals_and_discover_include_only_existing_unique_completed_videos(self):
        good = self.job('video.mp4')
        self.job('audio.m4a', profile='audio')
        self.job('wrong-profile.mp4', profile='audio')
        self.job('video.info.json')
        self.job('fanart.jpg')
        self.job('video.en.srt')
        self.job('missing.mkv', exists=False)
        self.job('.video.compat-deadbeef.mp4')
        self.job('video.f137.mp4')
        self.job('working.mp4', status='processing')
        self.job('duplicate.mp4', exists=False)
        with app.db() as conn:
            conn.execute("UPDATE downloads SET output_path=? WHERE job_id='duplicate.mp4'", (str(good),))
        overview = self.client.get('/api/pinchflat/download-overview').get_json()
        self.assertTrue(overview['ok'])
        self.assertEqual(overview['summary']['completed'], 1)
        self.assertEqual(overview['summary']['video_bytes'], good.stat().st_size)
        with patch.object(app, 'pinchflat_db_readonly', side_effect=AssertionError('Legacy DB called')):
            response = self.client.get('/api/discover?kind=downloaded')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.get_json()['results']), 1)
        self.assertTrue(response.get_json()['results'][0]['from_downloader'])
        good.unlink()
        app.invalidate_video_inventory()
        self.assertEqual(app.completed_video_inventory()['count'], 0)

    def test_processing_stays_active_and_latest_until_completion(self):
        self.job('previous.mp4')
        self.job('new.mp4', status='processing', source='single')
        data = app.pinchflat_download_overview()
        self.assertEqual(data['latest_download']['job_id'], 'new.mp4')
        self.assertIn('FFmpeg', data['latest_download']['status'])
        self.assertEqual(data['active'][0]['source_type'], 'single')
        self.assertEqual(data['last_downloaded']['job_id'], 'previous.mp4')
        self.assertEqual(data['summary']['completed'], 1)
        app.update_download_job('new.mp4', status='completed', phase='Completed', finished_at=app.now_iso())
        data = app.pinchflat_download_overview()
        self.assertFalse(data['active'])
        self.assertEqual(data['latest_download']['job_id'], 'new.mp4')
        self.assertEqual(data['summary']['completed'], 2)

    def test_progress_hook_sets_one_time_identity_before_postprocessing(self):
        self.job('single.mp4', status='queued', source='single')
        app._download_progress_hook('single.mp4')({'status':'finished','filename':'single.mp4',
            'info_dict': {'id':'newvideo123','title':'New title','channel_id':'UCsample','channel':'Example channel'}})
        row=app.download_job_row('single.mp4')
        self.assertEqual(row['title'], 'New title')
        self.assertEqual(row['video_id'], 'newvideo123')
        self.assertEqual(row['status'], 'downloading')
        self.assertNotIn('FFmpeg', row['phase'])

    def test_exact_final_path_never_selects_other_video_or_sidecar(self):
        other=self.job('different [zzzzzzzzzzz].mp4')
        sidecar=self.job('wanted [abcdefghijk].en.vtt')
        ydl=Mock()
        ydl.prepare_filename.return_value=str(app.DOWNLOAD_ROOT / 'missing.webm')
        self.assertEqual(app.resolve_direct_download_output_path({'id':'abcdefghijk'},ydl,app.DOWNLOAD_ROOT), '')
        wanted=self.job('wanted [abcdefghijk].mp4')
        self.assertEqual(app.resolve_direct_download_output_path({'id':'abcdefghijk'},ydl,app.DOWNLOAD_ROOT),str(wanted))
        self.assertEqual(app.resolve_direct_download_output_path({'id':'abcdefghijk','filepath':str(wanted)},ydl,app.DOWNLOAD_ROOT,str(other)),str(wanted))

    def test_channel_artwork_and_nfo_survive_failed_banner(self):
        path=self.job('shows/Example channel/Season 2026/video.mp4')
        def image(url):
            if url.endswith('banner'):
                raise RuntimeError('banner unavailable')
            return Image.new('RGB',(64,64),(240,20,20))
        with patch.object(app,'youtube_channel_artwork',return_value={'thumbnail_url':'avatar','banner_url':'banner'}), patch.object(app,'_download_image',side_effect=image):
            app.write_direct_download_series_metadata({'channel':'Example channel','channel_id':'UCsample','thumbnail':'wrong-video'},str(path),channel_root=True)
        root=path.parent.parent
        self.assertEqual(ET.parse(root/'tvshow.nfo').findtext('title'),'Example channel')
        for name in ['fanart.jpg','banner.jpg','poster.jpg']:
            with Image.open(root/name) as img:
                r,g,b=img.getpixel((img.width//2,img.height//2))
                self.assertGreater(r,200)
                self.assertLess(g,50)
        self.assertFalse((path.parent/'tvshow.nfo').exists())

    def test_saved_avatar_fallback_and_artwork_toggles(self):
        with patch.object(app,'youtube_channel_summary',return_value={}):
            self.assertEqual(app.youtube_channel_artwork('UCsample')['thumbnail_url'],'https://example.test/avatar.jpg')
        path=self.job('shows/Example channel/Season 2026/video.mp4')
        with patch.object(app,'_download_image',side_effect=AssertionError('Artwork disabled')):
            app.write_direct_download_series_metadata({'channel':'Example channel'},str(path),write_nfo=False,write_images=False,channel_root=True)
        self.assertFalse((path.parent.parent/'tvshow.nfo').exists())

    def test_subscription_metadata_uses_job_identity_and_finishes_after_writing(self):
        path=self.job('shows/Example channel/Season 2026/video.mp4', status='queued')
        job_id='shows/Example channel/Season 2026/video.mp4'
        app.set_setting('downloader_compatibility_profile','automatic')
        info={'id':'abcdefghijk','title':'Example video','filepath':str(path),'upload_date':'20260101'}
        def metadata(info, output, **kwargs):
            self.assertIn(app.download_job_row(job_id)['status'], ('downloading','processing'))
            self.assertEqual(info['channel_id'],'UCsample')
            self.assertTrue(kwargs['channel_root'])
        with patch.object(app,'_v3_download_with_auth_retry',return_value=(info,Mock(),'anonymous')), patch.object(app,'write_direct_download_series_metadata',side_effect=metadata), patch.object(app,'storage_snapshot'), patch.object(app,'emby_configured',return_value=False):
            app.run_download_job(job_id)
        self.assertEqual(app.download_job_row(job_id)['status'],'completed',app.download_job_row(job_id)['error'])

    def test_media_switches_install_real_postprocessors_and_respect_off(self):
        options=app._v3_profile_ydl_options('1080p')
        keys={p['key'] for p in options['postprocessors']}
        self.assertTrue({'FFmpegEmbedSubtitle','FFmpegMetadata','EmbedThumbnail','SponsorBlock','ModifyChapters'} <= keys)
        # Instantiate the real yt-dlp processors without fetching a video.
        with app.yt_dlp.YoutubeDL({**options,'quiet':True}) as ydl:
            self.assertTrue(ydl._pps['post_process'])
        for name in ['download_subtitles','embed_subtitles','download_thumbnail','embed_thumbnail','download_metadata','embed_metadata']:
            app.set_setting('downloader_'+name,'0')
        app.set_setting('downloader_sponsorblock_behaviour','disabled')
        options=app._v3_profile_ydl_options('1080p')
        self.assertEqual(options['postprocessors'],[])
        self.assertFalse(options['writethumbnail'])
        self.assertFalse(options['writeinfojson'])
        self.assertFalse(options.get('writesubtitles',False))

    def test_latest_tab_and_default_migrate_once(self):
        self.assertFalse(app.setting_bool('page_load_latest_videos', True))
        app.set_setting('page_load_latest_videos','1')
        app.init_v303_defaults()
        self.assertTrue(app.setting_bool('page_load_latest_videos',False))
        with patch.object(app,'youtube_latest_subscription_videos',return_value={'results':[{'video_id':'v1','published_at':'2026-01-01'}],'shorts':[{'video_id':'v2','published_at':'2026-02-01'}]}):
            response=self.client.get('/api/discover?kind=latest')
        self.assertEqual(response.status_code,200)
        self.assertEqual([r['video_id'] for r in response.get_json()['results']],['v2','v1'])

    def test_failed_processing_is_not_a_completed_download(self):
        self.job('failed.mp4',status='processing')
        app.update_download_job('failed.mp4',status='failed',phase='Failed')
        data=app.pinchflat_download_overview()
        self.assertEqual(data['summary']['completed'],0)
        self.assertEqual(data['latest_download']['state'], 'failed')

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
    def test_real_compatibility_conversion(self):
        path=app.DOWNLOAD_ROOT/'source.mkv'
        subtitle=app.DOWNLOAD_ROOT/'source.srt'
        subtitle.write_text('1\n00:00:00,000 --> 00:00:00,300\nTest subtitle\n')
        subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-f','lavfi','-i','color=c=blue:s=128x72:r=10','-f','lavfi','-i','sine=frequency=440','-i',str(subtitle),'-c:s','srt','-t','0.3','-c:v','mpeg4','-c:a','libmp3lame',str(path)],check=True)
        result=Path(app.ensure_download_emby_compatibility(str(path)))
        self.assertEqual(result.suffix,'.mp4')
        self.assertEqual(app._probe_single_download_codecs(result),('h264','aac'))
        self.assertFalse(path.exists())
        streams=app._probe_download_payload(result)['streams']
        self.assertTrue(any(s['codec_type']=='subtitle' for s in streams))


if __name__=='__main__':
    unittest.main()
