from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest

from activity import ActivityTracker, load_activity, save_activity
TEST_IP = "8.8.8.8"


class UsageTests(unittest.TestCase):
    def setUp(self):
        self.tracker = ActivityTracker()
        self.start = time.time()

    def sample(self, offset, processes):
        self.tracker.observe(processes, wall_time=self.start + offset, tick=10 + offset)

    def test_counts_only_observed_running_intervals_and_records_end(self):
        self.sample(0, {})
        self.sample(2, {"Demo": (7,)})
        self.sample(4, {"Demo": (7,)})
        self.sample(6, {"Demo": ()})
        usage = self.tracker.records["Demo"]
        session, = self.tracker.history
        self.assertEqual(usage.total, 2)
        self.assertEqual(usage.starts, 1)
        self.assertEqual(session.origin, "observed")
        self.assertEqual(session.status, "closed")
        self.assertEqual(session.ended_at, self.start + 6)
        self.assertFalse(session.checked_ip)

    def test_read_failure_does_not_invent_close_or_runtime(self):
        self.sample(0, {"Demo": (7,)})
        self.sample(2, {"Demo": (7,)})
        self.sample(4, None)
        self.sample(30, {})
        session, = self.tracker.history
        self.assertEqual(session.origin, "already_running")
        self.assertEqual(session.status, "interrupted")
        self.assertEqual(session.ended_at, 0)
        self.assertEqual(session.last_seen, self.start + 2)
        self.assertEqual(session.seconds, 2)

    def test_guarded_launch_upgrades_the_same_observed_pid_without_duplication(self):
        self.sample(0, {})
        self.sample(2, {"Demo": (7,)})
        self.tracker.record_guarded_launch("Demo", 7, self.start + 1, TEST_IP)
        self.sample(4, {"Demo": (7,)})
        session, = self.tracker.history
        self.assertEqual(session.origin, "guarded")
        self.assertEqual(session.started_at, self.start + 1)
        self.assertEqual(session.checked_ip, TEST_IP)
        self.assertEqual(session.pid, 7)
        self.assertEqual(self.tracker.records["Demo"].starts, 1)

    def test_distinct_process_is_not_marked_as_vpn_verified(self):
        self.sample(0, {})
        self.tracker.record_guarded_launch("Demo", 7, self.start + 1, TEST_IP)
        self.sample(2, {"Demo": (8,)})
        unknown, guarded = self.tracker.history
        self.assertEqual(guarded.status, "interrupted")
        self.assertEqual(guarded.origin, "guarded")
        self.assertEqual(unknown.origin, "observed")
        self.assertFalse(unknown.checked_ip)

    def test_persistence_marks_open_saved_history_as_interrupted_after_relaunch(self):
        self.sample(0, {})
        self.tracker.record_guarded_launch("Demo", 7, self.start + 1, TEST_IP)
        self.sample(2, {"Demo": (7,)})
        self.sample(4, {"Demo": (7,)})
        with TemporaryDirectory() as folder:
            path = Path(folder) / "activity.json"
            save_activity(self.tracker, path)
            loaded = load_activity(path)
        self.assertEqual(loaded.records["Demo"].total, 2)
        session, = loaded.history
        self.assertEqual(session.status, "interrupted")
        self.assertEqual(session.last_seen, self.start + 4)
        self.assertEqual(session.checked_ip, TEST_IP)
        self.assertEqual(loaded.open_sessions, {})

    def test_day_boundary_splits_elapsed_time(self):
        self.start = datetime(2025, 11, 24, 23, 59, 59).timestamp()
        self.sample(0, {"Demo": (7,)})
        self.sample(2, {"Demo": (7,)})
        self.assertEqual(self.tracker.records["Demo"].days, {"2025-11-24": 1, "2025-11-25": 1})
