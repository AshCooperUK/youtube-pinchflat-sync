"""Session-gated watched requests and one-time bulk marking."""
import unittest,time
from pathlib import Path
from unittest.mock import patch,Mock
import test_v303 as fixtures
import watched_status as watched
app=fixtures.app

class WatchedSessionTests(unittest.TestCase):
    setUp=fixtures.DownloadTests.setUp
    job=fixtures.DownloadTests.job
    def post(self,path,payload):
        return self.client.post(path,json=payload,headers={'X-CSRF-Token':'test-token'})
    def cookie(self,expiry):
        p=Path(self.tmp.name)/'cookies.txt'
        p.write_text('# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t'+str(expiry)+'\tSAPISID\tprivate-token\n')
        return p
    def test_expiry_and_live_logged_out_block_before_watched_subprocess(self):
        p=self.cookie(1)
        self.assertEqual(watched.cookie_session_file_status(p)[0],'auth_expired')
        with patch('watched_status.subprocess.run') as run:
            self.assertEqual(watched.send_watched_request('abcdefghijk',p)[0],'auth_expired');run.assert_not_called()
        self.cookie(int(time.time())+3600)
        response=Mock(text='ytcfg.set({"LOGGED_IN":false});')
        with patch('watched_status.requests.Session') as session,patch('watched_status.subprocess.run') as run:
            session.return_value.__enter__.return_value.get.return_value=response
            self.assertEqual(watched.send_watched_request('abcdefghijk',p)[0],'auth_expired');run.assert_not_called()
    def test_explicit_active_session_required(self):
        p=self.cookie(int(time.time())+3600)
        for html,expected in [('ytcfg.set({"LOGGED_IN":true});','active'),('consent page','auth_unverified'),('ytcfg.set({"LOGGED_IN":"true"});','auth_unverified')]:
            with patch('watched_status.requests.Session') as session:
                session.return_value.__enter__.return_value.get.return_value=Mock(text=html)
                self.assertEqual(watched.check_cookie_session(p)[0],expected)
    def test_bulk_deduplicates_filters_and_cancels(self):
        self.job('one.mp4');self.job('duplicate.mp4')
        self.job('two.mp4',video_id='bcdefghijkl',source='single')
        self.job('external.mp4',video_id='media:bbc:id')
        self.job('missing.mp4',video_id='cdefghijklm',exists=False)
        self.job('processing.mp4',video_id='defghijklmn',status='processing')
        with patch.object(app,'check_cookie_session',return_value=('active','Signed in')):
            self.assertEqual(self.post('/api/youtube/watched-all',{}).status_code,400)
            result=self.post('/api/youtube/watched-all',{'confirm':True})
            self.assertEqual(result.status_code,200,result.json)
            self.assertIn('2 video(s)',result.json['message'])
            self.assertIn('0 video(s)',self.post('/api/youtube/watched-all',{'confirm':True}).json['message'])
        self.assertEqual(len(app.watched_bulk_candidates()),0)
        self.post('/api/youtube/watched-all/cancel',{})
        self.assertEqual(len(app.watched_bulk_candidates()),2)
    def test_rejected_session_blocks_enable_bulk_and_pauses_queue(self):
        self.job('one.mp4')
        with patch.object(app,'_v3_cookie_status',return_value={'valid':True}),patch.object(app,'check_cookie_session',return_value=('auth_expired','Renew cookies')):
            self.assertEqual(self.post('/api/youtube/watched-setting',{'enabled':True}).status_code,400)
            self.assertEqual(self.post('/api/youtube/watched-all',{'confirm':True}).status_code,400)
        with app.db() as conn:
            conn.execute("INSERT INTO youtube_watched_requests(job_id,video_id,origin,created_at) VALUES('one.mp4','abcdefghijk','bulk',?)",(app.now_iso(),))
        with patch.object(app,'watched_session_status',return_value={'state':'auth_expired'}),patch.object(app,'send_watched_request') as send:
            app.process_watched_request();send.assert_not_called()
        with app.db() as conn:self.assertEqual(conn.execute('SELECT status FROM youtube_watched_requests').fetchone()[0],'queued')
    def test_new_cookies_clear_stale_session_warning(self):
        p=self.cookie(int(time.time())+3600)
        with patch.object(app,'YOUTUBE_COOKIE_PATH',p):
            app.record_watched_session('auth_expired','Old session')
            self.assertEqual(app.watched_session_status()['state'],'auth_expired')
            p.write_text(p.read_text().replace('private-token','renewed-token'))
            self.assertEqual(app.watched_session_status()['state'],'unchecked')
    def test_bulk_is_admin_only_and_csrf_protected(self):
        self.assertEqual(self.client.post('/api/youtube/watched-all',json={'confirm':True}).status_code,400)
        with app.db() as conn:conn.execute("UPDATE users SET role='viewer'")
        with patch.object(app,'check_cookie_session') as check:
            for path in ['/api/youtube/watched-all','/api/youtube/watched-all/cancel','/api/youtube/watched-session']:
                self.assertNotEqual(self.post(path,{'confirm':True}).status_code,200)
            check.assert_not_called()
    def test_emby_pagination_uses_only_played_video_ids(self):
        pages=[{'Items':[{'Path':'/media/Channel/episode [abcdefghijk].mp4','UserData':{'Played':True}},
                         {'ProviderIds':{'YouTube':'bcdefghijkl'},'UserData':{'Played':False}}],'TotalRecordCount':3},
               {'Items':[{'ProviderIds':{'YouTube':'cdefghijklm'},'UserData':{'Played':True}}],'TotalRecordCount':3}]
        with patch.object(app,'emby_api_request',side_effect=[Mock(json=lambda:p) for p in []]) as api:
            api.side_effect=[Mock(json=Mock(return_value=p)) for p in pages]
            result=app.emby_played_youtube_ids('user1')
            self.assertEqual(result,{'abcdefghijk','cdefghijklm'})
            self.assertEqual(api.call_count,2)
            self.assertEqual(api.call_args.kwargs['params']['StartIndex'],2)
            self.assertEqual(api.call_args.kwargs['params']['IsPlayed'],'true')
    def test_emby_preview_and_confirm_selected_video(self):
        self.job('one.mp4');self.job('two.mp4',video_id='bcdefghijkl')
        with patch.object(app,'emby_played_youtube_ids',return_value={'abcdefghijk'}),patch.object(app,'check_cookie_session',return_value=('active','Signed in')) as check:
            preview=self.post('/api/youtube/watched-emby',{'user_id':'user1'})
            self.assertEqual(preview.json['count'],1);check.assert_not_called()
            response=self.post('/api/youtube/watched-emby',{'user_id':'user1','job_id':'two.mp4','confirm':True})
            self.assertIn('0 Emby-played',response.json['message'])
            response=self.post('/api/youtube/watched-emby',{'user_id':'user1','job_id':'one.mp4','confirm':True})
            self.assertIn('1 Emby-played',response.json['message'])
        with app.db() as conn:
            row=conn.execute('SELECT * FROM youtube_watched_requests').fetchone()
            self.assertEqual(row['origin'],'emby');self.assertEqual(row['job_id'],'one.mp4')
        self.post('/api/youtube/watched-all/cancel',{})
        with app.db() as conn:self.assertEqual(conn.execute('SELECT status FROM youtube_watched_requests').fetchone()[0],'cancelled')
    def test_emby_failure_never_queues_partial_matches(self):
        self.job('one.mp4')
        with patch.object(app,'emby_played_youtube_ids',side_effect=RuntimeError('API failed')):
            self.assertEqual(self.post('/api/youtube/watched-emby',{'user_id':'user1','confirm':True}).status_code,400)
        with app.db() as conn:self.assertEqual(conn.execute('SELECT COUNT(*) FROM youtube_watched_requests').fetchone()[0],0)
