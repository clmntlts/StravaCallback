import os
import sys
import unittest
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import (adapt, coach, dashboard, deliver, garmin, garmin_connect,
                    garmin_workout, program, strava, workouts)
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


class TestCrossTrainingLoad(unittest.TestCase):
    def test_cycling_counts_in_aerobic_not_run_volume(self):
        acts = [Activity("2026-09-08", 3600, 10000, 40, "Run"),
                Activity("2026-09-10", 7200, 40000, 300, "GravelRide")]
        hist = [Activity("2026-08-18", 3600, 10000, 0, "Run"),
                Activity("2026-08-25", 7200, 40000, 0, "GravelRide"),
                Activity("2026-09-01", 3600, 10000, 0, "Run")]
        s = strava.summarize_week(acts, 3600, history_acts=hist, history_weeks=3,
                                  cross_weight=0.5)
        self.assertEqual(s.n_runs, 1)                 # le vélo n'entre pas dans le volume course
        self.assertAlmostEqual(s.actual_hours, 1.0)   # course seule
        self.assertAlmostEqual(s.cross_hours, 2.0)    # 2 h de vélo
        self.assertAlmostEqual(s.aerobic_acute_hours, 1.0 + 0.5 * 2.0)  # 2.0 h équiv.
        self.assertIsNotNone(s.aerobic_chronic_hours)
        self.assertGreater(s.aerobic_acwr, 0)

    def test_weight_zero_ignores_cross(self):
        acts = [Activity("2026-09-08", 3600, 10000, 40, "Run"),
                Activity("2026-09-10", 7200, 40000, 300, "Ride")]
        s = strava.summarize_week(acts, 3600, cross_weight=0.0)
        self.assertAlmostEqual(s.aerobic_acute_hours, s.actual_hours)


class TestWeeklyActuals(unittest.TestCase):
    def test_buckets(self):
        acts = strava.load_activities_file(
            os.path.join(os.path.dirname(__file__), "fixtures", "last_week_sample.json"))
        today = date(2026, 9, 14)
        b = strava.weekly_actual_hours(acts, program.PROGRAM_START, program.N_WEEKS,
                                       today=today)
        cur = (today - program.PROGRAM_START).days // 7   # index de la semaine en cours
        # semaines échues : jamais None, et au moins une porte des heures réalisées
        self.assertTrue(all(b[i] is not None for i in range(cur + 1)))
        self.assertGreater(sum(b[i] for i in range(cur + 1)), 0)
        # semaines futures -> None (juste après la semaine en cours, et en fin de plan)
        self.assertIsNone(b[cur + 1])
        self.assertIsNone(b[-1])


class TestHistoryJson(unittest.TestCase):
    def _act(self, d, secs, dist_m=0, elev_m=0.0, sport="Run", hr=None):
        return Activity(date=d, moving_time_s=secs, distance_m=dist_m,
                        elevation_m=elev_m, sport=sport, avg_hr=hr)

    def test_daily_covers_every_day_including_zeros(self):
        start, end = date(2026, 9, 7), date(2026, 9, 14)  # lundi -> lundi, 7 jours
        h = strava.history_json([self._act("2026-09-08", 3600, 10000)], start, end)
        self.assertEqual(len(h["daily"]), 7)
        self.assertEqual(h["daily"][0]["date"], "2026-09-07")
        self.assertEqual(h["daily"][1]["hours"], 1.0)   # 2026-09-08
        self.assertEqual(h["daily"][0]["hours"], 0.0)   # jour sans activité

    def test_weekly_buckets_and_cumulative_elevation(self):
        start, end = date(2026, 9, 7), date(2026, 9, 21)  # 2 semaines pleines
        acts = [self._act("2026-09-08", 3600, 10000, elev_m=100),
                self._act("2026-09-15", 3600, 10000, elev_m=200)]
        h = strava.history_json(acts, start, end)
        self.assertEqual(len(h["weekly"]), 2)
        self.assertEqual(h["weekly"][0]["elevation_cumulative_m"], 100)
        self.assertEqual(h["weekly"][1]["elevation_cumulative_m"], 300)  # cumul, pas juste S2

    def test_avg_hr_none_when_no_hr_data_that_week(self):
        start, end = date(2026, 9, 7), date(2026, 9, 14)
        h = strava.history_json([self._act("2026-09-08", 3600, 10000, hr=None)], start, end)
        self.assertIsNone(h["weekly"][0]["avg_hr"])

    def test_avg_hr_averages_across_activities_with_hr(self):
        start, end = date(2026, 9, 7), date(2026, 9, 14)
        acts = [self._act("2026-09-08", 3600, hr=140), self._act("2026-09-09", 3600, hr=150)]
        h = strava.history_json(acts, start, end)
        self.assertAlmostEqual(h["weekly"][0]["avg_hr"], 145.0)

    def test_totals_match_sum_of_activities(self):
        start, end = date(2026, 9, 7), date(2026, 9, 14)
        acts = [self._act("2026-09-08", 3600, 10000, elev_m=50),
                self._act("2026-09-09", 1800, 5000, elev_m=25, sport="GravelRide")]
        h = strava.history_json(acts, start, end)
        self.assertAlmostEqual(h["totals"]["hours"], 1.5)
        self.assertAlmostEqual(h["totals"]["km"], 15.0)
        self.assertEqual(h["totals"]["elevation_m"], 75)
        self.assertEqual(h["totals"]["activities"], 2)

    def test_activities_outside_range_excluded(self):
        start, end = date(2026, 9, 7), date(2026, 9, 14)
        acts = [self._act("2026-09-06", 3600, 10000), self._act("2026-09-14", 3600, 10000)]
        h = strava.history_json(acts, start, end)  # [start, end) : les deux hors bornes
        self.assertEqual(h["totals"]["activities"], 0)


class TestDashboard(unittest.TestCase):
    def test_builds_html(self):
        res = adapt.adapt_week(program.week(9),
                               WeekSummary(3, 12000, 40000, 500, 5400, 16200,
                                           acute_hours=3.3, chronic_hours=3.3))
        actuals = [None] * program.N_WEEKS
        actuals[7] = 4.0
        html = dashboard.build(res, res and WeekSummary(3, 12000, 40000, 500, 5400, 16200),
                               actuals, today=date(2026, 11, 1))
        # [L3] revue pipeline 2026-08-26 : le graphe ne doit plus être en <svg>
        # inline (Gmail le vidait) mais en table HTML de barres.
        self.assertNotIn("<svg", html)
        self.assertIn('<table class="chart"', html)
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

    def test_easy_and_long_carry_heart_rate_target(self):
        # Angle mort [L7] de la revue pipeline 2026-08-26 : aucun test ne
        # vérifiait que les séances aérobies (garde-fou Z2) traduisent bien en
        # cible FC plutôt qu'en OPEN.
        lo, hi = workouts.hr_range("z2")
        for role, params in (("easy", {"minutes": 45}), ("long", {"minutes": 180})):
            with self.subTest(role=role):
                w = garmin_workout.session_to_garmin(SessionSpec(role, params))
                main = w["steps"][0]  # easy/long n'ont pas d'échauffement séparé
                self.assertEqual(main["targetType"], garmin_workout.TARGET_HEART_RATE)
                self.assertEqual(main["targetValueLow"], lo)
                self.assertEqual(main["targetValueHigh"], hi)


class TestGarminConnectTranslate(unittest.TestCase):
    def test_schema_top_level(self):
        w = garmin_connect.session_to_connect(SessionSpec("easy", {"minutes": 45}))
        self.assertEqual(w["sportType"]["sportTypeKey"], "running")
        self.assertGreater(w["estimatedDurationInSecs"], 0)
        self.assertEqual(len(w["workoutSegments"]), 1)
        self.assertTrue(w["workoutSegments"][0]["workoutSteps"])

    def _steps(self, w):
        return w["workoutSegments"][0]["workoutSteps"]

    def test_interval_nests_repeat_group(self):
        w = garmin_connect.session_to_connect(
            SessionSpec("threshold", {"reps": 3, "rep_min": 10, "rec_min": 2}))
        groups = [s for s in self._steps(w) if s.get("type") == "RepeatGroupDTO"]
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["numberOfIterations"], 3)
        self.assertEqual(groups[0]["endCondition"]["conditionTypeKey"], "iterations")
        self.assertEqual(len(groups[0]["workoutSteps"]), 2)  # effort + récup
        wu = self._steps(w)[0]
        self.assertEqual(wu["stepType"]["stepTypeKey"], "warmup")
        # cible d'allure : bornes en m/s, low (plus lent) < high (plus rapide)
        self.assertEqual(wu["targetType"]["workoutTargetTypeKey"], "pace.zone")
        self.assertLess(wu["targetValueOne"], wu["targetValueTwo"])

    def test_step_orders_unique_in_depth(self):
        w = garmin_connect.session_to_connect(SessionSpec("backyard", {"loops": 4}))
        orders = []

        def walk(nodes):
            for n in nodes:
                orders.append(n["stepOrder"])
                if n.get("type") == "RepeatGroupDTO":
                    walk(n["workoutSteps"])

        walk(self._steps(w))
        self.assertEqual(len(orders), len(set(orders)))

    def test_distance_step_uses_meters(self):
        w = garmin_connect.session_to_connect(SessionSpec("backyard", {"loops": 6}))
        group = [s for s in self._steps(w) if s.get("type") == "RepeatGroupDTO"][0]
        conds = [c["endCondition"]["conditionTypeKey"] for c in group["workoutSteps"]]
        self.assertIn("distance", conds)   # la boucle backyard est à distance fixe

    def test_easy_and_long_carry_heart_rate_target(self):
        # Angle mort [L7] de la revue pipeline 2026-08-26 : aucun test ne
        # vérifiait que les séances aérobies (garde-fou Z2) traduisent bien en
        # cible FC plutôt qu'en no.target.
        lo, hi = workouts.hr_range("z2")
        for role, params in (("easy", {"minutes": 45}), ("long", {"minutes": 180})):
            with self.subTest(role=role):
                w = garmin_connect.session_to_connect(SessionSpec(role, params))
                main = self._steps(w)[0]  # easy/long n'ont pas d'échauffement séparé
                self.assertEqual(main["targetType"]["workoutTargetTypeKey"], "heart.rate.zone")
                self.assertEqual(main["targetValueOne"], lo)
                self.assertEqual(main["targetValueTwo"], hi)

    def test_not_configured_without_env(self):
        for k in ("GARMIN_EMAIL", "GARMIN_PASSWORD", "GARMIN_TOKENS_BASE64"):
            os.environ.pop(k, None)
        self.assertFalse(garmin_connect.is_configured())

    def test_configured_via_token_only(self):
        for k in ("GARMIN_EMAIL", "GARMIN_PASSWORD"):
            os.environ.pop(k, None)
        os.environ["GARMIN_TOKENS_BASE64"] = "dummy-token"
        try:
            self.assertTrue(garmin_connect.is_configured())  # jeton seul suffit
        finally:
            os.environ.pop("GARMIN_TOKENS_BASE64", None)


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


class TestVolumeGovernor(unittest.TestCase):
    """[E2/E4/E5/E9] gouverneurs de charge actifs sur le plan nominal complet."""

    def test_deloads_indexed_on_recent_load(self):
        # Une décharge ayant >=1 semaine "build" avant elle doit être proche de
        # DELOAD_TARGET_FRAC x (moyenne des 3 dernières semaines "build") --
        # pas figée à la valeur brute du template, indépendamment de la charge
        # portée juste avant [E5].
        built = []
        for w in program.PROGRAM:
            if w.deload:
                prev_builds = [x for x in built if not x.deload][-3:]
                if prev_builds:
                    target = (sum(program.planned_hours(x) for x in prev_builds)
                              / len(prev_builds)) * program.DELOAD_TARGET_FRAC
                    self.assertAlmostEqual(program.planned_hours(w), target, delta=0.5)
            built.append(w)

    def test_no_jump_beyond_cap_outside_backyard_weeks(self):
        # [E4] anti-saut de charge hebdo total, actif même sur le plan non
        # compressé -- sauf sur une semaine de simu backyard (progression pilotée
        # par le nombre de boucles, pas par les heures totales, cf. [E1]).
        # Tolérance 0.15h : l'arrondi par séance (reps entiers, minutes/5) du
        # rééchantillonnage peut légèrement dépasser le plafond mathématique
        # exact sans que ce soit un vrai saut de charge.
        prev = None
        for w in program.PROGRAM:
            if prev is not None and not w.deload and not program._has_backyard(w):
                cap = (program.SMOOTH_CAP_POST_DELOAD if prev.deload
                       else program.SMOOTH_CAP)
                self.assertLessEqual(program.planned_hours(w),
                                     program.planned_hours(prev) * cap + 0.15)
            prev = w

    def test_b2b_growth_capped(self):
        # [E9] le rôle b2b suit le même plafond de progression phase-dépendant
        # que la sortie longue continue (adapt.long_growth), plus jamais illimité.
        prev = None
        for w in program.PROGRAM:
            if (prev is not None and not w.deload
                    and "b2b" in w.sessions and "b2b" in prev.sessions):
                cap = workouts.minutes(prev.sessions["b2b"]) * adapt.long_growth(w.phase)
                self.assertLessEqual(workouts.minutes(w.sessions["b2b"]), cap + 2.5)
            prev = w

    def test_backyard_weeks_not_rescaled_by_smoothing(self):
        # Régression [E1] : une semaine de simu backyard garde le nombre de
        # boucles du template (x VOLUME_SCALE arrondi), jamais rabotée par le
        # lissage du volume hebdo total.
        for idx, row in enumerate(program._ACTIVE_ROWS, start=1):
            w = program.week(idx)
            if program._has_backyard(w):
                expected = adapt._scaled_spec(
                    program._base_row_sessions(row)["long"], program.VOLUME_SCALE)
                self.assertEqual(w.sessions["long"].params["loops"],
                                 expected.params["loops"])

    def test_long_growth_specifique_pic_tightened(self):
        # [E8] resserré de 1.60 à 1.30 -- 3-6x la norme sûre sur la séance
        # continue la plus traumatisante du plan.
        self.assertEqual(adapt.long_growth("Spécifique"), 1.30)
        self.assertEqual(adapt.long_growth("Pic"), 1.30)


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

    def test_onboard_derives_paces_and_extras(self):
        import json
        import tempfile
        from argparse import Namespace
        import generate
        from engine import config as cfg
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tf:
            tf.write("{}")
            path = tf.name
        old = cfg.CONFIG_PATH
        try:
            cfg.CONFIG_PATH = path
            generate.cmd_onboard(Namespace(
                objective="18-24 yards", race_date="2027-04-24", plan_start=None,
                plan_weeks=None, days=4, start_volume=3.0, peak_volume=None,
                longest_run=90, cross_weight=0.7,
                ref_distance="10k", ref_time="44:00"))
            data = json.load(open(path))
            self.assertEqual(data["longest_run_min"], 90)
            self.assertEqual(data["cross_training_weight"], 0.7)
            self.assertIn("paces", data)
            self.assertIn("tempo", data["paces"])      # allures dérivées présentes
            self.assertTrue(data["onboarded"])
        finally:
            cfg.CONFIG_PATH = old
            os.unlink(path)


class TestPaceDerivation(unittest.TestCase):
    def test_derive_paces_from_10k(self):
        from engine import workouts
        p = workouts.derive_paces(10000, 44 * 60)   # 10 km en 44:00
        for k in ("recovery", "easy", "long", "yard", "steady", "tempo", "cruise"):
            self.assertIn(k, p)
        s = {k: workouts._pace_seconds(v) for k, v in p.items()}
        # ordre logique : cruise (rapide) < tempo < steady < easy < long < recovery
        self.assertLess(s["cruise"], s["tempo"])
        self.assertLess(s["tempo"], s["steady"])
        self.assertLess(s["steady"], s["easy"])
        self.assertLess(s["easy"], s["long"])
        self.assertLess(s["long"], s["recovery"])
        # seuil plausible pour un 10k en 44:00 (~4:20-4:45/km)
        self.assertTrue(260 <= s["tempo"] <= 285)

    def test_distance_and_time_parsers(self):
        import generate
        self.assertEqual(generate._parse_time_to_seconds("44:00"), 2640)
        self.assertEqual(generate._parse_time_to_seconds("1:30:00"), 5400)
        self.assertEqual(generate._parse_distance_to_m("10k"), 10000)
        self.assertEqual(generate._parse_distance_to_m("21.1km"), 21100)
        self.assertEqual(generate._parse_distance_to_m("5000m"), 5000)


class TestGarminConfig(unittest.TestCase):
    def test_not_configured_without_env(self):
        for k in ("GARMIN_CONSUMER_KEY", "GARMIN_CONSUMER_SECRET", "GARMIN_REFRESH_TOKEN"):
            os.environ.pop(k, None)
        self.assertFalse(garmin.is_configured())


if __name__ == "__main__":
    unittest.main()
