"""Tests de l'interface web locale (training/webapp/).

Toute la classe est sautée si Flask n'est pas installé — dépendance
OPTIONNELLE (training/requirements-web.txt), jamais requise pour le reste
de la suite. `_reload_engine()` mute des modules PARTAGÉS avec les autres
fichiers de test (`engine.config`/`workouts`/`coach`/`program`) : chaque test
qui l'exerce doit restaurer l'état d'origine en `finally`, quel que soit
l'ordre d'exécution de `discover`.
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import flask  # noqa: F401
    HAS_FLASK = True
except ImportError:
    HAS_FLASK = False


@unittest.skipUnless(HAS_FLASK, "Flask non installé (training/requirements-web.txt)")
class TestReloadChain(unittest.TestCase):
    def test_reload_picks_up_new_athlete_json(self):
        from webapp import server
        from engine import config

        old_env = os.environ.get("ATHLETE_CONFIG")
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "athlete.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"objective": "TEST-OBJECTIVE-XYZ", "days_per_week": 3,
                          "onboarded": True}, f)
            os.environ["ATHLETE_CONFIG"] = path
            try:
                server._reload_engine()
                self.assertEqual(config.CONFIG_PATH, path)
                self.assertEqual(config.OBJECTIVE, "TEST-OBJECTIVE-XYZ")
                self.assertEqual(config.DAYS_PER_WEEK, 3)
            finally:
                if old_env is None:
                    os.environ.pop("ATHLETE_CONFIG", None)
                else:
                    os.environ["ATHLETE_CONFIG"] = old_env
                server._reload_engine()  # restaure le profil réel pour la suite

    def test_reload_updates_coach_paces_binding(self):
        """Régression : coach.py importait PACES par VALEUR depuis workouts —
        un reload de config+workouts sans coach laissait une allure figée."""
        from webapp import server
        from engine import config, coach

        old_env = os.environ.get("ATHLETE_CONFIG")
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "athlete.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"onboarded": True,
                          "paces": {"easy": "5:00", "steady": "4:30"}}, f)
            os.environ["ATHLETE_CONFIG"] = path
            try:
                server._reload_engine()
                self.assertEqual(config.PACES.get("easy"), "5:00")
                self.assertEqual(coach.workouts.PACES.get("easy"), "5:00")
            finally:
                if old_env is None:
                    os.environ.pop("ATHLETE_CONFIG", None)
                else:
                    os.environ["ATHLETE_CONFIG"] = old_env
                server._reload_engine()


@unittest.skipUnless(HAS_FLASK, "Flask non installé (training/requirements-web.txt)")
class TestRoutes(unittest.TestCase):
    def setUp(self):
        from webapp import server
        server._week_cache.clear()
        self.server = server
        self.client = server.create_app().test_client()

    def test_plan_route(self):
        r = self.client.get("/api/plan")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertIn("objective", data["meta"])
        self.assertEqual(len(data["weeks"]), data["meta"]["weeks"])
        self.assertIn("current_week", data)

    def test_week_route_and_fit_download(self):
        from engine import program
        idx = min(9, program.N_WEEKS)
        r = self.client.get(f"/api/week/{idx}")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertEqual(data["week"], idx)
        self.assertGreater(len(data["sessions"]), 0)
        self.assertIsNone(data["strava_error"])  # pas de ?live=1 -> pas d'appel réseau

        role = data["sessions"][0]["role"]
        fr = self.client.get(f"/api/week/{idx}/fit/{role}")
        self.assertEqual(fr.status_code, 200)
        self.assertEqual(fr.mimetype, "application/octet-stream")
        self.assertGreater(len(fr.data), 0)

    def test_week_out_of_range_is_404(self):
        from engine import program
        r = self.client.get(f"/api/week/{program.N_WEEKS + 1}")
        self.assertEqual(r.status_code, 404)

    def test_fit_without_loading_week_first_is_409(self):
        from engine import program
        idx = program.N_WEEKS  # jamais chargé : setUp vide le cache à chaque test
        r = self.client.get(f"/api/week/{idx}/fit/easy")
        self.assertEqual(r.status_code, 409)

    def test_fit_unknown_role_is_404(self):
        from engine import program
        idx = min(9, program.N_WEEKS)
        self.client.get(f"/api/week/{idx}")  # peuple le cache
        r = self.client.get(f"/api/week/{idx}/fit/does-not-exist")
        self.assertEqual(r.status_code, 404)


if __name__ == "__main__":
    unittest.main()
