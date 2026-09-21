"""Tests : python3 -m unittest discover -s tools/psychopy_tapping"""

import importlib.util
import math
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

import analyser_tapping as app
import tap_analysis as ta

HAS_MPL = importlib.util.find_spec("matplotlib") is not None


def row(**kwargs):
    return pd.Series(kwargs)


class ParsingTests(unittest.TestCase):
    def test_parse_np_float_cell(self):
        cell = "[np.float64(0.1), np.float64(0.45), np.float64(1.2e-01)]"
        self.assertEqual(ta.parse_list_cell(cell), [0.1, 0.45, 0.12])

    def test_parse_empty_variants(self):
        for cell in (None, float("nan"), "", "[]", "nan"):
            self.assertIsNone(ta.parse_list_cell(cell))

    def test_component_and_loop_detection(self):
        cols = ["foot_tapping.time", "Practice.foot_tapping.time", "key_resp.rt"]
        self.assertEqual(ta.find_components(cols), ["foot_tapping"])
        self.assertEqual(ta.loop_of("Practice.foot_tapping.time", "foot_tapping"), "Practice")
        self.assertEqual(ta.loop_of("foot_tapping.time", "foot_tapping"), "")


class ExtractionTests(unittest.TestCase):
    def test_on_click_sampling_prefers_loop_column(self):
        cols = ["foot_tapping.time", "Practice.foot_tapping.time",
                "foot_tapping.leftButton", "Practice.foot_tapping.leftButton"]
        r = row(**{
            "foot_tapping.time": "[0.0, 0.5, 1.0]",
            "Practice.foot_tapping.time": "[0.0, 0.5, 1.0]",
            "foot_tapping.leftButton": "[1, 1, 1]",
            "Practice.foot_tapping.leftButton": "[1, 1, 1]",
        })
        got = ta.extract_taps(r, "foot_tapping", cols, min_iti=0.0)
        self.assertEqual(got["times"], [0.0, 0.5, 1.0])
        self.assertEqual(got["loop"], "Practice")
        self.assertEqual(got["sampling"], "on_click")

    def test_every_frame_sampling_keeps_press_onsets(self):
        cols = ["m.time", "m.leftButton"]
        r = row(**{"m.time": "[0.0, 0.1, 0.2, 0.3, 0.4]",
                   "m.leftButton": "[0, 1, 1, 0, 1]"})
        got = ta.extract_taps(r, "m", cols, min_iti=0.0)
        self.assertEqual(got["sampling"], "every_frame")
        self.assertEqual(got["times"], [0.1, 0.4])

    def test_debounce_merges_short_intervals(self):
        cols = ["m.time"]
        r = row(**{"m.time": "[0.0, 0.01, 0.5]"})
        got = ta.extract_taps(r, "m", cols, min_iti=0.05)
        self.assertEqual(got["times"], [0.0, 0.5])
        self.assertEqual(got["n_short_merged"], 1)

    def test_other_buttons_ignored(self):
        cols = ["m.time", "m.leftButton"]
        r = row(**{"m.time": "[0.0, 0.5, 1.0]", "m.leftButton": "[1, 1, 1]"})
        self.assertEqual(len(ta.extract_taps(r, "m", cols, button="right")["times"]), 3)


class MetricTests(unittest.TestCase):
    def test_perfectly_isochronous_train(self):
        times = [i * 0.4 for i in range(11)]
        m = ta.trial_metrics(times)
        self.assertEqual(m["n_taps"], 11)
        self.assertAlmostEqual(m["iti_mean"], 0.4)
        self.assertAlmostEqual(m["tap_rate_hz"], 2.5)
        self.assertAlmostEqual(m["tap_rate_per_min"], 150.0)
        self.assertAlmostEqual(m["iti_cv"], 0.0)
        self.assertAlmostEqual(m["rmssd"], 0.0)
        self.assertAlmostEqual(m["isochrony_sd_s"], 0.0, places=9)
        self.assertEqual(m["n_pauses"], 0)

    def test_pause_excluded_from_clean_metrics(self):
        times = list(np.arange(0, 10) * 0.3) + [5.0, 5.3, 5.6]
        m = ta.trial_metrics(times)
        self.assertEqual(m["n_pauses"], 1)
        self.assertAlmostEqual(m["longest_gap_s"], 5.0 - 9 * 0.3, places=6)
        self.assertGreater(m["iti_cv"], m["clean_iti_cv"])
        self.assertAlmostEqual(m["clean_iti_cv"], 0.0, places=9)
        self.assertAlmostEqual(m["clean_iti_mean"], 0.3, places=9)

    def test_acceleration_is_detected(self):
        itis = np.linspace(0.5, 0.3, 20)
        times = np.r_[0.0, np.cumsum(itis)]
        m = ta.trial_metrics(times.tolist())
        self.assertLess(m["iti_slope_s_per_tap"], 0)
        self.assertLess(m["drift_ratio"], 1)
        self.assertGreater(m["rate_second_half_hz"], m["rate_first_half_hz"])

    def test_single_tap_is_not_an_error(self):
        m = ta.trial_metrics([1.23])
        self.assertEqual(m["n_taps"], 1)
        self.assertTrue(math.isnan(m["iti_mean"]))

    def test_target_tempo_phase_locking(self):
        locked = ta.trial_metrics([i * 0.5 for i in range(20)], target_iti=0.5)
        self.assertAlmostEqual(locked["phase_locking_r"], 1.0, places=6)
        self.assertAlmostEqual(locked["iti_bias_s"], 0.0, places=9)
        rng = np.random.default_rng(0)
        jittered = ta.trial_metrics(np.cumsum(rng.uniform(0.2, 0.8, 200)).tolist(),
                                    target_iti=0.5)
        self.assertLess(jittered["phase_locking_r"], 0.5)

    def test_frame_quantisation_flag(self):
        frame = 1 / 60
        times = np.cumsum([frame * k for k in [18, 20, 19, 20, 21, 19]]).tolist()
        m = ta.trial_metrics(times, frame_rate=60.0)
        self.assertTrue(m["frame_quantized"])


class FrameRateTests(unittest.TestCase):
    def test_decimal_separator_loss_is_recovered(self):
        df = pd.DataFrame({"frameRate": [5993960485655321]})
        self.assertAlmostEqual(ta.guess_frame_rate(df), 59.93960485655321, places=6)

    def test_plain_frame_rate(self):
        self.assertAlmostEqual(ta.guess_frame_rate(pd.DataFrame({"frameRate": [60.0]})), 60.0)


def _fake_tables(n_participants=2, n_trials=4):
    """Deux tables (essais / appuis) cohérentes, comme après analyse."""
    trials, taps = [], []
    for p in range(n_participants):
        for t in range(n_trials):
            times = np.arange(0, 3, 0.3) + 0.01 * t
            row = {"file": f"p{p}.xlsx", "source_row": t + 2, "participant": 100 + p,
                   "Condition": ["C", "I", "N"][t % 3]}
            metrics = ta.trial_metrics(times.tolist())
            trials.append(row | metrics)
            for k, time in enumerate(times):
                taps.append(row | {"tap_index": k, "time_s": time,
                                   "iti_s": None if k == 0 else 0.3,
                                   "is_pause": False})
    return ta.add_labels(pd.DataFrame(trials), pd.DataFrame(taps))


class LabelTests(unittest.TestCase):
    def test_participant_id_and_trial_labels(self):
        trials, taps = _fake_tables()
        self.assertEqual(sorted(trials["participant_id"].unique()), ["100", "101"])
        self.assertEqual(list(trials["trial_label"])[:2], ["E01 · C", "E02 · I"])
        self.assertEqual(list(trials.groupby("participant_id")["trial_no"].max()), [4, 4])

    def test_trial_key_joins_both_tables(self):
        trials, taps = _fake_tables()
        self.assertTrue(set(taps["trial_key"]) <= set(trials["trial_key"]))
        self.assertEqual(taps["trial_label"].isna().sum(), 0)

    def test_participant_id_falls_back_to_file_name(self):
        trials = pd.DataFrame([{"file": "sujet_A.xlsx", "source_row": 2}])
        taps = pd.DataFrame([{"file": "sujet_A.xlsx", "source_row": 2, "tap_index": 0}])
        trials, _ = ta.add_labels(trials, taps)
        self.assertEqual(trials.loc[0, "participant_id"], "sujet_A")


class InputCollectionTests(unittest.TestCase):
    def test_folder_scan_skips_generated_and_temp_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "donnees.xlsx").touch()
            (root / "notes.txt").touch()
            (root / "trials.csv").touch()          # sortie d'une analyse précédente
            (root / "~$donnees.xlsx").touch()      # fichier temporaire Excel
            (root / "analyse_tapping_2026").mkdir()
            (root / "analyse_tapping_2026" / "taps_long.csv").touch()
            found = app.collect_inputs([root])
            self.assertEqual([f.name for f in found], ["donnees.xlsx"])

    def test_explicit_files_are_kept_and_deduplicated(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "a.csv"
            f.touch()
            self.assertEqual(app.collect_inputs([f, f]), [f])


@unittest.skipUnless(HAS_MPL, "matplotlib absent")
class PlotTests(unittest.TestCase):
    def test_all_figure_families_are_produced(self):
        import plots

        trials, taps = _fake_tables()
        with tempfile.TemporaryDirectory() as tmp:
            written = plots.make_all(taps, trials, Path(tmp), group_cols=["Condition"])
            names = {p.name for p in written}
        self.assertTrue(all(p for p in names))
        self.assertIn("participants_resume.png", names)
        self.assertIn("conditions_Condition.png", names)
        self.assertIn("conditions_Condition_distribution_iti.png", names)
        self.assertTrue({"essais_100_raster.png", "essais_100_iti.png",
                         "essais_100_resume.png"} <= names)


if __name__ == "__main__":
    unittest.main()
