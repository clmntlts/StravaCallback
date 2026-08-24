#!/usr/bin/env python3
"""CLI du moteur d'entraînement adaptatif backyard ultra.

Exemples :

  # Semaine adaptative (fichiers .fit + rapport + dashboard) depuis une fixture :
  python3 generate.py week 9 --activities tests/fixtures/last_week_sample.json --today 2026-09-14

  # Pipeline hebdo complet + envoi email (semaine courante déduite du calendrier) :
  python3 generate.py send --live

  # Idem mais sans envoyer (génère tout, montre ce qui serait expédié) :
  python3 generate.py send --activities tests/fixtures/last_week_sample.json --today 2026-09-14 --dry-run

  # Bibliothèque nominale complète / régénérer le plan :
  python3 generate.py library
  python3 generate.py plan
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from engine import (adapt, coach, dashboard, deliver, garmin, garmin_workout,    # noqa: E402
                    program, report, strava, workouts)
from engine.fit_encoder import write as write_fit                               # noqa: E402
from engine.models import WeekSummary, ordered_roles                            # noqa: E402

WORKOUTS_DIR = os.path.join(HERE, "workouts")

# Décalage (jours) du rôle par rapport au lundi de la semaine (week_start)
ROLE_OFFSET = {"quality": 1, "easy": 3, "long": 5, "b2b": 6}  # Mar/Jeu/Sam/Dim


# --------------------------------------------------------------------------- #
# Chargement des activités (fixture ou live) — partagé week/send
# --------------------------------------------------------------------------- #
def _load_activities(args):
    today = datetime.strptime(args.today, "%Y-%m-%d").date() if args.today else None
    if args.activities:
        return strava.load_activities_file(args.activities), today
    if getattr(args, "live", False):
        try:
            token = strava.refresh_access_token()
            now = datetime.now(timezone.utc)
            span_start = now - timedelta(days=7 * program.N_WEEKS + 7)
            return strava.fetch_activities(token, span_start, now), today
        except Exception as e:
            raise SystemExit(f"Erreur d'accès Strava : {e}\n"
                             "Vérifie STRAVA_CLIENT_ID/SECRET/REFRESH_TOKEN et le réseau.")
    return None, today


def _prescribed_prev_seconds(week_index, acts, today):
    """Temps PRESCRIT (adapté) de la semaine N-1, recalculé sans état.

    Compare l'adhérence à ce qui a réellement été demandé la semaine passée
    (et non au nominal), pour éviter la double peine / le tempérage perpétuel.
    """
    if week_index <= 1:
        return 0
    prev = program.week(week_index - 1)
    if acts is None:
        return int(program.planned_minutes(prev) * 60)
    ref = program.week_start(week_index - 1)  # lundi de la semaine N-1
    prev2_s = (int(program.planned_minutes(program.week(week_index - 2)) * 60)
               if week_index - 1 > 1 else 0)
    summ = strava.completed_week_summary(acts, prev2_s, today=ref)
    res_prev = adapt.adapt_week(prev, summ)
    return int(program.planned_minutes(res_prev.week) * 60)


def _prepare_week(week_index, acts, today):
    planned = program.week(week_index)
    if acts is None:
        last = WeekSummary(0, 0, 0, 0, 0, 0, data_available=False)
        actuals = [None] * program.N_WEEKS
        week_runs, history_runs = [], []
    else:
        planned_prev_s = _prescribed_prev_seconds(week_index, acts, today)
        last = strava.completed_week_summary(acts, planned_prev_s, today=today)
        actuals = strava.weekly_actual_hours(acts, program.PROGRAM_START,
                                             program.N_WEEKS, today=today)
        weeks = strava.recent_completed_weeks(acts, today=today, n=4)
        week_runs, history_runs = weeks[0], weeks[1:]
    res = adapt.adapt_week(planned, last)
    ws = program.upcoming_monday(today) - timedelta(days=7)
    analysis = coach.analyze(last, week_runs, history_runs, week_start=ws)
    return res, last, actuals, analysis


def _write_week(res, last, actuals, analysis, outdir, today):
    os.makedirs(outdir, exist_ok=True)
    files = {}
    for i, role in enumerate(ordered_roles(res.week.sessions), start=1):
        spec = res.week.sessions[role]
        fname = f"{i}_{role}_{workouts.slug(spec)}.fit"
        write_fit(workouts.build_workout(spec), os.path.join(outdir, fname))
        files[role] = fname
    with open(os.path.join(outdir, "rapport.md"), "w", encoding="utf-8") as f:
        f.write(report.week_report_md(res, last, files, analysis))
    with open(os.path.join(outdir, "rapport.json"), "w", encoding="utf-8") as f:
        json.dump(report.week_report_json(res, last, files, analysis), f,
                  ensure_ascii=False, indent=2)
    dash = dashboard.build(res, last, actuals, analysis, today=today)
    dash_path = os.path.join(outdir, "dashboard.html")
    with open(dash_path, "w", encoding="utf-8") as f:
        f.write(dash)
    return files, dash_path, dash


def _resolve_week(args, today):
    if args.week is not None:
        if not (1 <= args.week <= program.N_WEEKS):
            raise SystemExit(f"Semaine {args.week} hors programme (1..{program.N_WEEKS}).")
        return args.week
    return program.target_week_index(today)


def _push_garmin(res, idx):
    """Crée + planifie chaque séance sur Garmin (si configuré). Repli sinon."""
    if not garmin.is_configured():
        print("\n[garmin] non configuré (GARMIN_CONSUMER_KEY/SECRET/REFRESH_TOKEN) "
              "— push ignoré, email/FIT conservés.")
        return
    try:
        token = garmin.get_access_token()
    except Exception as e:
        print(f"\n[garmin] échec d'authentification : {e}\n"
              "         push ignoré, email/FIT conservés.")
        return
    print("\n[garmin] planification des séances :")
    for role in ordered_roles(res.week.sessions):
        spec = res.week.sessions[role]
        d = (program.week_start(idx) + timedelta(days=ROLE_OFFSET[role])).isoformat()
        try:
            wid = garmin.push_and_schedule(garmin_workout.session_to_garmin(spec), d,
                                           access_token=token)
            print(f"  ✓ {d}  {workouts.label(spec)}  (id {wid})")
        except Exception as e:
            print(f"  ✗ {d}  {workouts.label(spec)} — {e}")


def _print_summary(res, files, outdir):
    print(f"\n=== Semaine {res.week.index} — {res.week.phase} [{res.band}] ===")
    print(res.message)
    for role in ordered_roles(res.week.sessions):
        print(f"  {role:8} {workouts.label(res.week.sessions[role])}")
    print(f"\n{len(files)} séances .fit + rapport + dashboard → {outdir}")


# --------------------------------------------------------------------------- #
# Commandes
# --------------------------------------------------------------------------- #
def cmd_week(args):
    acts, today = _load_activities(args)
    idx = _resolve_week(args, today)
    res, last, actuals, analysis = _prepare_week(idx, acts, today)
    outdir = args.outdir or os.path.join(WORKOUTS_DIR, f"semaine_{idx:02d}")
    files, dash_path, _ = _write_week(res, last, actuals, analysis, outdir, today)
    _print_summary(res, files, outdir)
    if getattr(args, "push_garmin", False):
        _push_garmin(res, idx)


def cmd_send(args):
    # Garde-source : ne jamais expédier un plan non adapté sans le dire.
    if not args.activities and not args.live and not args.dry_run:
        raise SystemExit("`send` exige une source de données : --live, "
                         "--activities <fichier>, ou --dry-run pour tester sans envoyer.")
    acts, today = _load_activities(args)
    idx = _resolve_week(args, today)
    res, last, actuals, analysis = _prepare_week(idx, acts, today)
    outdir = args.outdir or os.path.join(WORKOUTS_DIR, f"semaine_{idx:02d}")
    files, dash_path, dash_html = _write_week(res, last, actuals, analysis, outdir, today)
    _print_summary(res, files, outdir)

    subject = f"🏃 Semaine {idx}/{program.N_WEEKS} — {res.week.phase} [{res.band}]"
    attachments = [os.path.join(outdir, f) for f in files.values()] + [dash_path]

    if args.dry_run:
        print("\n[dry-run] Email NON envoyé.")
        print(f"  Sujet : {subject}")
        print(f"  Pièces jointes : {len(attachments)} "
              f"({', '.join(os.path.basename(a) for a in attachments)})")
        return

    try:
        to = deliver.send_email(subject, deliver.email_body_html(dash_html),
                                attachments=attachments)
    except Exception as e:
        raise SystemExit(f"Échec de l'envoi email : {e}\n"
                         "Vérifie GMAIL_ADDRESS / GMAIL_APP_PASSWORD / MAIL_TO.")
    print(f"\n✉️  Email envoyé à {to} ({len(attachments)} pièces jointes).")

    if getattr(args, "push_garmin", False):
        _push_garmin(res, idx)


def cmd_library(args):
    os.makedirs(WORKOUTS_DIR, exist_ok=True)
    seen = {}
    for w in program.PROGRAM:
        for spec in w.sessions.values():
            seen.setdefault(workouts.slug(spec), spec)
    for key, spec in sorted(seen.items()):
        write_fit(workouts.build_workout(spec), os.path.join(WORKOUTS_DIR, f"{key}.fit"))
    print(f"{len(seen)} séances uniques générées dans {WORKOUTS_DIR}")


def cmd_plan(args):
    with open(os.path.join(HERE, "plan.md"), "w", encoding="utf-8") as f:
        f.write(report.plan_md())
    html = os.path.join(HERE, "plan.html")
    if os.path.exists(html):
        report.update_plan_html(html)
    print("plan.md régénéré" + (" + plan.html mis à jour" if os.path.exists(html) else ""))


def cmd_garmin_auth_url(args):
    verifier, challenge = garmin.make_pkce()
    print("1) Ouvre cette URL dans un navigateur et autorise l'accès :\n")
    print("   " + garmin.authorize_url(challenge))
    print("\n2) Après redirection, récupère le paramètre ?code=… puis lance :")
    print(f"   python3 generate.py garmin-auth-exchange --code <CODE> --verifier {verifier}")
    print("\n(Requiert GARMIN_CONSUMER_KEY et GARMIN_REDIRECT_URI en variables d'env.)")


def cmd_garmin_auth_exchange(args):
    tokens = garmin.exchange_code(args.code, args.verifier)
    print(json.dumps(tokens, ensure_ascii=False, indent=2))
    if "refresh_token" in tokens:
        print("\n➡️  Stocke ce refresh_token en variable d'env GARMIN_REFRESH_TOKEN.")


def main(argv=None):
    p = argparse.ArgumentParser(description="Moteur d'entraînement adaptatif backyard ultra")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add_src(sp):
        sp.add_argument("--activities", help="JSON d'activités Strava (fixture/export)")
        sp.add_argument("--live", action="store_true", help="Lit Strava en direct (env vars)")
        sp.add_argument("--today", help="Date de référence YYYY-MM-DD (tests)")
        sp.add_argument("--outdir", help="Dossier de sortie")

    pw = sub.add_parser("week", help="Génère une semaine adaptée (fit + rapport + dashboard)")
    pw.add_argument("week", type=int, nargs="?", help="Numéro de semaine (défaut : semaine courante)")
    add_src(pw)
    pw.add_argument("--push-garmin", action="store_true",
                    help="Planifie les séances sur Garmin si configuré (sinon ignoré)")
    pw.set_defaults(func=cmd_week)

    ps = sub.add_parser("send", help="Pipeline hebdo complet + envoi email")
    ps.add_argument("week", type=int, nargs="?", help="Numéro de semaine (défaut : semaine courante)")
    add_src(ps)
    ps.add_argument("--dry-run", action="store_true", help="Génère sans envoyer l'email")
    ps.add_argument("--push-garmin", action="store_true",
                    help="Planifie les séances sur Garmin si configuré (sinon ignoré)")
    ps.set_defaults(func=cmd_send)

    sub.add_parser("library", help="Génère toutes les séances nominales").set_defaults(func=cmd_library)
    sub.add_parser("plan", help="Régénère plan.md et plan.html").set_defaults(func=cmd_plan)

    pau = sub.add_parser("garmin-auth-url",
                         help="Étape 1 auth Garmin : imprime l'URL de consentement + le verifier")
    pau.set_defaults(func=cmd_garmin_auth_url)

    pex = sub.add_parser("garmin-auth-exchange",
                         help="Étape 2 auth Garmin : échange le code contre les tokens")
    pex.add_argument("--code", required=True, help="Code d'autorisation (paramètre ?code= du redirect)")
    pex.add_argument("--verifier", required=True, help="code_verifier imprimé à l'étape 1")
    pex.set_defaults(func=cmd_garmin_auth_exchange)

    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
