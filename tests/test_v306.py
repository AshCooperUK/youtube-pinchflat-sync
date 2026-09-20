"""Completed-only latest video and persistent illustrated diagnostics."""
import unittest
from unittest.mock import patch

import test_v303 as fixtures

app = fixtures.app


class ActivityTests(unittest.TestCase):
    setUp = fixtures.DownloadTests.setUp
    job = fixtures.DownloadTests.job

    def test_latest_only_changes_after_successful_video_completion(self):
        previous = self.job('previous.mp4')
        for status in ('queued', 'downloading', 'processing', 'failed', 'skipped'):
            self.job(status + '.mp4', status=status, video_id='bcdefghijkl')
        self.job('audio.m4a', source='single', profile='audio')
        self.job('missing.mp4', exists=False)
        overview = self.client.get('/api/pinchflat/download-overview').get_json()
        self.assertEqual(overview['latest_download']['job_id'], 'previous.mp4')
        self.assertEqual(overview['last_downloaded']['job_id'], 'previous.mp4')
        self.assertEqual({row['state'] for row in overview['active']}, {'downloading','processing'})
        app.update_download_job('processing.mp4', status='completed', phase='Completed', finished_at=app.now_iso())
        self.assertEqual(app.pinchflat_download_overview()['last_downloaded']['job_id'], 'processing.mp4')
        previous.unlink()
        (app.DOWNLOAD_ROOT / 'processing.mp4').unlink()
        app.invalidate_video_inventory()
        self.assertIsNone(app.pinchflat_download_overview()['latest_download'])

    def test_worker_failure_has_thumbnail_and_does_not_replace_success(self):
        self.job('previous.mp4')
        self.job('failed-job', status='queued', video_id='xcSMAyfQNfA', exists=False)
        with patch.object(app, 'prepare_subscription_metadata'), \
                patch.object(app, '_v3_download_with_auth_retry', side_effect=RuntimeError('ERROR: [youtube] xcSMAyfQNfA: Video unavailable')):
            app.run_download_job('failed-job')
        failure = next(row for row in app.recent_activity() if row['title'] == 'Download failed')
        self.assertEqual(failure['job_id'], 'failed-job')
        self.assertEqual(failure['video_id'], 'xcSMAyfQNfA')
        self.assertEqual(failure['thumbnail_url'], 'https://i.ytimg.com/vi/xcSMAyfQNfA/hqdefault.jpg')
        self.assertIn('Video unavailable', failure['message'])
        self.assertEqual(failure['severity'], 'error')
        self.assertEqual(app.pinchflat_download_overview()['latest_download']['job_id'], 'previous.mp4')

    def test_active_phase_logging_does_not_log_every_progress_tick(self):
        self.job('active-job', status='queued', exists=False)
        for percent in (1, 10, 20, 80, 99):
            app.update_download_job('active-job', status='downloading', phase='Downloading from YouTube', progress=percent)
        app.update_download_job('active-job', status='processing', phase='FFmpeg · Merger')
        rows = [row for row in app.recent_activity() if row['event_type']=='download_progress']
        self.assertEqual(len(rows), 2)
        self.assertEqual({row['message'] for row in rows}, {'Downloading from YouTube','FFmpeg · Merger'})
        self.assertTrue(all(row['video_id']=='abcdefghijk' and row['thumbnail_url'] for row in rows))
        self.assertEqual(app.pinchflat_download_overview()['active'][0]['status'], 'FFmpeg · Merger')
        self.assertIsNone(app.pinchflat_download_overview()['latest_download'])

    def test_optional_metadata_notices_keep_video_identity_after_job_removal(self):
        self.job('notice-job', status='queued', exists=False)
        app.record_download_notice('notice-job', 'Subtitles unavailable: en')
        app.record_download_notice('notice-job', 'Subtitles unavailable: en')
        with app.db() as conn:
            conn.execute("DELETE FROM downloads WHERE job_id='notice-job'")
        rows = [row for row in app.recent_activity() if row['title']=='Download details']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['video_id'], 'abcdefghijk')
        self.assertEqual(rows[0]['video_title'], 'notice-job')
        self.assertIn('/abcdefghijk/', rows[0]['thumbnail_url'])

    def test_one_time_job_has_thumbnail_before_metadata_arrives(self):
        with patch.object(app.download_queue, 'put'):
            job_id, _ = app.enqueue_download('https://youtu.be/bcdefghijkl')
        queued = next(row for row in app.recent_activity() if row['title']=='Download queued')
        self.assertEqual(queued['video_id'], 'bcdefghijkl')
        self.assertEqual(queued['job_id'], job_id)
        self.assertEqual(app.pinchflat_download_overview()['waiting'][0]['video_id'], 'bcdefghijkl')

    def test_old_activity_matches_error_ids_and_exact_titles_without_guessing_duplicates(self):
        self.job('Unique title', video_id='abcdefghijk')
        self.job('duplicate-a', video_id='bcdefghijkl')
        self.job('duplicate-b', video_id='cdefghijklm')
        with app.db() as conn:
            conn.execute("UPDATE downloads SET title='Same title' WHERE job_id LIKE 'duplicate-%'")
            for message in ('Unique title completed.', 'Same title completed.', 'ERROR: [youtube] xcSMAyfQNfA: Video unavailable'):
                conn.execute("INSERT INTO activity(created_at,event_type,title,message,severity,channel_id) VALUES (?,'download','Old result',?,'error','UCsample')", (app.now_iso(), message))
        rows = {row['message']:row for row in app.recent_activity()}
        self.assertEqual(rows['Unique title completed.']['video_id'], 'abcdefghijk')
        self.assertFalse(rows['Same title completed.']['thumbnail_url'])
        self.assertEqual(rows['ERROR: [youtube] xcSMAyfQNfA: Video unavailable']['video_id'], 'xcSMAyfQNfA')
        self.assertEqual(app.activity_video_id_from_message('https://youtube.com/shorts/bcdefghijkl'), 'bcdefghijkl')
        self.assertEqual(app.activity_video_id_from_message('Video [bcdefghijkl].mp4 failed'), 'bcdefghijkl')

    def test_activity_schema_upgrade_preserves_existing_logs(self):
        with app.db() as conn:
            conn.executescript("""DROP TABLE activity;
                CREATE TABLE activity(id INTEGER PRIMARY KEY AUTOINCREMENT,created_at TEXT NOT NULL,
                event_type TEXT NOT NULL,title TEXT NOT NULL,message TEXT NOT NULL,severity TEXT NOT NULL DEFAULT 'info',channel_id TEXT);
                INSERT INTO activity(created_at,event_type,title,message) VALUES ('2026-09-20','sync','Old sync','Kept');""")
        app.init_db()
        app.log_activity('download', 'New failure', 'Unavailable', 'error', video_id='abcdefghijk', video_title='Original title')
        rows = app.recent_activity()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1]['message'], 'Kept')
        self.assertFalse(rows[1]['thumbnail_url'])
        self.assertIn('/abcdefghijk/', rows[0]['thumbnail_url'])

    def test_activity_api_is_admin_only_and_rejects_invalid_thumbnail_ids(self):
        app.log_activity('download', 'Download failed', '<script>unsafe text</script>', 'error', video_id='../../secret', video_title='A <tag>')
        response = self.client.get('/api/activity')
        self.assertEqual(response.status_code, 200)
        row = response.get_json()['activity'][0]
        self.assertFalse(row['thumbnail_url'])
        self.assertEqual(row['message'], '<script>unsafe text</script>')
        with app.db() as conn:
            conn.execute("UPDATE users SET role='viewer'")
        self.assertEqual(self.client.get('/api/activity').status_code, 302)


if __name__ == '__main__':
    unittest.main()
