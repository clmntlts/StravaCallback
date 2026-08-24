import os
import sys
import unittest
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import (adapt, coach, dashboard, deliver, garmin, garmin_workout,
                    program, strava)
from engine.models import Activity, SessionSpec, WeekSummary


class TestCalendar(unittest.TestCase):
    def test_week_index_and_race(self):
        start = program.PROGRAM_START
        self.assertEqual(program.current_week_index(start), 1)
        self.assertEqual(program.current_week_index(program.week_start(9)), 9)
        # avant le début -> semaine 1 ; après la fin -> dernière semaine
        self.assertEqual(program.current_week_index(date(2020, 1, 1)), 1)
        self.assertEqual(program.current_week_index(date(2030, 1, 1)), program.N_WEEKS)
        self.assertGreater(program.days_to_race(start), 0)

    def test_program_start_snapped_to_monday(self):
        self.assertEqual(program.PROGRAM_START.weekday(), 0)

    def test_sunday_and_monday_target_same_upcoming_week(self):
        monday = program.week_start(5)                 # un lundi
        sunday_before = monday - timedelta(days=1)      # dimanche soir
        self.assertEqual(program.target_week_index(sunday_before),
                         program.target_week_index(monday))
        self.assertEqual(program.target_week_index(sunday_before), 5)


class TestACWR(unittest.TestCase):
    def _act(self, d, secs):
        return Activity(date=d, moving_time_s=secs, distance_m=0, sport="Run")

    def test_chronic_none_when_history_too_short(self):
        s = strava.summarize_week([], 1000, history_acts=[self._act("2026-09-01", 3600)],
                                  history_weeks=2)
        self.assertIsNone(s.chronic_hours)
        self.assertIsNone(s.acwr)

    def test_chronic_divides_by_actual_weeks(self):
        hist = [self._act("2026-09-01", 3600), self._act("2026-09-08", 3600),
                self._act("2026-09-15", 3600)]  # 3 h sur 3 semaines
        s = strava.summarize_week([], 1000, history_acts=hist, history_weeks=3)
        self.assertAlmostEqual(s.chronic_hours, 1.0, places=3)  # 3h / 3


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

    def test_fit_mime_is_octet_stream(self):
        self.assertEqual(deliver._guess_mime("01_easy.fit"), ("application", "octet-stream"))
        self.assertEqual(deliver._guess_mime("dashboard.html")[0], "text")


class TestGarminTranslate(unittest.TestCase):
    def test_interval_nests_repeat_block(self):
        w = garmin_workout.session_to_garmin(
            SessionSpec("threshold", {"reps": 3, "rep_min": 10, "rec_min": 2}))
        self.assertEqual(w["sport"], "RUNNING")
        self.assertGreater(w["estimatedDurationInSecs"], 0)
        reps = [s for s in w["steps"] if s.get("type") == "WorkoutRepeatStep"]
        self.assertEqual(len(reps), 1)
        self.assertEqual(reps[0]["repeatValue"], 3)
        self.assertEqual(len(reps[0]["steps"]), 2)  # effort + récup
        wu = w["steps"][0]
        self.assertEqual(wu["intensity"], "WARMUP")
        self.assertLess(wu["targetValueLow"], wu["targetValueHigh"])

    def test_step_orders_are_unique(self):
        w = garmin_workout.session_to_garmin(SessionSpec("backyard", {"loops": 4}))
        orders = []
        def walk(nodes):
            for n in nodes:
                orders.append(n["stepOrder"])
                if n.get("type") == "WorkoutRepeatStep":
                    walk(n["steps"])
        walk(w["steps"])
        self.assertEqual(len(orders), len(set(orders)))


class TestCoach(unittest.TestCase):
    def _fixture_analysis(self):
        acts = strava.load_activities_file(
            os.path.join(os.path.dirname(__file__), "fixtures", "last_week_sample.json"))
        today = date(2026, 9, 14)
        summ = strava.completed_week_summary(acts, 16000, today=today)
        runs = strava.completed_week_runs(acts, today=today)
        return coach.analyze(summ, runs)

    def test_analysis_has_content(self):
        a = self._fixture_analysis()
        self.assertTrue(a.headline)
        self.assertTrue(a.observations)
        self.assertTrue(a.recommendations)
        self.assertLessEqual(len(a.recommendations), 3)
        # les constats sont chiffrés (au moins un contient un chiffre)
        self.assertTrue(any(any(c.isdigit() for c in o) for o in a.observations))

    def test_single_fast_run_not_flagged_too_fast(self):
        ws = date(2026, 9, 7)
        runs = [Activity("2026-09-08", 3600, 10000, 40, "Run", 140),   # facile 6:00
                Activity("2026-09-09", 1800, 6000, 30, "Run", 165),    # qualité 5:00 (rapide)
                Activity("2026-09-13", 6000, 16000, 300, "Run", 145)]  # long facile
        summ = WeekSummary(3, sum(r.moving_time_s for r in runs), 32000, 370, 6000, 16200)
        a = coach.analyze(summ, runs, week_start=ws)
        self.assertFalse(any("ralentis" in r.lower() for r in a.recommendations))

    def test_backyard_is_distance_based(self):
        g = garmin_workout.session_to_garmin(SessionSpec("backyard", {"loops": 6}))
        rep = [s for s in g["steps"] if s.get("type") == "WorkoutRepeatStep"][0]
        kinds = [c["durationType"] for c in rep["steps"]]
        self.assertIn("DISTANCE", kinds)   # boucle à distance fixe (6,7 km)
        self.assertIn("TIME", kinds)       # repos = complément à l'heure

    def test_no_runs_message(self):
        empty = WeekSummary(0, 0, 0, 0, 0, 16000, data_available=True)
        a = coach.analyze(empty, [])
        self.assertIn("course", a.headline.lower())
        self.assertTrue(a.recommendations)

    def test_trends_from_history(self):
        acts = strava.load_activities_file(
            os.path.join(os.path.dirname(__file__), "fixtures", "last_week_sample.json"))
        today = date(2026, 9, 14)
        summ = strava.completed_week_summary(acts, 16000, today=today)
        weeks = strava.recent_completed_weeks(acts, today=today, n=4)
        ws = program.upcoming_monday(today) - timedelta(days=7)
        a = coach.analyze(summ, weeks[0], weeks[1:], week_start=ws)
        self.assertTrue(a.trends)
        self.assertTrue(any("Volume" in t for t in a.trends))
        # la fixture porte de la FC sur plusieurs semaines -> tendance EF présente
        self.assertTrue(any("aérobie" in t for t in a.trends))


class TestAthleteConfig(unittest.TestCase):
    def test_volume_scale_reduces_hours(self):
        full = program.planned_hours(program.week(9))
        half = program.planned_hours(program.build_week_scaled(9, 0.5))
        self.assertLess(half, full)
        self.assertGreater(half, 0)

    def test_three_days_drops_easy(self):
        self.assertNotIn("easy", program._roles_for_days(3))
        self.assertIn("easy", program._roles_for_days(4))
        w3 = program.build_week_scaled(9, 1.0, days=3)
        self.assertNotIn("easy", w3.sessions)
        self.assertIn("long", w3.sessions)

    def test_race_date_drives_start(self):
        # avec la date par défaut du profil, la semaine 34 se termine à la course
        self.assertEqual(program.week_start(program.N_WEEKS).weekday(), 0)  # lundi
        self.assertGreaterEqual((program.race_date() - program.week_start(program.N_WEEKS)).days, 0)

    def test_compression_keeps_shape(self):
        phases = {"Fondation", "Force-endurance", "Spécifique", "Pic", "Affûtage"}
        for N in (10, 16, 20, 28):
            sel = program._select(program._ROWS, N)
            taper_len = 3 if N >= 14 else 2
            self.assertEqual(len(sel), N)
            self.assertEqual([r[0] for r in sel], list(range(1, N + 1)))  # ré-indexé
            self.assertEqual({r[1] for r in sel}, phases)                 # toutes les phases
            self.assertEqual([r[1] for r in sel[-taper_len:]], ["Affûtage"] * taper_len)
            # décharges : rythme 3:1, jamais consécutives
            dl = [r[0] for r in sel if r[2]]
            self.assertTrue(all(b - a >= 2 for a, b in zip(dl, dl[1:])))

    def test_short_plans_do_not_hang(self):
        # régression : N=7/8 bouclait à l'infini dans _allocate
        for N in (4, 5, 6, 7, 8, 9):
            sel = program._select(program._ROWS, N)
            self.assertEqual(len(sel), N)

    def test_compression_noop_when_full(self):
        self.assertEqual(len(program._select(program._ROWS, program.TEMPLATE_WEEKS)),
                         program.TEMPLATE_WEEKS)


class TestOnboard(unittest.TestCase):
    def test_write_profile_sets_onboarded_and_preserves(self):
        import json
        import tempfile
        import generate
        from engine import config as cfg
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tf:
            tf.write('{"paces": {"easy": "6:00"}}')
            path = tf.name
        old = cfg.CONFIG_PATH
        try:
            cfg.CONFIG_PATH = path
            generate._write_profile({"race_date": "2027-03-15", "days_per_week": 3,
                                     "start_volume_h": None})
            data = json.load(open(path))
            self.assertTrue(data["onboarded"])
            self.assertEqual(data["race_date"], "2027-03-15")
            self.assertEqual(data["days_per_week"], 3)
            self.assertNotIn("start_volume_h", data)   # None ignoré
            self.assertIn("paces", data)               # préservé
        finally:
            cfg.CONFIG_PATH = old
            os.unlink(path)


class TestGarminConfig(unittest.TestCase):
    def test_not_configured_without_env(self):
        for k in ("GARMIN_CONSUMER_KEY", "GARMIN_CONSUMER_SECRET", "GARMIN_REFRESH_TOKEN"):
            os.environ.pop(k, None)
        self.assertFalse(garmin.is_configured())


if __name__ == "__main__":
    unittest.main()
