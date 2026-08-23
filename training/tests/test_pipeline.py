import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import adapt, dashboard, deliver, program, strava
from engine.models import WeekSummary


class TestCalendar(unittest.TestCase):
    def test_week_index_and_race(self):
        start = program.PROGRAM_START
        self.assertEqual(program.current_week_index(start), 1)
        self.assertEqual(program.current_week_index(program.week_start(9)), 9)
        # avant le début -> semaine 1 ; après la fin -> dernière semaine
        self.assertEqual(program.current_week_index(date(2020, 1, 1)), 1)
        self.assertEqual(program.current_week_index(date(2030, 1, 1)), program.N_WEEKS)
        self.assertGreater(program.days_to_race(start), 0)


class TestWeeklyActuals(unittest.TestCase):
    def test_buckets(self):
        acts = strava.load_activities_file(
            os.path.join(os.path.dirname(__file__), "fixtures", "last_week_sample.json"))
        b = strava.weekly_actual_hours(acts, program.PROGRAM_START, program.N_WEEKS,
                                       today=date(2026, 9, 14))
        self.assertGreater(b[0], 0)         # semaine 1 : des heures
        self.assertEqual(b[2], 0.0)         # semaine 3 (en cours) : échue -> 0
        self.assertIsNone(b[10])            # semaine future -> None


class TestDashboard(unittest.TestCase):
    def test_builds_html(self):
        res = adapt.adapt_week(program.week(9),
                               WeekSummary(3, 12000, 40000, 500, 5400, 16200,
                                           acute_hours=3.3, chronic_hours=3.3))
        actuals = [None] * program.N_WEEKS
        actuals[7] = 4.0
        html = dashboard.build(res, res and WeekSummary(3, 12000, 40000, 500, 5400, 16200),
                               actuals, today=date(2026, 11, 1))
        self.assertIn("<svg", html)
        self.assertIn("Semaine 9", html)
        self.assertIn("<title>", html)


class TestDeliverGuards(unittest.TestCase):
    def test_missing_env_raises(self):
        for k in ("GMAIL_ADDRESS", "GMAIL_APP_PASSWORD", "MAIL_TO"):
            os.environ.pop(k, None)
        with self.assertRaises(RuntimeError):
            deliver.send_email("s", "<p>x</p>", attachments=[])


if __name__ == "__main__":
    unittest.main()
