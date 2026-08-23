#!/usr/bin/env python3
"""CLI du moteur d'entraînement adaptatif backyard ultra.

Exemples :

  # Semaine adaptative à partir d'un export d'activités (JSON) :
  python3 generate.py week 9 --activities tests/fixtures/last_week_sample.json

  # Semaine adaptative en direct depuis Strava (variables d'env requises) :
  python3 generate.py week 9 --live

  # Générer toute la bibliothèque de séances "nominales" :
  python3 generate.py library

  # Régénérer le plan (plan.md + plan.html) depuis le programme :
  python3 generate.py plan
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from engine import adapt, program, report, strava, workouts   # noqa: E402
from engine.fit_encoder import write as write_fit             # noqa: E402
from engine.models import ROLES, WeekSummary                  # noqa: E402

WORKOUTS_DIR = os.path.join(HERE, "workouts")


# --------------------------------------------------------------------------- #
def _last_week_summary(args, week_index: int) -> WeekSummary:
    """Construit la synthèse de la semaine N-1 selon la source choisie."""
    planned_prev_s = 0
    if week_index > 1:
        planned_prev_s = int(program.planned_minutes(program.week(week_index - 1)) * 60)

    today = datetime.strptime(args.today, "%Y-%m-%d").date() if args.today else None

    if args.activities:
        acts = strava.load_activities_file(args.activities)
        return strava.last_week_summary(acts, planned_prev_s, today=today)

    if args.live:
        token = strava.refresh_access_token()
        from datetime import timedelta, timezone
        now = datetime.now(timezone.utc)
        acts = strava.fetch_activities(token, now - timedelta(days=35), now)
        return strava.last_week_summary(acts, planned_prev_s, today=today)

    # Pas de source : on suppose la semaine précédente conforme (nominal).
    return WeekSummary(0, planned_prev_s, 0, 0, 0, planned_prev_s)


def cmd_week(args):
    planned = program.week(args.week)
    last = _last_week_summary(args, args.week)
    res = adapt.adapt_week(planned, last)

    outdir = args.outdir or os.path.join(WORKOUTS_DIR, f"semaine_{args.week:02d}")
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
        json.dump(report.week_report_json(res, last, files), f,
                  ensure_ascii=False, indent=2)

    print(f"\n=== Semaine {args.week} — {res.week.phase} "
          f"[{res.band}] ===")
    print(res.message)
    for role in [r for r in ROLES if r in res.week.sessions]:
        print(f"  {role:8} {workouts.label(res.week.sessions[role])}")
    print(f"\n{len(files)} séances .fit + rapport écrits dans {outdir}")


def cmd_library(args):
    os.makedirs(WORKOUTS_DIR, exist_ok=True)
    seen = {}
    n = 0
    for w in program.PROGRAM:
        for spec in w.sessions.values():
            key = workouts.slug(spec)
            if key in seen:
                continue
            seen[key] = spec
    for i, (key, spec) in enumerate(sorted(seen.items()), start=1):
        write_fit(workouts.build_workout(spec),
                  os.path.join(WORKOUTS_DIR, f"{key}.fit"))
        n += 1
    print(f"{n} séances uniques générées dans {WORKOUTS_DIR}")


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

    pw = sub.add_parser("week", help="Génère une semaine adaptée au réalisé N-1")
    pw.add_argument("week", type=int, help="Numéro de semaine (1..34)")
    pw.add_argument("--activities", help="JSON d'activités Strava (fixture/export)")
    pw.add_argument("--live", action="store_true", help="Lit Strava en direct (env vars)")
    pw.add_argument("--today", help="Date de référence YYYY-MM-DD (tests)")
    pw.add_argument("--outdir", help="Dossier de sortie")
    pw.set_defaults(func=cmd_week)

    pl = sub.add_parser("library", help="Génère toutes les séances nominales")
    pl.set_defaults(func=cmd_library)

    pp = sub.add_parser("plan", help="Régénère plan.md et plan.html")
    pp.set_defaults(func=cmd_plan)

    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
