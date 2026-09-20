"""Guide refresh/cache, conservative forecasts and provider-neutral downloads."""
from datetime import datetime, timedelta, timezone
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
import json
import subprocess
import threading
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

import test_v303 as fixtures
import test_v307 as guide_fixtures
from guide_forecasts import forecast_events, matches
import upload_guide as catalogue

app = fixtures.app
NOW = guide_fixtures.NOW


class GuideReleaseTests(unittest.TestCase):
    setUp = guide_fixtures.GuideTests.setUp
    save_channel = guide_fixtures.GuideTests.save_channel
    get = guide_fixtures.GuideTests.get

    def test_all_enabled_channels_and_statistics_return_without_api_requests(self):
        with app.db() as conn:
            for i in range(130):
                conn.execute('INSERT INTO subscriptions(channel_id,title,channel_url,first_seen_at,active,download_enabled) VALUES(?,?,?,?,1,1)', (f'UC{i}',f'Channel {i}',f'https://youtube.com/channel/UC{i}',app.now_iso()))
        self.guide.save_videos([guide_fixtures.video(statistics={'viewCount':'1234','likeCount':'20'})])
        with patch.object(app,'youtube_api_request',side_effect=AssertionError('Guide read used API')):
            data=self.get()
            again=self.get()
        self.assertEqual(len(data['channels']),131)
        self.assertIsNone(data['next_offset'])
        item=next(c for c in data['channels'] if c['channel_id']=='UCsample')['events'][0]
        self.assertEqual(item['view_count'],1234);self.assertEqual(item['like_count'],20)
        self.assertIsNone(item['comment_count']);self.assertTrue(item['metadata_rich'])
        self.assertEqual(data,again)

    def test_daily_schedule_and_restart_do_not_repeat_completed_refresh(self):
        self.guide.save_videos([guide_fixtures.video()])
        with app.db() as conn:
            conn.execute("INSERT INTO guide_sync(channel_id,initialised,history_complete,refresh_requested,recent_checked_at) VALUES('UCsample',1,1,0,?)",(catalogue.stamp(NOW),))
            conn.execute('UPDATE guide_runtime SET scheduled_at=?',(self.guide.scheduled_boundary(),))
        def scheduled_api(creds, method, path, quota_method, quota_cost, params):
            if path=='channels':
                return SimpleNamespace(json=lambda:{'items':[{'id':'UCsample','snippet':{'title':'Example channel'},'contentDetails':{'relatedPlaylists':{'uploads':'UUUCsample'}}}]})
            if path=='videos':return SimpleNamespace(json=lambda:{'items':[guide_fixtures.video()]})
            return SimpleNamespace(json=lambda:{'items':[{'contentDetails':{'videoId':'abcdefghijk'}}]})
        with patch.object(app,'load_credentials',return_value=object()),patch.object(app,'youtube_api_request',side_effect=scheduled_api) as api:
            self.guide.tick();catalogue.UploadGuide(app).tick()
            self.assertEqual(api.call_count,0)
            tomorrow=NOW+timedelta(days=1)
            with patch.object(catalogue,'now',return_value=tomorrow):
                self.guide.tick()
                self.assertEqual(api.call_count,3)
                self.guide.tick()
                self.assertEqual(api.call_count,3)
        self.assertEqual(self.guide.next_refresh(),'2026-09-21T03:00:00+00:00')

    def test_guide_settings_schedule_predictions_and_permissions(self):
        payload={'_csrf':'test-token','guide_timezone':'Europe/London','guide_refresh_time':'06:45',
                 'guide_history':'year','guide_daily_budget':'500','guide_predictions_enabled':'1'}
        response=self.client.post('/settings/guide',data=payload)
        self.assertEqual(response.status_code,302)
        self.assertEqual(app.get_setting('guide_refresh_time'),'06:45')
        self.assertTrue(self.guide.forecasts.status()['enabled'])
        self.assertEqual(self.guide.next_refresh(),'2026-09-21T05:45:00+00:00')
        payload['guide_refresh_time']='99:99';self.client.post('/settings/guide',data=payload)
        self.assertEqual(app.get_setting('guide_refresh_time'),'06:45')
        payload['guide_refresh_time']='03:00'
        with app.db() as conn:conn.execute("UPDATE users SET role='viewer' WHERE id=1")
        self.client.post('/settings/guide',data=payload)
        self.assertEqual(app.get_setting('guide_refresh_time'),'06:45')

    def test_dashboard_guide_order_and_lazy_setting_persist(self):
        response=self.client.post('/settings/page-view',data={'_csrf':'test-token','page_section_order':'guide,summary,pinchflat,subscriptions,latest',
            'page_load_guide':'1','page_min_guide':'1'})
        self.assertEqual(response.status_code,302)
        self.assertTrue(app.get_setting('page_section_order').startswith('guide,'))
        self.assertEqual(app.get_setting('page_autoload_guide'),'0')
        html=self.client.get('/').get_data(as_text=True)
        self.assertEqual(html.count('id="ytsd-guide"'),1)
        self.assertIn('data-autoload="false"',html);self.assertIn('data-minimised="true"',html)
        self.assertNotIn('id="yt-load-more"',html)

    def test_prediction_cache_is_read_only_and_real_upload_replaces_estimate(self):
        records=[]
        for n in range(24):
            published=NOW-timedelta(days=NOW.weekday()+7*n, hours=1)
            records.append(guide_fixtures.video('prior'+str(n).zfill(6),published=published.isoformat()))
        self.guide.save_videos(records)
        with app.db() as conn:conn.execute("INSERT INTO guide_sync(channel_id,initialised) VALUES('UCsample',1)")
        self.guide.forecasts.rebuild()
        data=self.get(date='2026-09-21',filter='expected')
        events=data['channels'][0]['events'];self.assertGreater(len(events),0)
        expected=events[0]
        self.assertIsNone(expected['video_id']);self.assertFalse(expected['downloaded'])
        scheduled=guide_fixtures.video(published=NOW.isoformat(),snippet={**guide_fixtures.video()['snippet'],'liveBroadcastContent':'upcoming'},liveStreamingDetails={'scheduledStartTime':expected['event_at']})
        self.guide.save_videos([scheduled])
        with patch.object(self.guide.forecasts,'rebuild',side_effect=AssertionError('Read rebuilt cache')):
            self.assertNotIn(expected['id'],[e['id'] for e in self.get(date='2026-09-21')['channels'][0]['events']])


class ForecastTests(unittest.TestCase):
    def samples(self, pattern, start=NOW-timedelta(days=380), hours=(18,), kind='unknown'):
        result=[];day=start.date()
        while day<NOW.date():
            if matches(day,pattern):
                for hour in hours:
                    result.append({'published_at':datetime.combine(day,datetime.min.time(),timezone.utc).replace(hour=hour).isoformat(), 'classification':kind,'broadcast_state':'published'})
            day+=timedelta(days=1)
        return result

    def estimate(self, records):
        return forecast_events('UCchannel',records,NOW,'UTC')

    def test_daily_multiple_weekdays_and_multiple_slots(self):
        for pattern in [('daily',0,0),('weekly',0,0),('fortnightly',1,0)]:
            events=self.estimate(self.samples(pattern,hours=(9,18)))
            self.assertTrue(events,pattern)
            self.assertTrue(all(matches(datetime.fromisoformat(e['event_at']).date(),pattern) for e in events),pattern)
            self.assertEqual({datetime.fromisoformat(e['event_at']).hour for e in events},{9,18})
            self.assertTrue(all(e['confidence'] in ('High','Moderate') and e['observations']>=8 for e in events))
        events=self.estimate(self.samples(('weekly',0,0))+self.samples(('weekly',3,0)))
        self.assertEqual({datetime.fromisoformat(e['event_at']).weekday() for e in events},{0,3})

    def test_calendar_month_dates_and_nth_weekday_are_not_thirty_day_intervals(self):
        for pattern in [('monthly',25,0),('nth_weekday',6,0)]:
            events=self.estimate(self.samples(pattern,start=NOW-timedelta(days=520)))
            self.assertTrue(events,pattern)
            self.assertTrue(all(matches(datetime.fromisoformat(e['event_at']).date(),pattern) for e in events),pattern)

    def test_sparse_burst_irregular_and_changed_schedule_suppress_forecasts(self):
        self.assertEqual(self.estimate(self.samples(('weekly',0,0))[:4]),[])
        burst=[{'published_at':(NOW-timedelta(hours=i)).isoformat()} for i in range(20)]
        self.assertEqual(self.estimate(burst),[])
        irregular=[{'published_at':(NOW-timedelta(days=i*13+(i*i)%9,hours=(i*7)%24)).isoformat()} for i in range(25)]
        self.assertEqual(self.estimate(irregular),[])
        changed=self.samples(('weekly',0,0))
        for r in changed[-7:]:r['published_at']=(datetime.fromisoformat(r['published_at'])+timedelta(days=2,hours=-6)).isoformat()
        self.assertEqual(self.estimate(changed),[])

    def test_types_separate_unknown_times_excluded_and_horizon_limited(self):
        regular=self.samples(('weekly',0,0))
        streams=self.samples(('weekly',2,0),kind='livestream')
        events=self.estimate(regular+streams+[{'publication_date':'2026-09-20'}])
        self.assertEqual({e['classification'] for e in events},{'unknown','livestream'})
        self.assertTrue(all(NOW<datetime.fromisoformat(e['window_start']) and datetime.fromisoformat(e['event_at'])<NOW+timedelta(days=15) for e in events))
        expired=NOW+timedelta(days=100)
        self.assertEqual(forecast_events('UCchannel',regular,expired,'UTC'),[])


class ProviderDownloadTests(unittest.TestCase):
    setUp=fixtures.DownloadTests.setUp
    job=fixtures.DownloadTests.job

    def test_urls_provider_ids_and_processing_deduplication(self):
        for value in ['https://vimeo.com/1234','https://example.test/video.mp4?token=a','https://www.dailymotion.com/video/xyz']:
            response=self.client.post('/single-download/start',json={'url':value},headers={'X-CSRF-Token':'test-token'})
            self.assertEqual(response.status_code,200,response.json)
            job=response.json['job_id'];app.update_download_job(job,status='processing')
            again=self.client.post('/single-download/start',json={'url':value},headers={'X-CSRF-Token':'test-token'})
            self.assertEqual(again.json['job_id'],job);self.assertFalse(again.json['created'])
        for value in ['file:///etc/passwd','javascript:alert(1)','https://','https://user:password@example.test/video']:
            self.assertFalse(app.valid_download_url(value))
        self.assertEqual(app.download_info_id({'id':'abcdefghijk','extractor_key':'Vimeo'}),'media:vimeo:abcdefghijk')
        self.assertEqual(app.download_info_channel({'id':'123','channel_id':'not-youtube','extractor_key':'Vimeo'}),'')

    def test_non_youtube_auth_failure_does_not_retry_youtube_cookies(self):
        with patch.object(app,'MediaYoutubeDL') as ydl,patch.object(app,'_v3_cookie_status',side_effect=AssertionError('Cookies used')):
            ydl.return_value.__enter__.return_value.extract_info.side_effect=RuntimeError('Sign in to confirm your age')
            with self.assertRaises(RuntimeError):app._v3_download_with_auth_retry({'youtube_url':'https://vimeo.com/123','job_id':'123'},{})
            self.assertEqual(ydl.call_count,1)

    def test_real_generic_http_download_completion_and_authenticated_range_playback(self):
        source=Path(self.tmp.name)/'source';source.mkdir()
        subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-f','lavfi','-i','color=c=blue:s=160x90:d=1', '-c:v','libx264','-pix_fmt','yuv420p',str(source/'video.mp4')],check=True)
        class Quiet(SimpleHTTPRequestHandler):
            def log_message(self,*args):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),partial(Quiet,directory=str(source)))
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            url=f'http://127.0.0.1:{server.server_port}/video.mp4'
            job,_=app.enqueue_download(url)
            with patch.object(app,'youtube_api_request',side_effect=AssertionError('Generic video queried YouTube')),patch.object(app,'emby_refresh_download_library'):
                app.run_download_job(job)
            row=app.download_job_row(job)
            self.assertEqual(row['status'],'completed',row['error'])
            self.assertTrue(row['video_id'].startswith('media:generic:'))
            self.assertIn('[source-',Path(row['output_path']).name)
            latest=app.pinchflat_download_overview()['latest_download']
            self.assertTrue(latest['is_external']);self.assertEqual(latest['youtube_id'],'')
            response=self.client.get(latest['local_media_url'],headers={'Range':'bytes=0-31'})
            self.assertEqual(response.status_code,206);self.assertEqual(len(response.data),32);response.close()
            self.assertEqual(self.client.get('/api/discover?kind=downloaded').json['results'][0]['is_external'],True)
            client=app.app.test_client();self.assertNotEqual(client.get(latest['local_media_url']).status_code,200)
            other,_=app.enqueue_download(url+'?another-source=1')
            with patch.object(app,'youtube_api_request',side_effect=AssertionError('Generic video queried YouTube')),patch.object(app,'emby_refresh_download_library'):
                app.run_download_job(other)
            self.assertEqual(app.download_job_row(other)['status'],'completed')
            self.assertNotEqual(app.download_job_row(other)['output_path'],row['output_path'])
            app.update_download_job(job,status='processing');self.assertEqual(self.client.get(latest['local_media_url']).status_code,404)
        finally:server.shutdown();server.server_close();thread.join(5)

    def test_provider_activity_thumbnail_and_outside_root_media_rejected(self):
        self.job('external.mp4',source='single',video_id='media:vimeo:abcdefghijk')
        with app.db() as conn:
            conn.execute("UPDATE downloads SET job_id='external',youtube_url='https://vimeo.com/123',channel_id=NULL,thumbnail_url='https://example.test/cover.jpg'")
        app.log_activity('download','Download completed','Downloaded [abcdefghijk].mp4',job_id='external')
        item=self.client.get('/api/activity').json['activity'][0]
        self.assertEqual(item['thumbnail_url'],'https://example.test/cover.jpg')
        self.assertEqual(item['video_id'],'');self.assertEqual(item['local_media_url'],'/downloads/external/media')
        outside=Path(self.tmp.name)/'outside.mp4';outside.write_bytes(b'private')
        app.update_download_job('external',output_path=str(outside))
        self.assertEqual(self.client.get('/downloads/external/media').status_code,404)
