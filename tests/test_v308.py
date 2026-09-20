"""Activity popup context and deterministic two-way subscription sorting."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest
from unittest.mock import patch

import test_v303 as fixtures
from test_v303 import app
from upload_guide import channel_sort_key


class ActivityContextTests(unittest.TestCase):
    setUp = fixtures.DownloadTests.setUp
    job = fixtures.DownloadTests.job

    def test_job_context_survives_deletion_and_channel_only_events_link(self):
        self.job('Episode', source='single')
        app.log_activity('download', 'Completed', 'Saved', job_id='Episode')
        with app.db() as conn:
            conn.execute('DELETE FROM downloads')
            conn.execute('DELETE FROM subscriptions')
        item = app.recent_activity()[0]
        self.assertEqual((item['channel_id'],item['channel_title']), ('UCsample','Example channel'))
        self.assertEqual(item['video_id'], 'abcdefghijk')
        self.assertEqual(item['channel_url'], 'https://www.youtube.com/channel/UCsample')
        app.log_activity('scan', 'Scan completed', 'No new videos', channel_id='UCsample', channel_title='Example channel')
        item = app.recent_activity()[0]
        self.assertEqual(item['channel_title'], 'Example channel')
        self.assertFalse(item['video_id'])

    def test_legacy_video_id_and_unique_title_resolve_the_channel(self):
        self.job('Original title')
        app.log_activity('download', 'Old failure', 'ERROR: [youtube] abcdefghijk: Unavailable')
        app.log_activity('download', 'Old result', 'Original title completed.')
        with patch.object(app, 'youtube_api_request', side_effect=AssertionError('Activity must stay local')):
            rows = self.client.get('/api/activity').get_json()['activity']
        for row in rows:
            self.assertEqual(row['channel_id'], 'UCsample')
            self.assertEqual(row['channel_title'], 'Example channel')
            self.assertEqual(row['video_title'], 'Original title')

    def test_remote_saved_video_has_channel_context_without_download(self):
        with app.db() as conn:
            conn.execute("""INSERT INTO saved_videos(user_id,video_id,title,channel_id,channel_title,video_url,created_at,updated_at)
                VALUES (1,'abcdefghijk','Remote <video>','UCremote','Remote & channel','https://youtu.be/abcdefghijk',?,?)""", (app.now_iso(),app.now_iso()))
        app.log_activity('like', 'Liked', 'Video liked', video_id='abcdefghijk')
        item = self.client.get('/api/activity').get_json()['activity'][0]
        self.assertEqual(item['channel_id'], 'UCremote')
        self.assertEqual(item['channel_title'], 'Remote & channel')
        self.assertEqual(item['video_title'], 'Remote <video>')

    def test_uncertain_channel_is_not_guessed_from_duplicate_titles(self):
        self.job('A',video_id='abcdefghijk')
        self.job('B',video_id='bcdefghijkl')
        with app.db() as conn:
            conn.execute("UPDATE downloads SET title='Same title'")
        app.log_activity('download', 'Old result', 'Same title completed.')
        item = app.recent_activity()[0]
        self.assertEqual(item['channel_id'], '')
        self.assertEqual(item['video_id'], '')

    def test_channel_markup_remains_data_and_urls_are_encoded(self):
        app.log_activity('scan','Updated','Saved',channel_id='UC<script>',channel_title='<img src=x onerror=alert(1)>')
        row = self.client.get('/api/activity').get_json()['activity'][0]
        self.assertEqual(row['channel_title'], '<img src=x onerror=alert(1)>')
        self.assertEqual(row['channel_url'],'https://www.youtube.com/channel/UC%3Cscript%3E')


class SortTests(unittest.TestCase):
    def test_every_heading_both_directions_and_guide_parity(self):
        # Deliberately conflict names with numeric size, resolution, dates and state.
        rows = [
            dict(channel_id='A',title='Alpha',profile_id='2160p',profile_name='4K',storage_bytes=9,range_mode='last_year',cutoff='2025-09-20',download_enabled=False,last_error='',dirty=False,status='disabled',first_seen_at='2026-09-01'),
            dict(channel_id='B',title='Beta',profile_id='720p',profile_name='HD',storage_bytes=1024,range_mode='today',cutoff='2026-09-20',download_enabled=True,last_error='Unavailable',dirty=True,status='enabled',first_seen_at='2026-09-20'),
        ]
        first = {'title':'A','enabled':'B','range':'B','media_profile':'B','cutoff':'A','storage':'B','error':'B','actions':'B','status':'A','newest':'B'}
        defaults = {'enabled':'desc','storage':'desc','actions':'desc','newest':'desc'}
        script = Path(__file__).resolve().parents[1]/'app/static/subscription-sort.js'
        if not shutil.which('node'): self.skipTest('Node is required for browser/guide sort parity')
        for field,expected in first.items():
            default = defaults.get(field,'asc')
            for mode,wanted in [(field,expected),(field+(':'+('asc' if default=='desc' else 'desc')), 'B' if expected=='A' else 'A')]:
                with self.subTest(mode=mode):
                    python_order = [r['channel_id'] for r in sorted(rows,key=lambda r:channel_sort_key(r,mode))]
                    self.assertEqual(python_order[0],wanted)
                    code = "global.window=global;require(process.argv[1]);const rows=JSON.parse(process.argv[2]);console.log(JSON.stringify(rows.sort((a,b)=>ytsdCompareChannels(a,b,process.argv[3])).map(r=>r.channel_id)));"
                    js_order = json.loads(subprocess.check_output(['node','-e',code,str(script),json.dumps(rows),mode],text=True))
                    self.assertEqual(js_order,python_order)
        # Pinned favourites stay first even for descending title sorts.
        rows[0]['favourite']=True
        self.assertEqual(sorted(rows,key=lambda r:channel_sort_key(r,'title:desc'))[0]['channel_id'],'A')

    def test_descending_prefix_names_and_resolution_use_natural_order(self):
        rows=[dict(channel_id=str(i),title=t) for i,t in enumerate(['News','Newsroom','Néws extra'])]
        self.assertEqual([r['title'] for r in sorted(rows,key=lambda r:channel_sort_key(r,'title:desc'))], ['Newsroom','Néws extra','News'])


if __name__ == '__main__':
    unittest.main()
