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
import threading
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlparse

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

# Cache pour l'onglet Historique : {} tant que jamais chargé, sinon
# {"data": dict}. Une seule fenêtre glissante (12 mois), pas par clé comme
# _week_cache — vidé uniquement par le bouton "Actualiser" côté client
# (?refresh=1), jamais automatiquement (évite un appel Strava par tab-switch).
_history_cache: dict = {}

# Verrou partagé protégeant les deux caches process-local. Serveur mono-
# utilisateur : un seul verrou global (lectures/écritures/vidages) suffit,
# inutile d'en avoir un par cache.
_cache_lock = threading.Lock()

# Garde anti-DNS-rebinding : le chat onboarding shelle out un outil Bash au
# niveau du repo, une page « rebound » en same-origin pourrait le piloter par
# prompt injection. On borne donc l'hôte/l'origine au local (cf. #48).
_ALLOWED_HOSTS = {"127.0.0.1", "localhost"}


def _host_part(netloc: str) -> str:
    """Isole l'hôte d'un `host:port` (gère l'IPv6 littéral entre crochets,
    ex. `[::1]:5000` → `::1`)."""
    netloc = netloc.strip()
    if netloc.startswith("["):
        return netloc[1:netloc.index("]")] if "]" in netloc else netloc[1:]
    return netloc.rsplit(":", 1)[0] if ":" in netloc else netloc


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
    with _cache_lock:
        _week_cache.clear()


def _load_live_activities(days_back: Optional[int] = None):
    """Best-effort : (activités, erreur). N'appelle jamais SystemExit (une
    route Flask ne doit jamais laisser fuiter une BaseException) — un échec
    Strava dégrade en `acts=None` (plan macro sans réalisé), pas en 500.
    `days_back` par défaut : assez pour couvrir tout le plan (ACWR compris)."""
    try:
        token = strava.refresh_access_token()
    except Exception as e:
        return None, f"Strava non configuré ou jeton invalide : {e}"
    try:
        now = datetime.now(timezone.utc)
        span = days_back if days_back is not None else 7 * program.N_WEEKS + 7
        span_start = now - timedelta(days=span)
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

    @app.before_request
    def _guard_local_only():
        """Rejette en 403 toute requête dont l'hôte n'est pas local, ou dont
        l'`Origin` (quand présente) n'est pas un `http://127.0.0.1|localhost`
        — parade DNS-rebinding pour le shell d'onboarding (#48). Une requête
        sans `Origin` (GET same-origin) est autorisée."""
        if _host_part(request.headers.get("Host", "")) not in _ALLOWED_HOSTS:
            return jsonify({"error": "hôte non autorisé (local uniquement)"}), 403
        origin = request.headers.get("Origin")
        if origin:
            parsed = urlparse(origin)
            if parsed.scheme != "http" or _host_part(parsed.netloc) not in _ALLOWED_HOSTS:
                return jsonify({"error": "origine non autorisée (local uniquement)"}), 403

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
        with _cache_lock:
            _week_cache[idx] = res
        data = report.week_report_json(res, last, _files_for_week(res), analysis)
        data["actuals"] = actuals
        data["strava_error"] = strava_error
        return jsonify(data)

    @app.get("/api/history")
    def api_history():
        """Fenêtre glissante de 12 mois (alignée sur un lundi pour la grille
        heatmap), mise en cache process-local — un appel Strava par process
        tant que `?refresh=1` n'est pas demandé, pas un par tab-switch."""
        with _cache_lock:
            if request.args.get("refresh") == "1":
                _history_cache.clear()
            if "data" not in _history_cache:
                today = date.today()
                end = today + timedelta(days=1)
                raw_start = today - timedelta(days=365)
                start = raw_start - timedelta(days=raw_start.weekday())
                acts, strava_error = _load_live_activities(days_back=(end - start).days)
                if acts is None:
                    return jsonify({"error": strava_error}), 502
                _history_cache["data"] = strava.history_json(acts, start, end)
            return jsonify(_history_cache["data"])

    @app.get("/api/week/<int:idx>/fit/<role>")
    def api_week_fit(idx, role):
        with _cache_lock:
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
        with _cache_lock:
            res = _week_cache.get(idx)
        if res is None:
            return jsonify({"error": "charge d'abord la semaine "
                                     "(GET /api/week/<idx>)"}), 409
        return jsonify(push.push_week(res, idx, via="auto"))

    @app.post("/api/chat")
    def api_chat():
        body = request.get_json(silent=True) or {}
        messages = body.get("messages")
        if (not isinstance(messages, list) or not messages
                or not all(isinstance(m, dict) and "role" in m and "content" in m
                           for m in messages)):
            return jsonify({"error": "messages doit être une liste non vide "
                                     "de {role, content}"}), 400

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

        # `week_idx` explicite : on le coerce en int (une valeur non entière →
        # 400, pas un 500). Absent → semaine courante. NB : ne PAS utiliser
        # `body.get(...) or default`, qui transformerait un 0/négatif explicite
        # en défaut au lieu de le valider comme hors-programme.
        raw_idx = body.get("week_idx")
        if raw_idx is None:
            idx = program.target_week_index(date.today())
        else:
            try:
                idx = int(raw_idx)
            except (TypeError, ValueError):
                return jsonify({"error": "week_idx invalide (entier attendu)"}), 400
        if not (1 <= idx <= program.N_WEEKS):
            return jsonify({"error": f"semaine {idx} hors programme "
                                     f"(1..{program.N_WEEKS})"}), 404
        res, last, actuals, analysis = generate._prepare_week(idx, None, date.today())
        with _cache_lock:
            _week_cache[idx] = res
        week_json = report.week_report_json(res, last, _files_for_week(res), analysis)
        system_prompt = chat.assemble_system_prompt(
            week_json, report.plan_meta_json(), config.summary())
        reply = chat.run_chat_turn(messages, system_prompt)
        return jsonify({"reply": reply})

    return app
