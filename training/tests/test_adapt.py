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
    def test_nominal_keeps_program(self):
        w = program.week(9)
        res = adapt.adapt_week(w, summary(1.0))
        self.assertEqual(res.band, "nominal")
        self.assertEqual(res.adjustments, [])
        self.assertEqual(workouts.minutes(res.week.sessions["long"]),
                         workouts.minutes(program.week(9).sessions["long"]))

    def test_consolide_tempers_and_caps_long(self):
        res = adapt.adapt_week(program.week(9), summary(0.73, longest_min=90))
        self.assertEqual(res.band, "consolide")
        # long plafonné à +15 % de 90' = 103' -> arrondi 105'
        self.assertLessEqual(workouts.minutes(res.week.sessions["long"]), 105)
        self.assertTrue(any(a.role == "long" for a in res.adjustments))

    def test_reprise_regresses(self):
        res = adapt.adapt_week(program.week(9), summary(0.4, longest_min=60))
        self.assertEqual(res.band, "reprise")
        self.assertLess(workouts.minutes(res.week.sessions["easy"]),
                        workouts.minutes(program.week(9).sessions["easy"]))

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


if __name__ == "__main__":
    unittest.main()
