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
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

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
        self.assertIn("onboarded", data["meta"])  # pilote le mode par défaut du chat (Phase 4)
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


@unittest.skipUnless(HAS_FLASK, "Flask non installé (training/requirements-web.txt)")
class TestPushGarminRoute(unittest.TestCase):
    """`engine.push.push_week` est monkeypatché : jamais de vrai réseau/session
    Garmin ici (cette machine a une session Garmin Connect RÉELLE en local)."""

    def setUp(self):
        from webapp import server
        server._week_cache.clear()
        self.server = server
        self.client = server.create_app().test_client()

    def test_push_requires_week_loaded_first(self):
        r = self.client.post("/api/week/1/push-garmin")
        self.assertEqual(r.status_code, 409)

    @patch("webapp.server.push.push_week")
    def test_push_forwards_cached_result(self, mock_push_week):
        mock_push_week.return_value = {
            "via": "training-api", "configured": True, "ok": True,
            "detail": None, "results": [{"role": "easy", "date": "2026-09-15",
                                         "label": "Facile 40'", "ok": True,
                                         "detail": "id wid-1"}],
        }
        self.client.get("/api/week/4")  # peuple le cache
        r = self.client.post("/api/week/4/push-garmin")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertEqual(data["via"], "training-api")
        self.assertTrue(data["ok"])
        mock_push_week.assert_called_once()
        args, kwargs = mock_push_week.call_args
        self.assertEqual(args[1], 4)
        self.assertEqual(kwargs.get("via", args[2] if len(args) > 2 else None), "auto")


@unittest.skipUnless(HAS_FLASK, "Flask non installé (training/requirements-web.txt)")
class TestHistoryRoute(unittest.TestCase):
    """`_load_live_activities` monkeypatché : jamais de vrai appel Strava ici."""

    def setUp(self):
        from webapp import server
        server._week_cache.clear()
        server._history_cache.clear()
        self.server = server
        self.client = server.create_app().test_client()

    @patch("webapp.server._load_live_activities")
    def test_returns_history_shape_and_caches_across_requests(self, mock_load):
        from engine.models import Activity
        mock_load.return_value = ([Activity("2026-09-08", 3600, 10000)], None)
        r1 = self.client.get("/api/history")
        self.assertEqual(r1.status_code, 200)
        data = r1.get_json()
        self.assertIn("weekly", data)
        self.assertIn("daily", data)
        self.assertIn("totals", data)

        r2 = self.client.get("/api/history")
        self.assertEqual(r2.status_code, 200)
        mock_load.assert_called_once()  # 2e requête servie depuis le cache

    @patch("webapp.server._load_live_activities")
    def test_refresh_param_bypasses_cache(self, mock_load):
        mock_load.return_value = ([], None)
        self.client.get("/api/history")
        self.client.get("/api/history?refresh=1")
        self.assertEqual(mock_load.call_count, 2)

    @patch("webapp.server._load_live_activities")
    def test_strava_error_surfaces_without_500(self, mock_load):
        mock_load.return_value = (None, "Strava non configuré ou jeton invalide : boom")
        r = self.client.get("/api/history")
        self.assertEqual(r.status_code, 200)
        self.assertIn("boom", r.get_json()["error"])


@unittest.skipUnless(HAS_FLASK, "Flask non installé (training/requirements-web.txt)")
class TestChatAssembleSystemPrompt(unittest.TestCase):
    def test_includes_all_three_contexts(self):
        from webapp import chat
        prompt = chat.assemble_system_prompt(
            {"week": 7, "phase": "Fondation"},
            {"objective": "24 tours", "weeks": 34},
            {"objective": "24 tours", "days_per_week": 4},
        )
        self.assertIn("Fondation", prompt)
        self.assertIn("34", prompt)
        self.assertIn("days_per_week", prompt)


class TestChatAssembleOnboardingSystemPrompt(unittest.TestCase):
    def test_includes_command_and_current_profile(self):
        from webapp import chat
        prompt = chat.assemble_onboarding_system_prompt({"objective": None, "onboarded": False})
        self.assertIn("generate.py onboard", prompt)
        self.assertIn("onboarded", prompt)
        self.assertIn("N'exécute AUCUNE autre commande", prompt)


class TestChatRunTurn(unittest.TestCase):
    """`subprocess.run` monkeypatché : jamais de vrai appel `claude` ici."""

    @patch("webapp.chat.subprocess.run")
    def test_builds_expected_command_and_returns_stdout(self, mock_run):
        from webapp import chat
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="Repos bien mérité cette semaine.\n", stderr="")
        reply = chat.run_chat_turn(
            [{"role": "user", "content": "Comment est ma semaine ?"}], "SYSTEM-PROMPT")
        self.assertEqual(reply, "Repos bien mérité cette semaine.")
        args, kwargs = mock_run.call_args
        cmd = args[0]
        self.assertEqual(cmd[1], "-p")  # cmd[0] = binaire résolu (shutil.which), varie selon la machine
        self.assertIn("--append-system-prompt", cmd)
        self.assertEqual(cmd[cmd.index("--append-system-prompt") + 1], "SYSTEM-PROMPT")
        self.assertIn("--tools", cmd)
        self.assertIn("Comment est ma semaine ?", kwargs["input"])

    @patch("webapp.chat.subprocess.run")
    def test_nonzero_exit_degrades_to_message(self, mock_run):
        from webapp import chat
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="boom")
        reply = chat.run_chat_turn([{"role": "user", "content": "hi"}], "SYS")
        self.assertIn("boom", reply)

    @patch("webapp.chat.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="claude", timeout=1))
    def test_timeout_degrades_to_message(self, mock_run):
        from webapp import chat
        reply = chat.run_chat_turn([{"role": "user", "content": "hi"}], "SYS")
        self.assertIn("timeout", reply.lower())

    @patch("webapp.chat.subprocess.run", side_effect=FileNotFoundError())
    def test_missing_binary_degrades_to_message(self, mock_run):
        from webapp import chat
        reply = chat.run_chat_turn([{"role": "user", "content": "hi"}], "SYS")
        self.assertIn("introuvable", reply)


class TestOnboardingRunTurn(unittest.TestCase):
    """`subprocess.run` monkeypatché : jamais de vrai appel `claude` ici — un
    vrai appel toucherait athlete.json, le profil réel de cette machine."""

    @patch("webapp.chat.subprocess.run")
    def test_uses_shell_tool_only_no_bypass_flag_and_repo_root_cwd(self, mock_run):
        from webapp import chat
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="Profil enregistré.\n", stderr="")
        reply = chat.run_onboarding_turn(
            [{"role": "user", "content": "Objectif : 24 tours"}], "SYSTEM-PROMPT")
        self.assertEqual(reply, "Profil enregistré.")
        args, kwargs = mock_run.call_args
        cmd = args[0]
        self.assertEqual(cmd[1], "-p")
        self.assertIn("--tools", cmd)
        # Bash (POSIX) et PowerShell (Windows) : un seul des deux existe vraiment
        # selon la plateforme, mais jamais "" (Q&A) ni "default" (tout ouvert).
        self.assertEqual(cmd[cmd.index("--tools") + 1], "Bash,PowerShell")
        # Pas de --dangerously-skip-permissions : vérifié que -p n'attend aucune
        # confirmation humaine pour les outils listés dans --tools (personne pour
        # répondre en headless) — le flag n'apportait donc aucune protection réelle.
        self.assertNotIn("--dangerously-skip-permissions", cmd)
        self.assertEqual(kwargs["cwd"], chat.REPO_ROOT)

    @patch("webapp.chat.subprocess.run")
    def test_nonzero_exit_degrades_to_message(self, mock_run):
        from webapp import chat
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="boom")
        reply = chat.run_onboarding_turn([{"role": "user", "content": "hi"}], "SYS")
        self.assertIn("boom", reply)


@unittest.skipUnless(HAS_FLASK, "Flask non installé (training/requirements-web.txt)")
class TestChatRoute(unittest.TestCase):
    def setUp(self):
        from webapp import server
        server._week_cache.clear()
        self.server = server
        self.client = server.create_app().test_client()

    def test_missing_messages_is_400(self):
        r = self.client.post("/api/chat", json={})
        self.assertEqual(r.status_code, 400)

    def test_week_out_of_range_is_404(self):
        from engine import program
        r = self.client.post("/api/chat", json={
            "messages": [{"role": "user", "content": "hi"}],
            "week_idx": program.N_WEEKS + 1,
        })
        self.assertEqual(r.status_code, 404)

    @patch("webapp.server.chat.run_chat_turn")
    def test_forwards_reply_and_defaults_week_to_current(self, mock_run_chat_turn):
        mock_run_chat_turn.return_value = "Tout va bien."
        r = self.client.post("/api/chat", json={
            "messages": [{"role": "user", "content": "Comment se passe la semaine ?"}],
        })
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["reply"], "Tout va bien.")
        mock_run_chat_turn.assert_called_once()
        messages_arg, system_prompt_arg = mock_run_chat_turn.call_args[0]
        self.assertEqual(messages_arg[0]["content"], "Comment se passe la semaine ?")
        self.assertIsInstance(system_prompt_arg, str)
        self.assertIn("Semaine courante", system_prompt_arg)

    @patch("webapp.server._reload_engine")
    @patch("webapp.server.chat.run_onboarding_turn")
    @patch("webapp.server.os.path.getmtime", side_effect=[1000.0, 2000.0])
    def test_onboarding_mode_reloads_engine_when_profile_written(
            self, mock_getmtime, mock_run_onboarding, mock_reload):
        mock_run_onboarding.return_value = "Profil enregistré, regarde l'onglet Plan !"
        r = self.client.post("/api/chat", json={
            "messages": [{"role": "user", "content": "Objectif 24 tours, course le 2027-04-03"}],
            "mode": "onboarding",
        })
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertEqual(data["reply"], "Profil enregistré, regarde l'onglet Plan !")
        self.assertTrue(data["onboarded"])
        mock_reload.assert_called_once()
        messages_arg, system_prompt_arg = mock_run_onboarding.call_args[0]
        self.assertIn("24 tours", messages_arg[0]["content"])
        self.assertIn("generate.py onboard", system_prompt_arg)

    @patch("webapp.server._reload_engine")
    @patch("webapp.server.chat.run_onboarding_turn")
    @patch("webapp.server.os.path.getmtime", return_value=1000.0)
    def test_onboarding_mode_no_reload_when_profile_unchanged(
            self, mock_getmtime, mock_run_onboarding, mock_reload):
        mock_run_onboarding.return_value = "D'accord, et ta date de course ?"
        r = self.client.post("/api/chat", json={
            "messages": [{"role": "user", "content": "Mon objectif : 24 tours"}],
            "mode": "onboarding",
        })
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.get_json()["onboarded"])
        mock_reload.assert_not_called()


if __name__ == "__main__":
    unittest.main()
