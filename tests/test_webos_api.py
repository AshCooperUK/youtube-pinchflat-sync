"""Pairing, authentication separation and signed range streaming for webOS."""
import unittest
import time
from unittest.mock import patch
from PIL import Image
import test_v303 as fixtures

app = fixtures.app


class WebosTests(unittest.TestCase):
    setUp = fixtures.DownloadTests.setUp
    job = fixtures.DownloadTests.job

    def pending(self):
        public = app.app.test_client()
        data = public.post('/api/webos/pair/start', json={}).get_json()
        self.assertTrue(data['ok'])
        return public, data

    def linked(self):
        public, pair = self.pending()
        approve = self.client.post('/tv-link', data={'_csrf': 'test-token', 'code': pair['code']})
        self.assertEqual(approve.status_code, 200)
        self.assertIn(b'TV approved', approve.data)
        result = public.post('/api/webos/pair/status', json={'secret': pair['secret']})
        self.assertEqual(result.status_code, 200, result.data)
        return public, {'Authorization': 'Bearer ' + result.json['token']}

    def test_pairing_needs_secret_browser_login_and_csrf(self):
        public, pair = self.pending()
        self.assertEqual(public.post('/api/webos/pair/start', data={}).status_code, 400)
        self.assertEqual(public.get('/tv-link').status_code, 302)
        self.assertEqual(self.client.post('/tv-link', data={'code': pair['code']}).status_code, 400)
        self.assertEqual(public.post('/api/webos/pair/status', json={'secret': pair['code']}).status_code, 410)
        self.assertEqual(public.post('/api/webos/pair/status', json={'secret': pair['secret']}).json['status'], 'pending')
        with app.db() as conn:
            conn.execute("UPDATE users SET role='viewer'")
        self.assertEqual(self.client.post('/tv-link', data={'_csrf': 'test-token', 'code': pair['code']}).status_code, 200)
        answer = public.post('/api/webos/pair/status', json={'secret': pair['secret']}).json
        self.assertEqual(answer['status'], 'approved')
        self.assertNotIn('csrf_token', answer)
        with app.db() as conn:
            stored = conn.execute('SELECT * FROM webos_devices').fetchone()
            self.assertNotEqual(stored['token_hash'], answer['token'])
        self.assertEqual(public.post('/api/webos/pair/status', json={'secret': pair['secret']}).status_code, 410)

    def test_cookie_and_bearer_authentication_stay_separate(self):
        public, auth = self.linked()
        self.assertEqual(self.client.get('/api/webos/session').status_code, 401)
        response = public.get('/api/webos/session', headers=auth)
        self.assertEqual(response.json['user_id'], '1')
        self.assertNotIn('csrf_token', response.json)
        self.assertNotIn('Set-Cookie', response.headers)
        self.assertEqual(response.headers['Cache-Control'], 'private, no-store')
        self.assertEqual(public.get('/api/tv/session', headers=auth).status_code, 302)
        self.assertEqual(public.post('/settings/downloader/repair-dates', json={}, headers=auth).status_code, 400)
        self.assertEqual(public.get('/api/webos/library?token=' + auth['Authorization'][7:]).status_code, 401)

    def test_preflight_and_local_origin_ignore_canonical_redirect(self):
        public = app.app.test_client()
        response = public.options('/api/webos/library', headers={'Origin': 'null', 'Access-Control-Request-Method': 'GET', 'Access-Control-Request-Headers': 'Authorization'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['Access-Control-Allow-Origin'], '*')
        self.assertNotIn('Access-Control-Allow-Credentials', response.headers)
        with patch.object(app, 'CANONICAL_REDIRECT', True), patch.object(app, 'ENV_APP_URL', 'https://remote.example.test'):
            self.assertEqual(public.get('/api/webos/info').status_code, 200)

    def test_read_only_catalogue_and_account_favourites(self):
        self.job('good.mp4')
        self.job('failed.mp4', status='failed')
        self.job('partial.mp4', status='processing')
        self.job('sound.m4a', profile='audio')
        with app.db() as conn:
            conn.execute('INSERT INTO favourite_channels(user_id,channel_id,channel_title,channel_url,created_at) VALUES(1,?,?,?,?)', ('UCsample', 'Example', '', app.now_iso()))
        public, auth = self.linked()
        listing = public.get('/api/webos/library?favourites=1', headers=auth).json
        self.assertEqual([x['id'] for x in listing['items']], ['good.mp4'])
        self.assertTrue(listing['items'][0]['favourite'])
        self.assertTrue(listing['items'][0]['stream_url'].startswith('/api/webos/media/'))
        self.assertNotIn(auth['Authorization'][7:], str(listing))
        self.assertTrue(public.get('/api/webos/channels', headers=auth).json['items'][0]['favourite'])

    def test_media_grants_scope_range_head_and_revocation(self):
        self.job('first.mp4').write_bytes(b'0123456789abcdefghij')
        self.job('second.mp4', video_id='secondvideo')
        public, auth = self.linked()
        url = public.get('/api/webos/videos/first.mp4', headers=auth).json['item']['stream_url']
        response = public.get(url, headers={'Range': 'bytes=5-9'})
        self.assertEqual(response.status_code, 206)
        self.assertEqual(response.data, b'56789')
        self.assertEqual(response.headers['Content-Range'], 'bytes 5-9/20')
        self.assertEqual(public.head(url).status_code, 200)
        self.assertEqual(public.get(url, headers={'Range': 'bytes=100-200'}).status_code, 416)
        self.assertEqual(public.get(url.replace('first.mp4', 'second.mp4')).status_code, 401)
        self.assertEqual(public.get(url.replace('/media/', '/artwork/')).status_code, 401)
        self.assertEqual(public.get('/api/webos/media/first.mp4').status_code, 401)
        self.assertEqual(public.post('/api/webos/signout', headers=auth, json={}).status_code, 200)
        self.assertEqual(public.get(url).status_code, 401)
        self.assertEqual(public.get('/api/webos/library', headers=auth).status_code, 401)

    def test_subtitle_conversion_and_local_artwork(self):
        path = self.job('external.mp4', source='single', video_id='media:generic:episode')
        path.with_suffix('.en.srt').write_text('1\n00:00:01,000 --> 00:00:03,000\nHello\n', encoding='utf-8')
        Image.new('RGB', (50, 50), 'green').save(path.with_suffix('.jpg'))
        public, auth = self.linked()
        item = public.get('/api/webos/videos/external.mp4', headers=auth).json['item']
        self.assertEqual(public.get(item['thumbnail_url']).status_code, 200)
        sub = public.get(item['subtitles'][0]['url'])
        self.assertEqual(sub.mimetype, 'text/vtt')
        self.assertTrue(sub.data.startswith(b'WEBVTT'))
        self.assertIn(b'00:00:01.000 --> 00:00:03.000', sub.data)
        channel = public.get('/api/webos/channels', headers=auth).json['items'][0]
        self.assertEqual(public.get(channel['thumbnail_url']).status_code, 200)

    def test_inactive_account_and_session_version_revoke_access(self):
        public, auth = self.linked()
        with app.db() as conn:
            conn.execute('UPDATE users SET active=0')
        self.assertEqual(public.get('/api/webos/session', headers=auth).status_code, 401)
        with app.db() as conn:
            conn.execute('UPDATE users SET active=1, session_version=2')
        self.assertEqual(public.get('/api/webos/session', headers=auth).status_code, 401)

    def test_pairing_limits_and_expiry(self):
        public, pair = self.pending()
        with app.db() as conn:
            conn.execute('UPDATE webos_pairing SET expires=?', (time.time() - 1,))
        self.assertEqual(public.post('/api/webos/pair/status', json={'secret': pair['secret']}).status_code, 410)
        for _ in range(11):
            self.assertEqual(public.post('/api/webos/pair/start', json={}).status_code, 200)
        self.assertEqual(public.post('/api/webos/pair/start', json={}).status_code, 429)

    def test_browser_revoke_only_owns_devices(self):
        public, auth = self.linked()
        with app.db() as conn:
            identifier = conn.execute('SELECT id FROM webos_devices').fetchone()['id']
        self.assertEqual(self.client.post('/tv-link', data={'_csrf': 'test-token', 'revoke': identifier}).status_code, 200)
        self.assertEqual(public.get('/api/webos/session', headers=auth).status_code, 401)

