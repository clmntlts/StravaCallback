import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import adapt, program, workouts
from engine.models import WeekSummary


def summary(adherence, planned_h=4.5, longest_min=90, acwr=None):
    planned_s = int(planned_h * 3600)
    total_s = int(planned_s * adherence)
    acute = total_s / 3600.0
    chronic = (acute / acwr) if acwr else None
    return WeekSummary(
        n_runs=3, total_time_s=total_s, total_dist_m=40000, total_elev_m=500,
        longest_run_s=longest_min * 60, planned_time_s=planned_s,
        acute_hours=acute, chronic_hours=chronic,
    )


class TestBands(unittest.TestCase):
    def test_nominal_keeps_program_when_long_history_sufficient(self):
        # plus longue récente élevée -> le plafond ne mord pas -> programme tel quel
        w = program.week(9)
        res = adapt.adapt_week(w, summary(1.0, longest_min=240))
        self.assertEqual(res.band, "nominal")
        self.assertEqual(res.adjustments, [])
        self.assertEqual(workouts.minutes(res.week.sessions["long"]),
                         workouts.minutes(program.week(9).sessions["long"]))

    def test_long_cap_applies_even_in_nominal(self):
        # LE fix de sécurité : plus longue récente faible -> plafond même en nominal
        res = adapt.adapt_week(program.week(9), summary(1.0, longest_min=90))
        self.assertEqual(res.band, "nominal")
        cap = 90 * adapt.long_growth(program.week(9).phase)
        self.assertLessEqual(workouts.minutes(res.week.sessions["long"]), cap + 2.5)
        self.assertTrue(any(a.role == "long" for a in res.adjustments))

    def test_consolide_tempers_and_caps_long(self):
        res = adapt.adapt_week(program.week(9), summary(0.73, longest_min=90))
        self.assertEqual(res.band, "consolide")
        cap = 90 * adapt.long_growth(program.week(9).phase)
        self.assertLessEqual(workouts.minutes(res.week.sessions["long"]), cap + 2.5)
        self.assertTrue(any(a.role == "long" for a in res.adjustments))

    def test_reprise_regresses(self):
        res = adapt.adapt_week(program.week(9), summary(0.4, longest_min=60))
        self.assertEqual(res.band, "reprise")
        self.assertLess(workouts.minutes(res.week.sessions["easy"]),
                        workouts.minutes(program.week(9).sessions["easy"]))

    def test_reprise_scale_is_proportional(self):
        self.assertAlmostEqual(adapt._band_and_scale(0.20)[1], 0.50, places=2)
        self.assertAlmostEqual(adapt._band_and_scale(0.55)[1], 0.75, places=2)

    def test_rolling_longest_relaxes_cap(self):
        base = dict(n_runs=3, total_time_s=12000, total_dist_m=40000,
                    total_elev_m=300, longest_run_s=40 * 60, planned_time_s=16200)
        l_no = workouts.minutes(adapt.adapt_week(
            program.week(9), WeekSummary(**base)).week.sessions["long"])
        l_roll = workouts.minutes(adapt.adapt_week(
            program.week(9), WeekSummary(**base, rolling_longest_s=180 * 60)).week.sessions["long"])
        self.assertGreater(l_roll, l_no)  # une longue récente relâche le plafond

    def test_vigilance_no_overdose(self):
        res = adapt.adapt_week(program.week(9), summary(1.35))
        self.assertEqual(res.band, "vigilance")
        # pas d'augmentation par rapport au nominal
        self.assertLessEqual(program.planned_hours(res.week),
                             program.planned_hours(program.week(9)) + 0.01)


class TestGuards(unittest.TestCase):
    def test_deload_is_untouched(self):
        w = program.week(4)  # décharge
        res = adapt.adapt_week(w, summary(0.3))  # même très mauvaise adhérence
        self.assertEqual(res.band, "deload")
        self.assertEqual(res.adjustments, [])
        for role in w.sessions:
            self.assertEqual(workouts.label(res.week.sessions[role]),
                             workouts.label(w.sessions[role]))

    def test_high_acwr_brakes_and_downgrades_quality(self):
        res = adapt.adapt_week(program.week(9), summary(1.0, acwr=1.7))
        self.assertLessEqual(res.scale, 0.8)
        self.assertEqual(res.week.sessions["quality"].template, "easy")

    def test_structure_preserved(self):
        """Les rôles ne changent jamais ; les types non plus (hors downgrade)."""
        original = program.week(9)
        res = adapt.adapt_week(original, summary(0.5))
        self.assertEqual(set(res.week.sessions), set(original.sessions))
        for role in original.sessions:
            self.assertEqual(res.week.sessions[role].template,
                             original.sessions[role].template)

    def test_no_previous_data_is_nominal(self):
        # planned=0 -> adherence 1.0 -> nominal
        res = adapt.adapt_week(program.week(1), WeekSummary(0, 0, 0, 0, 0, 0))
        self.assertEqual(res.band, "nominal")

    def test_zero_runs_does_not_regress(self):
        """0 sortie alors qu'il y avait du prévu -> bande verifier, nominal tenu."""
        last = WeekSummary(0, 0, 0, 0, 0, 16200, data_available=True)
        res = adapt.adapt_week(program.week(9), last)
        self.assertEqual(res.band, "verifier")
        self.assertEqual(res.adjustments, [])
        self.assertEqual(workouts.minutes(res.week.sessions["long"]),
                         workouts.minutes(program.week(9).sessions["long"]))

    def test_no_data_source_is_nominal_unadapted(self):
        last = WeekSummary(0, 0, 0, 0, 0, 0, data_available=False)
        res = adapt.adapt_week(program.week(9), last)
        self.assertEqual(res.band, "nominal")
        self.assertEqual(res.adjustments, [])
        self.assertIn("Aucune donnée", res.message)


if __name__ == "__main__":
    unittest.main()
