"""Release-date metadata and the persistent, download-independent Upload Guide."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import json
import unittest
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET
import requests

from test_v303 import app
import test_v303 as fixtures
import upload_guide as catalogue
from publication_metadata import publication_value, write_video_nfo

NOW = datetime(2026, 9, 20, 17, 30, tzinfo=timezone.utc)


def video(vid='abcdefghijk', channel='UCsample', published='2026-09-20T09:15:24Z', **extra):
    record = {'id': vid, 'snippet': {'channelId':channel, 'title':'Morning upload', 'description':'Real channel video',
              'publishedAt':published, 'liveBroadcastContent':'none', 'thumbnails':{'high':{'url':'https://i.ytimg.com/vi/'+vid+'/hqdefault.jpg'}}},
              'contentDetails':{'duration':'PT12M34S'}, 'status':{'privacyStatus':'public','embeddable':True}}
    record.update(extra)
    return record


class GuideTests(unittest.TestCase):
    job = fixtures.DownloadTests.job

    def setUp(self):
        fixtures.DownloadTests.setUp(self)
        self.clock = patch.object(catalogue, 'now', return_value=NOW)
        self.clock.start(); self.addCleanup(self.clock.stop)
        self.guide = app.guide = catalogue.UploadGuide(app)
        with app.db() as conn:
            conn.execute("UPDATE subscriptions SET active=1,download_enabled=1,pinchflat_added=1,history_mode='today'")
        self.save_channel('UCsample')

    def save_channel(self, channel, description='A real channel description'):
        self.guide._save_channels([{'id':channel, 'snippet':{'title':channel,'description':description,'publishedAt':'2010-02-03T06:45:00Z'},
            'contentDetails':{'relatedPlaylists':{'uploads':'UU'+channel}}}])

    def get(self, **params):
        query={'date':'2026-09-20', **params}
        response=self.client.get('/api/guide',query_string=query)
        self.assertEqual(response.status_code,200,response.get_data(as_text=True))
        return response.get_json()

    def test_empty_library_and_today_cutoff_do_not_limit_remote_history(self):
        self.guide.save_videos([video(published='2025-03-12T08:19:27Z')])
        with patch.object(app,'youtube_api_request',side_effect=AssertionError('Read used network')), patch.object(app,'enqueue_download',side_effect=AssertionError('Read queued media')):
            data=self.get(date='2025-03-12')
        self.assertEqual(data['channels'][0]['events'][0]['published_at'],'2025-03-12T08:19:27+00:00')
        self.assertFalse(data['channels'][0]['events'][0]['downloaded'])
        self.assertEqual(app.completed_video_inventory()['count'],0)
        app.init_v3_db()
        self.assertEqual(self.get(date='2025-03-12')['channels'][0]['events'][0]['published_at'],'2025-03-12T08:19:27+00:00')

    def test_pagination_past_fifty_and_resumed_backfill(self):
        ids=['video'+str(i).zfill(6) for i in range(120)]
        calls=[]
        def api(creds, method, path, quota_method, quota_cost, params):
            calls.append((path,params))
            if path=='playlistItems':
                offset=int(params.get('pageToken') or 0)
                result={'items':[{'snippet':{'publishedAt':'2026-09-20T00:00:00Z'},'contentDetails':{'videoId':vid,'videoPublishedAt':'2025-01-01T06:15:00Z'}} for vid in ids[offset:offset+50]]}
                if offset+50<len(ids):result['nextPageToken']=str(offset+50)
                return SimpleNamespace(json=lambda:result)
            if path=='videos':
                self.assertNotIn('maxResults',params)
                self.assertLessEqual(len(params['id'].split(',')),50)
                return SimpleNamespace(json=lambda:{'items':[video(vid,published='2025-01-01T06:15:00Z') for vid in params['id'].split(',')]})
            raise AssertionError(path)
        with patch.object(app,'load_credentials',return_value=object()),patch.object(app,'youtube_api_request',side_effect=api):
            self.guide.tick()
            with app.db() as conn:
                row=conn.execute("SELECT * FROM guide_sync WHERE channel_id='UCsample'").fetchone()
                self.assertEqual(row['backfill_cursor'],'100')
                self.assertFalse(row['history_complete'])
            restarted=catalogue.UploadGuide(app);restarted.tick()
        with app.db() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM guide_videos').fetchone()[0],120)
            self.assertEqual(conn.execute("SELECT history_complete FROM guide_sync WHERE channel_id='UCsample'").fetchone()[0],1)
        self.assertEqual([params.get('pageToken') for path,params in calls if path=='playlistItems'],[None,'50','100'])

    def test_video_timestamp_not_playlist_insertion_and_missing_exact_times(self):
        result=video(published=None)
        self.guide.save_videos([result],{'abcdefghijk':'2025-04-05T05:42:37-04:00'})
        data=self.get(date='2025-04-05')
        self.assertEqual(data['channels'][0]['events'][0]['published_at'],'2025-04-05T09:42:37+00:00')
        self.guide.save_videos([video(published='2025-04-05')])
        item=self.get(date='2025-04-05')['channels'][0]['events'][0]
        self.assertIsNone(item['published_at']);self.assertEqual(item['time_precision'],'date')
        self.assertEqual(item['publication_date'],'2025-04-05')

    def test_local_badge_only_completed_existing_files_and_retention_keeps_catalogue(self):
        good=self.job('complete.mp4')
        self.job('partial.mp4',status='processing',video_id='bcdefghijkl')
        self.job('failed.mp4',status='failed',video_id='cdefghijklm')
        self.job('queued.mp4',status='queued',video_id='defghijklmn')
        self.guide.save_videos([video(vid) for vid in ['abcdefghijk','bcdefghijkl','cdefghijklm','defghijklmn']])
        events=self.get()['channels'][0]['events']
        self.assertEqual([e['video_id'] for e in events if e['downloaded']],['abcdefghijk'])
        good.unlink()
        events=self.get()['channels'][0]['events']
        self.assertEqual(len(events),4);self.assertFalse(any(e['downloaded'] for e in events))

    def test_enabled_channels_per_user_favourites_and_all_sort_modes(self):
        with app.db() as conn:
            conn.execute("INSERT INTO users(username,password_hash,role,created_at) VALUES ('other','unused','viewer',?)",(app.now_iso(),))
            for cid,title,profile in [('UCz','Zebra','720p'),('UCa','Áardvark','2160p'),('UCb','Beta','1080p')]:
                conn.execute("INSERT INTO subscriptions(channel_id,title,channel_url,first_seen_at,active,download_enabled,media_profile_id) VALUES(?,?,?,?,1,1,?)",(cid,title,'https://youtube.com/channel/'+cid,app.now_iso(),profile))
            conn.execute("INSERT INTO favourite_channels(user_id,channel_id,channel_title,channel_url,created_at) VALUES(1,'UCz','Zebra','https://youtube.com/channel/UCz',?)",(app.now_iso(),))
            conn.execute("INSERT INTO favourite_channels(user_id,channel_id,channel_title,channel_url,created_at) VALUES(2,'UCb','Beta','https://youtube.com/channel/UCb',?)",(app.now_iso(),))
        data=self.get();self.assertEqual(data['channels'][0]['channel_id'],'UCz')
        self.assertEqual(data['channels'][1]['channel_id'],'UCa')
        self.assertEqual(data['channels'][1]['description'],'No channel description')
        profile=self.get(sort='media_profile')['channels']
        self.assertEqual([c['channel_id'] for c in profile],['UCz','UCb','UCsample','UCa'])
        with self.client.session_transaction() as session:session['auth_user_id']=2
        self.assertEqual(self.get()['channels'][0]['channel_id'],'UCb')
        with app.db() as conn:conn.execute("UPDATE subscriptions SET download_enabled=0 WHERE channel_id='UCb'")
        self.assertNotIn('UCb',[c['channel_id'] for c in self.get()['channels']])

    def test_search_description_and_older_video_title_and_stable_channel_pages(self):
        self.guide.save_videos([video(published='2020-01-01T12:00:00Z')])
        self.assertEqual(len(self.get(search='Morning')['channels']),1)
        self.assertEqual(self.get(search='real channel')['total_channels'],1)
        self.assertEqual(self.get(search='nothing matches')['total_channels'],0)
        self.assertEqual(self.get(offset=1)['channels'],[])

    def test_gmt_bst_windows_and_non_uk_publication_boundaries(self):
        spring=self.get(date='2026-03-29',zoom='day')['window']
        autumn=self.get(date='2026-10-25',zoom='day')['window']
        delta=lambda w:(datetime.fromisoformat(w['end'])-datetime.fromisoformat(w['start'])).total_seconds()/3600
        self.assertEqual(delta(spring),23);self.assertEqual(delta(autumn),25)
        self.guide.save_videos([video(published='2026-09-19T19:15:00-04:00')])
        item=self.get(zoom='day')['channels'][0]['events'][0]
        self.assertEqual(item['published_at'],'2026-09-19T23:15:00+00:00')
        app.set_setting('guide_timezone','America/New_York')
        self.assertEqual(self.get(zoom='day')['channels'][0]['events'],[])

    def test_scheduled_live_shorts_and_prediction_dependency(self):
        scheduled=video(snippet={**video()['snippet'],'liveBroadcastContent':'upcoming'},liveStreamingDetails={'scheduledStartTime':'2026-09-22T17:00:00Z'})
        short=video('bcdefghijkl',contentDetails={'duration':'PT45S'})
        self.guide.save_videos([scheduled,short])
        self.assertEqual(len(self.get()['channels'][0]['events']),2) # Short duration alone is not a Short.
        item=next(e for e in self.get()['channels'][0]['events'] if e['video_id']=='abcdefghijk')
        self.assertEqual(item['state'],'scheduled');self.assertFalse(item['downloaded'])
        self.assertEqual(len(self.get(filter='published')['channels'][0]['events']),1)
        self.assertFalse(self.get(filter='expected')['forecasts']['enabled'])
        self.assertEqual(self.get(filter='expected')['channels'][0]['events'],[])
        self.job('short',status='skipped',video_id='bcdefghijkl',exists=False)
        with app.db() as conn:conn.execute("UPDATE downloads SET failure_code='shorts_excluded'")
        self.guide.save_videos([short])
        self.assertEqual(len(self.get()['channels'][0]['events']),1)

    def test_quota_error_cached_read_and_persisted_backoff(self):
        self.guide.save_videos([video()])
        response=Mock(status_code=403)
        response.json.return_value={'error':{'errors':[{'reason':'quotaExceeded'}]}}
        error=requests.HTTPError('SECRET must not enter diagnostics',response=response)
        with patch.object(app,'load_credentials',return_value=object()),patch.object(app,'youtube_api_request',side_effect=error) as api:
            self.guide.tick();self.guide.tick()
            self.assertEqual(api.call_count,1)
        data=self.get();self.assertEqual(len(data['channels'][0]['events']),1)
        self.assertIn('quotaExceeded',data['coverage']['error'])
        self.assertNotIn('SECRET',json.dumps(data))
        with app.db() as conn:self.assertNotIn('SECRET',str([dict(r) for r in conn.execute('SELECT * FROM activity')]))

    def test_stale_metadata_purged_and_duplicate_refresh_does_not_spawn_downloads(self):
        self.guide.save_videos([video()])
        with app.db() as conn:conn.execute('UPDATE guide_videos SET metadata_checked_at=?',(catalogue.stamp(NOW-timedelta(days=31)),))
        self.assertEqual(self.get()['channels'][0]['events'],[])
        self.guide.expire()
        with app.db() as conn:self.assertEqual(conn.execute('SELECT COUNT(*) FROM guide_videos').fetchone()[0],0)
        with patch.object(app,'enqueue_download',side_effect=AssertionError('Unexpected media download')):
            for _ in range(2):
                response=self.client.post('/api/guide/refresh',headers={'X-CSRF-Token':'test-token'})
                self.assertEqual(response.status_code,200)
        with app.db() as conn:self.assertEqual(conn.execute('SELECT COUNT(*) FROM guide_sync').fetchone()[0],1)
        self.assertEqual(self.client.post('/api/guide/refresh').status_code,400)
        with app.db() as conn:conn.execute("UPDATE users SET role='viewer' WHERE id=1")
        self.assertEqual(self.client.post('/api/guide/refresh',headers={'X-CSRF-Token':'test-token'}).status_code,302)
        self.assertEqual(self.client.get('/api/guide').status_code,200)

    def test_lease_blocks_duplicate_worker_and_reads_do_not_start_indexing(self):
        with app.db() as conn:conn.execute('UPDATE guide_runtime SET lease_until=?',(catalogue.stamp(NOW+timedelta(minutes=5)),))
        with patch.object(app,'youtube_api_request',side_effect=AssertionError('Duplicate worker')):
            self.assertFalse(self.guide.tick())
            self.get()
        with app.db() as conn:self.assertEqual(conn.execute('SELECT COUNT(*) FROM guide_sync').fetchone()[0],0)

    def test_release_nfo_fields_preserve_user_values_and_existing_media(self):
        path=self.job('shows/Example channel/Season 2025/s2025E040500 - Video [abcdefghijk].mp4')
        path.with_suffix('.nfo').write_text('<episodedetails><title>My edited title</title><playcount>3</playcount><dateadded>2026-09-20 13:00:00</dateadded><aired>2026-09-20</aired></episodedetails>')
        original=path.read_bytes()
        self.guide.save_videos([video(published='2025-04-05T18:45:32Z')])
        result=app.repair_publication_dates()
        self.assertEqual(result['updated'],1)
        tree=ET.parse(path.with_suffix('.nfo')).getroot()
        for key in ('aired','premiered','releasedate'):self.assertEqual(tree.findtext(key),'2025-04-05')
        self.assertEqual(tree.findtext('year'),'2025');self.assertEqual(tree.findtext('title'),'My edited title')
        self.assertEqual(tree.findtext('playcount'),'3');self.assertEqual(tree.findtext('dateadded'),'2026-09-20 13:00:00')
        self.assertEqual(path.read_bytes(),original)
        self.assertEqual(app.repair_publication_dates()['updated'],0)
        with app.db() as conn:self.assertEqual(conn.execute('SELECT published_at FROM downloads').fetchone()[0],'2025-04-05T18:45:32+00:00')

    def test_no_fabricated_release_date_and_direct_video_nfo(self):
        path=self.job('single.mp4',source='single')
        self.assertEqual(app.repair_publication_dates()['missing'],1)
        self.assertFalse(path.with_suffix('.nfo').exists())
        write_video_nfo({'id':'abcdefghijk','title':'Safe & <XML> \x01','upload_date':'20240103'},path,episode=False)
        root=ET.parse(path.with_suffix('.nfo')).getroot()
        self.assertEqual(path.with_suffix('.nfo').stat().st_mode & 0o777, 0o644)
        self.assertEqual(root.tag,'movie');self.assertEqual(root.findtext('premiered'),'2024-01-03')
        self.assertEqual(root.findtext('title'),'Safe & <XML> ')
        self.assertEqual(publication_value({'upload_date':'20240103'}),'2024-01-03')
        self.assertEqual(publication_value({'upload_date':'20240103','release_timestamp':1704320523}),'2024-01-03T22:22:03+00:00')

    def test_selection_survives_search_and_range_but_disabled_channel_leaves(self):
        self.guide.save_videos([video()])
        data=self.get(date='2020-01-01',search='different',selected='abcdefghijk')
        self.assertEqual(data['channels'],[])
        self.assertEqual(data['selection']['item']['video_id'],'abcdefghijk')
        with app.db() as conn:conn.execute("UPDATE subscriptions SET download_enabled=0 WHERE channel_id='UCsample'")
        self.assertIsNone(self.get(selected='abcdefghijk')['selection'])

    def test_renewal_removes_unavailable_video_and_keeps_valid_older_catalogue(self):
        self.guide.save_videos([video(),video('bcdefghijkl',published='2018-02-03T06:15:00Z')])
        with app.db() as conn:
            conn.execute('UPDATE guide_videos SET metadata_checked_at=?',(catalogue.stamp(NOW-timedelta(days=26)),))
        self.guide.budget_left=10
        response={'items':[video('bcdefghijkl',published='2018-02-03T06:15:00Z')]}
        response['items'][0]['snippet']['title']='Updated historical title'
        with patch.object(app,'youtube_api_request',return_value=SimpleNamespace(json=lambda:response)):
            self.guide._videos(object(),['abcdefghijk','bcdefghijkl'])
        with app.db() as conn:
            rows=conn.execute('SELECT * FROM guide_videos').fetchall()
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['title'],'Updated historical title')
        self.assertEqual(rows[0]['published_at'],'2018-02-03T06:15:00+00:00')
        self.assertEqual(rows[0]['metadata_checked_at'],catalogue.stamp(NOW))

    def test_invalid_page_token_resets_checkpoint_without_removing_history(self):
        self.guide.save_videos([video()]);self.guide.request_refresh()
        with app.db() as conn:
            conn.execute("UPDATE guide_sync SET initialised=1,backfill_cursor='expired',recent_checked_at=?,refresh_requested=0,channel_refresh_requested=0",(catalogue.stamp(),))
        response=Mock(status_code=400)
        response.json.return_value={'error':{'errors':[{'reason':'invalidPageToken'}]}}
        with patch.object(app,'load_credentials',return_value=object()),patch.object(app,'youtube_api_request',side_effect=requests.HTTPError(response=response)):
            self.guide.tick()
        with app.db() as conn:
            row=conn.execute('SELECT * FROM guide_sync').fetchone()
            self.assertFalse(row['initialised']);self.assertIsNone(row['backfill_cursor'])
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM guide_videos').fetchone()[0],1)

    def test_dense_channel_events_have_explicit_pagination(self):
        self.guide.save_videos([video('dense'+str(i).zfill(6)) for i in range(503)])
        first=self.get()['channels'][0]
        self.assertEqual(len(first['events']),500);self.assertEqual(first['events_next_offset'],500)
        second=self.get(channel='UCsample',event_offset=500)['channels'][0]
        self.assertEqual(len(second['events']),3);self.assertIsNone(second['events_next_offset'])
        self.assertFalse({v['id'] for v in first['events']}&{v['id'] for v in second['events']})
