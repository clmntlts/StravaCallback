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

from engine import adapt, dashboard, deliver, program, report, strava, workouts  # noqa: E402
from engine.fit_encoder import write as write_fit                               # noqa: E402
from engine.models import ROLES, WeekSummary                                    # noqa: E402

WORKOUTS_DIR = os.path.join(HERE, "workouts")


# --------------------------------------------------------------------------- #
# Chargement des activités (fixture ou live) — partagé week/send
# --------------------------------------------------------------------------- #
def _load_activities(args):
    today = datetime.strptime(args.today, "%Y-%m-%d").date() if args.today else None
    if args.activities:
        return strava.load_activities_file(args.activities), today
    if getattr(args, "live", False):
        token = strava.refresh_access_token()
        now = datetime.now(timezone.utc)
        span_start = now - timedelta(days=7 * program.N_WEEKS + 7)
        return strava.fetch_activities(token, span_start, now), today
    return None, today


def _prepare_week(week_index, acts, today):
    planned = program.week(week_index)
    planned_prev_s = 0
    if week_index > 1:
        planned_prev_s = int(program.planned_minutes(program.week(week_index - 1)) * 60)
    if acts is None:
        last = WeekSummary(0, planned_prev_s, 0, 0, 0, planned_prev_s)
        actuals = [None] * program.N_WEEKS
    else:
        last = strava.last_week_summary(acts, planned_prev_s, today=today)
        actuals = strava.weekly_actual_hours(acts, program.PROGRAM_START,
                                             program.N_WEEKS, today=today)
    res = adapt.adapt_week(planned, last)
    return res, last, actuals


def _write_week(res, last, actuals, outdir, today):
    os.makedirs(outdir, exist_ok=True)
    files = {}
    for i, role in enumerate([r for r in ROLES if r in res.week.sessions], start=1):
        spec = res.week.sessions[role]
        fname = f"{i}_{role}_{workouts.slug(spec)}.fit"
        write_fit(workouts.build_workout(spec), os.path.join(outdir, fname))
        files[role] = fname
    with open(os.path.join(outdir, "rapport.md"), "w", encoding="utf-8") as f:
        f.write(report.week_report_md(res, last, files))
    with open(os.path.join(outdir, "rapport.json"), "w", encoding="utf-8") as f:
        json.dump(report.week_report_json(res, last, files), f, ensure_ascii=False, indent=2)
    dash = dashboard.build(res, last, actuals, today=today)
    dash_path = os.path.join(outdir, "dashboard.html")
    with open(dash_path, "w", encoding="utf-8") as f:
        f.write(dash)
    return files, dash_path, dash


def _print_summary(res, files, outdir):
    print(f"\n=== Semaine {res.week.index} — {res.week.phase} [{res.band}] ===")
    print(res.message)
    for role in [r for r in ROLES if r in res.week.sessions]:
        print(f"  {role:8} {workouts.label(res.week.sessions[role])}")
    print(f"\n{len(files)} séances .fit + rapport + dashboard → {outdir}")


# --------------------------------------------------------------------------- #
# Commandes
# --------------------------------------------------------------------------- #
def cmd_week(args):
    acts, today = _load_activities(args)
    idx = args.week or program.current_week_index(today)
    res, last, actuals = _prepare_week(idx, acts, today)
    outdir = args.outdir or os.path.join(WORKOUTS_DIR, f"semaine_{idx:02d}")
    files, dash_path, _ = _write_week(res, last, actuals, outdir, today)
    _print_summary(res, files, outdir)


def cmd_send(args):
    acts, today = _load_activities(args)
    idx = args.week or program.current_week_index(today)
    res, last, actuals = _prepare_week(idx, acts, today)
    outdir = args.outdir or os.path.join(WORKOUTS_DIR, f"semaine_{idx:02d}")
    files, dash_path, dash_html = _write_week(res, last, actuals, outdir, today)
    _print_summary(res, files, outdir)

    subject = f"🏃 Semaine {idx}/{program.N_WEEKS} — {res.week.phase} [{res.band}]"
    attachments = [os.path.join(outdir, f) for f in files.values()] + [dash_path]

    if args.dry_run:
        print(f"\n[dry-run] Email NON envoyé.")
        print(f"  Sujet : {subject}")
        print(f"  Pièces jointes : {len(attachments)} "
              f"({', '.join(os.path.basename(a) for a in attachments)})")
        return

    to = deliver.send_email(subject, deliver.email_body_html(dash_html),
                            attachments=attachments)
    print(f"\n✉️  Email envoyé à {to} ({len(attachments)} pièces jointes).")


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
    pw.set_defaults(func=cmd_week)

    ps = sub.add_parser("send", help="Pipeline hebdo complet + envoi email")
    ps.add_argument("week", type=int, nargs="?", help="Numéro de semaine (défaut : semaine courante)")
    add_src(ps)
    ps.add_argument("--dry-run", action="store_true", help="Génère sans envoyer l'email")
    ps.set_defaults(func=cmd_send)

    sub.add_parser("library", help="Génère toutes les séances nominales").set_defaults(func=cmd_library)
    sub.add_parser("plan", help="Régénère plan.md et plan.html").set_defaults(func=cmd_plan)

    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
