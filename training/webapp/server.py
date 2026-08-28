"""Backend Flask de l'interface web locale (optionnelle).

Importé PARESSEUSEMENT par `generate.py serve` — jamais par le coeur du
moteur ni par la suite de tests hors `test_webapp.py`. Réutilise les
fonctions déjà pures de `generate.py` (`_prepare_week`, `_write_profile`)
comme une librairie plutôt que de dupliquer leur logique métier.

Aucune authentification : conçu pour tourner en local uniquement
(`127.0.0.1`), jamais exposé publiquement — cf. le plan qui a motivé ce
module (garde-fou Garmin anti-datacenter, issue #14).
"""

from __future__ import annotations

import importlib
import os
import sys
from datetime import date, datetime, timedelta, timezone

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # training/
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from flask import Flask, Response, jsonify, request, send_from_directory  # noqa: E402

import generate                                                          # noqa: E402
from engine import coach, config, program, push, report, strava, workouts  # noqa: E402
from engine.fit_encoder import encode as encode_fit                      # noqa: E402
from engine.models import ordered_roles                                 # noqa: E402
from webapp import chat                                                 # noqa: E402

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

# Cache mémoire simple, process-local : {week_index: AdaptResult}. Réutilisé
# par la route .fit pour qu'un clic sur 4 liens de téléchargement ne refasse
# pas 4 appels Strava. Vidé après un rechargement de profil (onboarding).
_week_cache: dict = {}


def _reload_engine() -> None:
    """Recharge la chaîne config → workouts → coach → program après une
    écriture d'`athlete.json` (onboarding via chat), sinon le process serveur
    garde l'ancien profil en mémoire jusqu'à un redémarrage.

    Ordre important : `coach` importe `PACES`/`_pace_seconds` DEPUIS
    `workouts` (référence de module désormais, cf. engine/coach.py) — il doit
    donc être rechargé APRÈS `workouts` pour capter la valeur fraîche.
    `program` importe `config`/`workouts` par référence de module, il peut se
    recharger en dernier sans contrainte d'ordre avec `coach`.
    """
    for mod in (config, workouts, coach, program):
        importlib.reload(mod)
    _week_cache.clear()


def _load_live_activities():
    """Best-effort : (activités, erreur). N'appelle jamais SystemExit (une
    route Flask ne doit jamais laisser fuiter une BaseException) — un échec
    Strava dégrade en `acts=None` (plan macro sans réalisé), pas en 500."""
    try:
        token = strava.refresh_access_token()
    except Exception as e:
        return None, f"Strava non configuré ou jeton invalide : {e}"
    try:
        now = datetime.now(timezone.utc)
        span_start = now - timedelta(days=7 * program.N_WEEKS + 7)
        return strava.fetch_activities(token, span_start, now), None
    except Exception as e:
        return None, f"Échec de récupération Strava : {e}"


def _files_for_week(res) -> dict:
    """Reproduit le nommage de `generate.py::_write_week` SANS écrire sur
    disque (les .fit du dashboard web sont encodés en mémoire, à la demande)."""
    files = {}
    for i, role in enumerate(ordered_roles(res.week.sessions), start=1):
        spec = res.week.sessions[role]
        files[role] = f"{i}_{role}_{workouts.slug(spec)}.fit"
    return files


def create_app() -> "Flask":
    app = Flask(__name__, static_folder=None)

    @app.get("/")
    def index():
        return send_from_directory(STATIC_DIR, "index.html")

    @app.get("/<path:filename>")
    def static_files(filename):
        return send_from_directory(STATIC_DIR, filename)

    @app.get("/api/plan")
    def api_plan():
        return jsonify({
            "meta": report.plan_meta_json(),
            "weeks": report.plan_data_json(),
            "current_week": program.target_week_index(date.today()),
        })

    @app.get("/api/week/<int:idx>")
    def api_week(idx):
        if not (1 <= idx <= program.N_WEEKS):
            return jsonify({"error": f"semaine {idx} hors programme "
                                     f"(1..{program.N_WEEKS})"}), 404
        today = date.today()
        acts, strava_error = (None, None)
        if request.args.get("live") == "1":
            acts, strava_error = _load_live_activities()
        res, last, actuals, analysis = generate._prepare_week(idx, acts, today)
        _week_cache[idx] = res
        data = report.week_report_json(res, last, _files_for_week(res), analysis)
        data["actuals"] = actuals
        data["strava_error"] = strava_error
        return jsonify(data)

    @app.get("/api/week/<int:idx>/fit/<role>")
    def api_week_fit(idx, role):
        res = _week_cache.get(idx)
        if res is None:
            return jsonify({"error": "charge d'abord la semaine "
                                     "(GET /api/week/<idx>)"}), 409
        if role not in res.week.sessions:
            return jsonify({"error": f"rôle inconnu pour cette semaine : {role}"}), 404
        spec = res.week.sessions[role]
        fname = _files_for_week(res)[role]
        data = encode_fit(workouts.build_workout(spec))
        return Response(data, mimetype="application/octet-stream",
                        headers={"Content-Disposition": f'attachment; filename="{fname}"'})

    @app.post("/api/week/<int:idx>/push-garmin")
    def api_week_push_garmin(idx):
        res = _week_cache.get(idx)
        if res is None:
            return jsonify({"error": "charge d'abord la semaine "
                                     "(GET /api/week/<idx>)"}), 409
        return jsonify(push.push_week(res, idx, via="auto"))

    @app.post("/api/chat")
    def api_chat():
        body = request.get_json(silent=True) or {}
        messages = body.get("messages")
        if not messages:
            return jsonify({"error": "messages manquant ou vide"}), 400

        if body.get("mode") == "onboarding":
            try:
                mtime_before = os.path.getmtime(config.CONFIG_PATH)
            except OSError:
                mtime_before = None
            system_prompt = chat.assemble_onboarding_system_prompt(config.summary())
            reply = chat.run_onboarding_turn(messages, system_prompt)
            try:
                mtime_after = os.path.getmtime(config.CONFIG_PATH)
            except OSError:
                mtime_after = None
            onboarded = mtime_after is not None and mtime_after != mtime_before
            if onboarded:
                _reload_engine()
            return jsonify({"reply": reply, "onboarded": onboarded})

        idx = body.get("week_idx") or program.target_week_index(date.today())
        if not (1 <= idx <= program.N_WEEKS):
            return jsonify({"error": f"semaine {idx} hors programme "
                                     f"(1..{program.N_WEEKS})"}), 404
        res, last, actuals, analysis = generate._prepare_week(idx, None, date.today())
        _week_cache[idx] = res
        week_json = report.week_report_json(res, last, _files_for_week(res), analysis)
        system_prompt = chat.assemble_system_prompt(
            week_json, report.plan_meta_json(), config.summary())
        reply = chat.run_chat_turn(messages, system_prompt)
        return jsonify({"reply": reply})

    return app
