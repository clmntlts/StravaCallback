import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import workouts
from engine.fit_encoder import encode, fit_crc, write
from engine.models import SessionSpec

try:
    import fitdecode
    HAS_FITDECODE = True
except ImportError:
    HAS_FITDECODE = False


class TestEncoder(unittest.TestCase):
    def test_header_and_crc(self):
        data = encode(workouts.build_workout(SessionSpec("easy", {"minutes": 60})))
        self.assertEqual(data[0], 14)              # taille header
        self.assertEqual(data[8:12], b".FIT")      # signature
        # CRC final = CRC des data records
        body = data[14:-2]
        self.assertEqual(int.from_bytes(data[-2:], "little"), fit_crc(body))

    @unittest.skipUnless(HAS_FITDECODE, "fitdecode non installé")
    def test_parses_with_reference_lib(self):
        spec = SessionSpec("threshold", {"reps": 5, "rep_min": 3, "rec_min": 2})
        with tempfile.NamedTemporaryFile(suffix=".fit", delete=False) as tf:
            write(workouts.build_workout(spec), tf.name)
            path = tf.name
        try:
            counts = {"file_id": 0, "workout": 0, "workout_step": 0}
            declared = None
            repeat_seen = False
            with fitdecode.FitReader(path) as fr:
                for fr_ in fr:
                    if isinstance(fr_, fitdecode.FitDataMessage):
                        if fr_.name in counts:
                            counts[fr_.name] += 1
                        if fr_.name == "workout":
                            declared = fr_.get_value("num_valid_steps")
                        if fr_.name == "workout_step":
                            if fr_.get_value("duration_type") == "repeat_until_steps_cmplt":
                                repeat_seen = True
                                self.assertEqual(fr_.get_value("repeat_steps"), 5)
            self.assertEqual(counts["file_id"], 1)
            self.assertEqual(counts["workout"], 1)
            self.assertEqual(counts["workout_step"], declared)
            self.assertTrue(repeat_seen, "bloc de répétition non décodé")
        finally:
            os.unlink(path)

    @unittest.skipUnless(HAS_FITDECODE, "fitdecode non installé")
    def test_all_templates_encode_and_parse(self):
        specs = [
            SessionSpec("easy", {"minutes": 45}),
            SessionSpec("long", {"minutes": 180}),
            SessionSpec("hills", {"reps": 8, "sec": 60}),
            SessionSpec("backyard", {"loops": 6}),
            SessionSpec("runwalk", {"hours": 3}),
        ]
        for spec in specs:
            data = encode(workouts.build_workout(spec))
            with tempfile.NamedTemporaryFile(suffix=".fit", delete=False) as tf:
                tf.write(data)
                path = tf.name
            try:
                with fitdecode.FitReader(path) as fr:
                    steps = sum(1 for x in fr
                                if isinstance(x, fitdecode.FitDataMessage)
                                and x.name == "workout_step")
                self.assertGreaterEqual(steps, 1, f"{spec.template} sans étape")
            finally:
                os.unlink(path)


if __name__ == "__main__":
    unittest.main()
