import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import program, workouts
from engine.models import ROLES


class TestProgramIntegrity(unittest.TestCase):
    def test_34_weeks_sequential(self):
        self.assertEqual(program.N_WEEKS, 34)
        self.assertEqual([w.index for w in program.PROGRAM], list(range(1, 35)))

    def test_every_session_is_valid(self):
        for w in program.PROGRAM:
            self.assertTrue(w.sessions, f"semaine {w.index} sans séance")
            for role, spec in w.sessions.items():
                self.assertIn(role, ROLES)
                self.assertIn(spec.template, workouts.TEMPLATES,
                              f"template inconnu S{w.index}/{role}: {spec.template}")
                # se construit, se décrit, a une durée positive
                wkt = workouts.build_workout(spec)
                self.assertGreaterEqual(len(wkt.steps), 1)
                self.assertIsInstance(workouts.label(spec), str)
                self.assertGreater(workouts.minutes(spec), 0)

    def test_deload_weeks_are_lighter_than_neighbors(self):
        for w in program.PROGRAM:
            if w.deload and 1 < w.index < 34:
                prev = program.PROGRAM[w.index - 2]
                if not prev.deload:
                    self.assertLess(program.planned_hours(w),
                                    program.planned_hours(prev),
                                    f"décharge S{w.index} pas plus légère que S{prev.index}")

    def test_long_progression_reaches_peak(self):
        max_long = max(
            workouts.minutes(w.sessions["long"])
            for w in program.PROGRAM if "long" in w.sessions
        )
        self.assertGreaterEqual(max_long, 300)  # au moins un 5h (ou simu plus longue)


if __name__ == "__main__":
    unittest.main()
