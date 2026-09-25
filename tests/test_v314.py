"""Subscription ordering by the latest successful video still on disk."""
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch
import test_v307 as fixtures
from test_v307 import app, catalogue


class LatestDownloadSortTests(unittest.TestCase):
    setUp = fixtures.GuideTests.setUp
    save_channel = fixtures.GuideTests.save_channel
    job = fixtures.GuideTests.job
    get = fixtures.GuideTests.get

    def finish(self, job, date):
        with app.db() as conn:
            conn.execute('UPDATE downloads SET finished_at=? WHERE job_id=?', (date, job))
        app.invalidate_video_inventory()

    def test_only_successful_existing_video_counts_and_removal_falls_back(self):
        self.job('old.mp4'); self.finish('old.mp4', '2026-09-20T12:00:00+01:00')
        new = self.job('new.mp4'); self.finish('new.mp4', '2026-09-20T11:30:00Z')
        for status in ('queued', 'downloading', 'processing', 'failed', 'skipped', 'cancelled'):
            self.job(status+'.mp4', status=status)
        self.job('audio.m4a', profile='audio')
        self.job('metadata.nfo'); self.job('subtitles.vtt')
        self.job('missing.mp4', exists=False)
        self.assertEqual(app.latest_channel_downloads(), {'UCsample':1789903800000})
        new.unlink(); app.invalidate_video_inventory()
        self.assertEqual(app.latest_channel_downloads(), {'UCsample':1789902000000})
        (app.DOWNLOAD_ROOT/'old.mp4').unlink(); app.invalidate_video_inventory()
        self.assertEqual(app.latest_channel_downloads(), {})

    def test_missing_dates_stay_unknown_and_channel_ids_do_not_mix(self):
        self.job('unknown.mp4'); self.finish('unknown.mp4', '')
        self.job('invalid.mp4'); self.finish('invalid.mp4', 'not-a-date')
        self.job('single.mp4', source='single'); self.finish('single.mp4', '2026-09-20T11:00:00Z')
        with app.db() as conn:
            conn.execute("UPDATE downloads SET channel_id='UCanother' WHERE job_id='single.mp4'")
        self.assertEqual(app.latest_channel_downloads(), {'UCanother':1789902000000})

    def test_newest_and_oldest_browser_and_guide_order_match(self):
        rows = [dict(channel_id='none', title='A missing', latest_download_at=''),
                dict(channel_id='old', title='Old', latest_download_at=1000),
                dict(channel_id='new', title='New', latest_download_at=5000),
                dict(channel_id='tie', title='Z tie', latest_download_at=5000)]
        script = Path(__file__).resolve().parents[1]/'app/static/subscription-sort.js'
        code = "global.window=global;require(process.argv[1]);const rows=JSON.parse(process.argv[2]);console.log(JSON.stringify(rows.sort((a,b)=>ytsdCompareChannels(a,b,process.argv[3])).map(r=>r.channel_id)));"
        for mode, expected in [('latest_download', ['new','tie','old','none']), ('latest_download:asc', ['old','new','tie','none'])]:
            self.assertEqual([r['channel_id'] for r in sorted(rows, key=lambda r:catalogue.channel_sort_key(r,mode))], expected)
            self.assertEqual(json.loads(subprocess.check_output(['node','-e',code,str(script),json.dumps(rows),mode],text=True)),expected)

    def test_dashboard_poll_and_guide_share_completion_timestamp(self):
        self.job('episode.mp4'); self.finish('episode.mp4', '2026-09-20T11:00:00Z')
        overview = self.client.get('/api/pinchflat/download-overview?limit=0').get_json()
        self.assertEqual(overview['channel_latest_downloads']['UCsample'],1789902000000)
        guide = self.get(sort='latest_download')
        self.assertEqual(guide['channels'][0]['latest_download_at'],1789902000000)
        # Template carries the same timestamp before polling starts.
        with patch.object(app, 'youtube_account_stats_cached', return_value={'available':False}):
            page = self.client.get('/').get_data(as_text=True)
        self.assertIn('data-latest-download="1789902000000"',page)
        self.assertIn('value="latest_download:asc"',page)
