"""Offline coverage for experimental watched requests. No account mutations."""
import unittest
from unittest.mock import patch,Mock
import subprocess
from pathlib import Path
import test_v303 as fixtures
from watched_status import send_watched_request
app=fixtures.app

class WatchedTests(unittest.TestCase):
    def setUp(self):
        fixtures.DownloadTests.setUp(self)
        for target,attribute,result in [(app,'cookie_session_file_status',('unchecked','Cookie file present')),
            (app,'check_cookie_session',('active','Signed in'))]:
            patcher=patch.object(target,attribute,return_value=result)
            patcher.start();self.addCleanup(patcher.stop)
        patcher=patch('watched_status.check_cookie_session',return_value=('active','Signed in'))
        patcher.start();self.addCleanup(patcher.stop)
    job=fixtures.DownloadTests.job

    def post(self,path,payload):
        return self.client.post(path,json=payload,headers={'X-CSRF-Token':'test-token'})

    def test_manual_request_deduplicates_and_keeps_download_completed(self):
        self.job('test.mp4')
        self.assertFalse(self.client.get('/api/youtube/watched-test').json['enabled'])
        with patch.object(app,'_v3_cookie_status',return_value={'valid':True}):
            one=self.post('/api/youtube/watched-test',{'job_id':'test.mp4'})
            two=self.post('/api/youtube/watched-test',{'job_id':'test.mp4'})
            self.assertEqual(one.status_code,200,one.json)
            self.assertEqual(one.json['request_id'],two.json['request_id'])
            with patch.object(app,'send_watched_request',return_value=('failed','Network failure')) as send:
                app.process_watched_request();send.assert_called_once()
                app.process_watched_request();send.assert_called_once()
        status=self.client.get('/api/youtube/watched-test').json
        self.assertEqual(status['requests'][0]['status'],'failed')
        self.assertEqual(app.watched_download_job('test.mp4')['status'],'completed')
        self.assertTrue(any(x['event_type']=='youtube_watched' for x in self.client.get('/api/activity?filter=errors').json['activity']))

    def test_invalid_targets_cookies_and_permissions(self):
        self.job('incomplete.mp4',status='processing')
        self.job('external.mp4',video_id='media:bbc:id')
        self.job('missing.mp4',exists=False)
        self.job('good.mp4')
        with patch.object(app,'_v3_cookie_status',return_value={'valid':True}):
            for name in ['incomplete.mp4','external.mp4','missing.mp4','unknown']:
                self.assertEqual(self.post('/api/youtube/watched-test',{'job_id':name}).status_code,400)
        with patch.object(app,'_v3_cookie_status',return_value={'valid':False}):
            self.assertEqual(self.post('/api/youtube/watched-test',{'job_id':'good.mp4'}).status_code,400)
            self.assertEqual(self.post('/api/youtube/watched-setting',{'enabled':True}).status_code,400)
        self.assertEqual(self.client.post('/api/youtube/watched-test',json={'job_id':'good.mp4'}).status_code,400)
        with app.db() as conn:conn.execute("UPDATE users SET role='viewer'")
        with patch.object(app,'enqueue_watched_request') as enqueue:
            self.assertNotEqual(self.post('/api/youtube/watched-test',{'job_id':'good.mp4'}).status_code,200)
            self.assertNotEqual(self.client.get('/api/youtube/watched-test').status_code,200)
            enqueue.assert_not_called()

    def test_auto_opt_in_and_turn_off_cancels_pending(self):
        self.job('test.mp4')
        with patch.object(app,'_v3_cookie_status',return_value={'valid':True}):
            app.automatic_watched_request('test.mp4')
            self.assertEqual(self.client.get('/api/youtube/watched-test').json['requests'],[])
            self.assertEqual(self.post('/api/youtube/watched-setting',{'enabled':True}).status_code,200)
            app.automatic_watched_request('test.mp4');app.automatic_watched_request('test.mp4')
            self.assertEqual(len(self.client.get('/api/youtube/watched-test').json['requests']),1)
            self.post('/api/youtube/watched-setting',{'enabled':False})
            self.assertEqual(self.client.get('/api/youtube/watched-test').json['requests'][0]['status'],'cancelled')
        with patch.object(app,'setting_bool',side_effect=RuntimeError('DB issue')):
            app.automatic_watched_request('test.mp4')
        self.assertEqual(app.watched_download_job('test.mp4')['status'],'completed')

    def test_subprocess_has_timeout_no_download_and_redacts_output(self):
        cookies=Path(self.tmp.name)/'cookies.txt';cookies.write_text('private-cookie')
        cases=[(0,'Marking fully watched','sent'),(0,'Marking fully watched\nWARNING: Unable to mark watched secret','failed'),(0,'No marking happened','unverified'),(1,'ERROR secret','failed')]
        for code,output,status in cases:
            with patch('watched_status.subprocess.run',return_value=Mock(returncode=code,stdout=output,stderr='')) as run:
                actual,message=send_watched_request('abcdefghijk',cookies)
                self.assertEqual(actual,status);self.assertNotIn('secret',message)
                command=run.call_args.args[0]
                self.assertIn('--simulate',command);self.assertIn('--ignore-config',command)
                self.assertEqual(run.call_args.kwargs['timeout'],90)
                self.assertFalse(Path(command[command.index('--cookies')+1]).exists())
        with patch('watched_status.subprocess.run',side_effect=subprocess.TimeoutExpired('yt-dlp',90)):
            self.assertEqual(send_watched_request('abcdefghijk',cookies)[0],'failed')
        self.assertEqual(cookies.read_text(),'private-cookie')
