"""TV catalogue boundaries and the existing authenticated range-stream contract."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import test_v303 as fixtures

app = fixtures.app


class TvApiTests(unittest.TestCase):
    setUp = fixtures.DownloadTests.setUp
    job = fixtures.DownloadTests.job

    def test_session_contract_and_viewer_access(self):
        with app.db() as conn:
            conn.execute("UPDATE users SET role='viewer'")
        response = self.client.get('/api/tv/session')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['api_version'], 1)
        self.assertEqual(response.json['user_id'], '1')
        self.assertEqual(response.json['server_version'], app.VERSION)
        self.assertEqual(response.json['csrf_token'], 'test-token')
        self.assertEqual(response.headers['Cache-Control'], 'private, no-store')
        self.assertEqual(self.client.get('/api/tv/library').status_code, 200)

    def test_catalogue_excludes_incomplete_missing_sidecars_audio_and_symlinks(self):
        good = self.job('good.mp4')
        self.job('failed.mp4', status='failed')
        self.job('working.mp4', status='processing')
        self.job('missing.mp4', exists=False)
        self.job('audio.m4a', profile='audio')
        self.job('audio-video.mp4', profile='audio')
        self.job('image.jpg')
        self.job('subtitles.vtt')
        self.job('file.info.json')
        self.job('fragment.f137.mp4')
        self.job('file.part.mp4')
        self.job('file.temp.mp4')
        self.job('.hidden.mp4')
        self.job('duplicate.mp4', exists=False)
        outside = Path(self.tmp.name) / 'outside.mp4'
        outside.write_bytes(b'private')
        linked = self.job('linked.mp4', exists=False)
        linked.symlink_to(outside)
        with app.db() as conn:
            conn.execute("UPDATE downloads SET output_path=? WHERE job_id='duplicate.mp4'", (str(good),))
        result = self.client.get('/api/tv/library').json
        self.assertEqual(result['total'], 1)
        self.assertNotIn('output_path', result['items'][0])
        self.assertNotIn(str(app.DOWNLOAD_ROOT), json.dumps(result))

    def test_pagination_has_no_100_download_ceiling(self):
        for index in range(105):
            self.job(f'{index:03d}.mp4', video_id=f'{index:011d}')
        first = self.client.get('/api/tv/library?limit=100').json
        second = self.client.get('/api/tv/library?limit=100&offset=100').json
        self.assertEqual(first['total'], 105)
        self.assertEqual(len(first['items']), 100)
        self.assertEqual(first['next_offset'], 100)
        self.assertEqual(len(second['items']), 5)
        self.assertIsNone(second['next_offset'])
        self.assertFalse(set(x['id'] for x in first['items']) & set(x['id'] for x in second['items']))
        self.assertEqual(self.client.get('/api/tv/library?offset=invalid').status_code, 400)

    def test_external_one_time_metadata_channel_filter_and_local_artwork(self):
        path = self.job('episode.mp4', source='single', video_id='media:generic:episode')
        path.with_suffix('.jpg').write_bytes(b'picture')
        metadata = {'extractor_key': 'generic', 'title': 'Episode title', 'description': 'Episode description',
                    'duration': 1234, 'upload_date': '20260924', 'uploader': 'Programme'}
        with app.db() as conn:
            conn.execute("UPDATE downloads SET channel_id=NULL, channel_title='Programme',metadata_json=?", (json.dumps(metadata),))
        result = self.client.get('/api/tv/library?channel=one-time').json
        item = result['items'][0]
        self.assertEqual(item['duration_seconds'], 1234)
        self.assertEqual(item['description'], 'Episode description')
        self.assertTrue(item['published_at'].startswith('2026-09-24'))
        self.assertEqual(self.client.get(item['thumbnail_url']).data, b'picture')
        self.assertEqual(self.client.get(item['stream_url']).data, b'fixture-video')
        self.assertEqual(self.client.get('/api/tv/channels').json['items'][0]['id'], 'one-time')

    def test_subtitle_tracks_are_scoped_to_exact_video_and_directory(self):
        path = self.job('episode.mp4')
        path.with_suffix('.en.vtt').write_text('WEBVTT\n\n00:00.000 --> 00:01.000\nHello\n')
        path.with_suffix('.fr.srt').write_text('1\n00:00:00,000 --> 00:00:01,000\nBonjour\n')
        (path.parent / 'different.en.vtt').write_text('other')
        outside = Path(self.tmp.name) / 'outside.vtt'
        outside.write_text('private')
        path.with_suffix('.secret.vtt').symlink_to(outside)
        item = self.client.get('/api/tv/videos/episode.mp4').json['item']
        self.assertEqual(len(item['subtitles']), 2)
        self.assertEqual([t['language'] for t in item['subtitles']], ['en', 'fr'])
        for sub in item['subtitles']:
            response = self.client.get(sub['url'])
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers['Cache-Control'], 'private, no-store')
        self.assertEqual(self.client.get('/api/tv/subtitles/episode.mp4/99').status_code, 404)

    def test_favourites_are_account_scoped(self):
        self.job('favourite.mp4')
        result = self.client.post('/api/favourites/channel/toggle', json={'channel_id': 'UCsample', 'channel_title': 'Example channel'}, headers={'X-CSRF-Token': 'test-token'})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(self.client.get('/api/tv/library?favourites=1').json['total'], 1)
        self.assertTrue(self.client.get('/api/tv/channels').json['items'][0]['favourite'])
        with app.db() as conn:
            conn.execute("INSERT INTO users(username,password_hash,role,created_at) VALUES ('second','unused','viewer',?)", (app.now_iso(),))
        with self.client.session_transaction() as session:
            session['auth_user_id'] = 2
        self.assertEqual(self.client.get('/api/tv/library?favourites=1').json['total'], 0)

    def test_range_head_and_expired_session(self):
        path = self.job('range.mp4')
        path.write_bytes(bytes(range(256)) * 32)
        response = self.client.get('/downloads/range.mp4/media', headers={'Range': 'bytes=1024-2047'})
        self.assertEqual(response.status_code, 206)
        self.assertEqual(response.headers['Content-Range'], 'bytes 1024-2047/8192')
        self.assertEqual(len(response.data), 1024)
        self.assertEqual(self.client.head('/downloads/range.mp4/media').headers['Content-Length'], '8192')
        self.assertEqual(self.client.get('/downloads/range.mp4/media', headers={'Range': 'bytes=99999-'}).status_code, 416)
        with app.db() as conn:
            conn.execute('UPDATE users SET session_version=2 WHERE id=1')
        for url in ['/api/tv/library', '/api/tv/channels', '/api/tv/videos/range.mp4', '/downloads/range.mp4/media']:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302)
            self.assertTrue(response.headers['Location'].endswith('/login'))

    def test_recently_removed_file_disappears_even_with_cached_inventory(self):
        path = self.job('deleted.mp4')
        self.assertEqual(self.client.get('/api/tv/library').json['total'], 1)
        path.unlink()
        self.assertEqual(self.client.get('/api/tv/library').json['total'], 0)
        self.assertEqual(self.client.get('/api/tv/videos/deleted.mp4').status_code, 404)

    def test_continue_ids_filter_and_no_remote_metadata_calls(self):
        self.job('first.mp4')
        self.job('second.mp4')
        with patch.object(app, 'youtube_api_request', side_effect=AssertionError('TV browse contacted YouTube')):
            result = self.client.get('/api/tv/library?id=second.mp4').json
        self.assertEqual([item['id'] for item in result['items']], ['second.mp4'])
        self.assertEqual(self.client.get('/api/tv/library?' + '&'.join('id=x' for _ in range(101))).status_code, 400)


if __name__ == '__main__':
    unittest.main()
