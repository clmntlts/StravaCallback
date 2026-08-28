"""Tests de engine/push.py — sélection de voie Garmin + résultat structuré.

AUCUN de ces tests ne doit toucher le réseau ni des identifiants réels :
`garmin`/`garmin_connect` sont monkeypatchés (unittest.mock.patch), jamais
appelés pour de vrai — cette machine a une session Garmin Connect RÉELLE
configurée (`training/.env`), un vrai appel pousserait/planifierait une
séance sur le compte réel de l'athlète.
"""

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import adapt, program, push
from engine.models import WeekSummary


def _fixture_res():
    return adapt.adapt_week(program.week(4),
                            WeekSummary(3, 12000, 40000, 500, 5400, 16200,
                                        acute_hours=3.3, chronic_hours=3.3))


class TestPushWeekNotConfigured(unittest.TestCase):
    def setUp(self):
        self._env_backup = {}
        for k in ("GARMIN_CONSUMER_KEY", "GARMIN_CONSUMER_SECRET", "GARMIN_REFRESH_TOKEN",
                  "GARMIN_EMAIL", "GARMIN_PASSWORD", "GARMIN_TOKENS_BASE64"):
            self._env_backup[k] = os.environ.pop(k, None)

    def tearDown(self):
        for k, v in self._env_backup.items():
            if v is not None:
                os.environ[k] = v

    def test_training_api_not_configured(self):
        result = push.push_week(_fixture_res(), 4, via="training-api")
        self.assertEqual(result, {"via": "training-api", "configured": False,
                                  "ok": False, "detail": None, "results": []})

    def test_connect_not_configured(self):
        result = push.push_week(_fixture_res(), 4, via="connect")
        self.assertEqual(result, {"via": "connect", "configured": False,
                                  "ok": False, "detail": None, "results": []})

    def test_auto_falls_back_to_connect_when_training_api_unconfigured(self):
        # is_configured()==False des deux côtés -> "auto" choisit "connect"
        # (repli), qui retombe lui aussi sur configured=False. Vérifie juste
        # le choix de voie, pas un vrai push.
        result = push.push_week(_fixture_res(), 4, via="auto")
        self.assertEqual(result["via"], "connect")
        self.assertFalse(result["configured"])

    def test_invalid_via_raises(self):
        with self.assertRaises(ValueError):
            push.push_week(_fixture_res(), 4, via="carrier-pigeon")


class TestPushWeekTrainingApiMocked(unittest.TestCase):
    """`garmin.is_configured()` lit des variables d'env ; on les fixe à des
    valeurs BIDON et on monkeypatche get_access_token/push_and_schedule pour
    ne jamais atteindre le réseau réel."""

    def setUp(self):
        self._env_backup = {}
        for k, v in (("GARMIN_CONSUMER_KEY", "x"), ("GARMIN_CONSUMER_SECRET", "x"),
                     ("GARMIN_REFRESH_TOKEN", "x")):
            self._env_backup[k] = os.environ.get(k)
            os.environ[k] = v

    def tearDown(self):
        for k, v in self._env_backup.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    @patch("engine.push.garmin.push_and_schedule")
    @patch("engine.push.garmin.get_access_token")
    def test_per_session_results_all_ok(self, mock_token, mock_push):
        mock_token.return_value = "fake-access-token"
        mock_push.return_value = "wid-123"
        result = push.push_week(_fixture_res(), 4, via="training-api")
        self.assertTrue(result["configured"])
        self.assertTrue(result["ok"])
        self.assertIsNone(result["detail"])
        self.assertEqual(len(result["results"]), 4)  # quality/easy/long/b2b
        for r in result["results"]:
            self.assertTrue(r["ok"])
            self.assertEqual(r["detail"], "id wid-123")
            self.assertIn("role", r)
            self.assertIn("date", r)
            self.assertIn("label", r)

    @patch("engine.push.garmin.push_and_schedule")
    @patch("engine.push.garmin.get_access_token")
    def test_per_session_failure_does_not_raise(self, mock_token, mock_push):
        mock_token.return_value = "fake-access-token"
        mock_push.side_effect = RuntimeError("Garmin API 500")
        result = push.push_week(_fixture_res(), 4, via="training-api")
        self.assertFalse(result["ok"])
        self.assertEqual(len(result["results"]), 4)
        for r in result["results"]:
            self.assertFalse(r["ok"])
            self.assertEqual(r["detail"], "Garmin API 500")

    @patch("engine.push.garmin.get_access_token")
    def test_auth_failure_captured_not_raised(self, mock_token):
        mock_token.side_effect = RuntimeError("token expiré")
        result = push.push_week(_fixture_res(), 4, via="training-api")
        self.assertTrue(result["configured"])
        self.assertFalse(result["ok"])
        self.assertEqual(result["detail"], "token expiré")
        self.assertEqual(result["results"], [])


class TestPushWeekConnectMocked(unittest.TestCase):
    """Idem TestPushWeekTrainingApiMocked pour la voie Garmin Connect —
    `login`/`push_and_schedule` monkeypatchés, jamais de session réelle."""

    def setUp(self):
        self._env_backup = {}
        for k, v in (("GARMIN_EMAIL", "test@example.invalid"), ("GARMIN_PASSWORD", "x")):
            self._env_backup[k] = os.environ.get(k)
            os.environ[k] = v
        self._token_backup = os.environ.pop("GARMIN_TOKENS_BASE64", None)

    def tearDown(self):
        for k, v in self._env_backup.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        if self._token_backup is not None:
            os.environ["GARMIN_TOKENS_BASE64"] = self._token_backup

    @patch("engine.push.garmin_connect.push_and_schedule")
    @patch("engine.push.garmin_connect.login")
    def test_per_session_results_all_ok(self, mock_login, mock_push):
        mock_login.return_value = "fake-client"
        mock_push.return_value = ("wid-456", "fake-client")
        result = push.push_week(_fixture_res(), 4, via="connect")
        self.assertTrue(result["configured"])
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["results"]), 4)
        for r in result["results"]:
            self.assertTrue(r["ok"])
            self.assertEqual(r["detail"], "id wid-456")

    @patch("engine.push.garmin_connect.login")
    def test_connection_failure_captured_not_raised(self, mock_login):
        mock_login.side_effect = RuntimeError("MFA requise")
        result = push.push_week(_fixture_res(), 4, via="connect")
        self.assertTrue(result["configured"])
        self.assertFalse(result["ok"])
        self.assertEqual(result["detail"], "MFA requise")
        self.assertEqual(result["results"], [])


if __name__ == "__main__":
    unittest.main()
