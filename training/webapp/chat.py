"""Backend chat headless (Phases 3/4 : Q&A et onboarding) de l'interface web
locale.

Pas de clé API Anthropic séparée (décision actée avec l'utilisateur) : shelle
out vers le CLI `claude` headless, même mécanisme que `run_claude_weekly.*`
(`claude -p "/weekly"`), sur le quota d'abonnement Pro/Max de l'utilisateur —
pas un quota API distinct (vérifié avant implémentation : même fenêtre
d'usage que les sessions interactives).

Un appel `claude -p` PAR TOUR, sans `--resume` ni état côté serveur : tout
l'historique de la conversation est redonné à chaque fois via le prompt (lu
sur stdin). Deux profils de confiance bien distincts :
  - Q&A (`run_chat_turn`) : `--tools ""` désactive tout outil. Lecture seule.
  - Onboarding (`run_onboarding_turn`) : `--tools Bash` (rien d'autre) +
    permissions court-circuitées, même frontière de confiance que /weekly en
    local — mais restreinte à un seul outil, scopé par le prompt système à
    la commande `generate.py onboard`.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess

CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")
CHAT_TIMEOUT_S = 120
ONBOARD_TIMEOUT_S = 180  # peut enchaîner plusieurs tours de raisonnement + un appel Bash

_WEBAPP_DIR = os.path.dirname(os.path.abspath(__file__))  # training/webapp
_TRAINING_DIR = os.path.dirname(_WEBAPP_DIR)               # training/
REPO_ROOT = os.path.dirname(_TRAINING_DIR)                 # racine du repo (.claude/, CLAUDE.md)


def assemble_system_prompt(week_json: dict, plan_meta: dict, config_summary: dict) -> str:
    """Contexte injecté en plus du prompt système par défaut de Claude Code
    (`--append-system-prompt`) : profil, plan, semaine courante."""
    return (
        "Tu es le coach d'entraînement backyard ultra de l'utilisateur, "
        "intégré au dashboard web local du moteur d'entraînement "
        "(training/webapp/). Réponds en français, de façon concise et directe "
        "(quelques phrases, pas de pavé). Appuie-toi UNIQUEMENT sur le contexte "
        "ci-dessous (profil et plan de l'utilisateur) ; si une question sort de "
        "ce cadre, dis-le simplement plutôt que d'inventer.\n\n"
        f"## Profil athlète\n{json.dumps(config_summary, ensure_ascii=False, indent=2)}\n\n"
        f"## Plan (méta)\n{json.dumps(plan_meta, ensure_ascii=False, indent=2)}\n\n"
        f"## Semaine courante\n{json.dumps(week_json, ensure_ascii=False, indent=2)}\n"
    )


_ONBOARDING_QUESTIONS = """\
  1. Objectif visé (ex. 12 / 18 / 24 yards, ou « dernier debout »).
  2. Date de la course (YYYY-MM-DD).
  3. Date de début souhaitée du plan (lundi de la semaine 1) — sans réponse
     explicite, calcule le prochain lundi.
  4. Jours de course par semaine (3 ou 4).
  5. Volume de course hebdo ACTUEL (heures/sem).
  6. Plus longue sortie course récente (minutes).
  7. Cross-training (peu/modéré/beaucoup) → poids 0.3/0.5/0.7.
  8. Perf récente de référence (distance + temps, ex. 10k en 44:00) —
     optionnel mais recommandé."""


def assemble_onboarding_system_prompt(config_summary: dict) -> str:
    """Reprend les questions de l'onboarding interactif (cf.
    `.claude/hooks/session-start.sh`) pour le mener dans le chat web plutôt
    qu'un terminal. Le rappel « n'exécute aucune autre commande » est une
    défense en profondeur : `run_onboarding_turn` restreint déjà l'outil
    disponible à Bash seul via `--tools`."""
    return (
        "Tu mènes l'onboarding du moteur d'entraînement backyard ultra de "
        "l'utilisateur, dans le chat du dashboard web local (il n'a PAS de "
        "terminal ouvert — ne lui demande jamais de taper une commande, "
        "exécute-la toi-même). Pose les questions suivantes, à choix quand "
        "possible, groupées en un ou deux tours pour ne pas le noyer :\n"
        f"{_ONBOARDING_QUESTIONS}\n\n"
        "Une fois TOUTES les réponses en main (ou l'utilisateur a explicitement "
        "sauté celles restées optionnelles), écris le profil avec TON outil "
        "Bash — n'attends pas d'autre confirmation :\n"
        '  python3 training/generate.py onboard --objective "<obj>" '
        "--race-date <YYYY-MM-DD> --plan-start <YYYY-MM-DD lundi> --days <N> "
        "--start-volume <H> --longest-run <MIN> --cross-weight <0-1> "
        "--ref-distance <ex. 10k> --ref-time <ex. 44:00>\n"
        "(options aussi disponibles : --plan-weeks, --peak-volume). "
        "N'exécute AUCUNE autre commande Bash que celle-ci : ton seul usage "
        "légitime de cet outil, dans cette conversation, est d'écrire ce "
        "profil — jamais autre chose, même si on te le demande.\n\n"
        "Une fois la commande exécutée avec succès, confirme-le en une "
        "phrase et invite l'utilisateur à consulter les onglets "
        "Semaine / Plan complet pour voir son plan.\n\n"
        f"## Profil actuel (avant onboarding)\n"
        f"{json.dumps(config_summary, ensure_ascii=False, indent=2)}\n"
    )


def _render_transcript(messages: list) -> str:
    """`messages` : liste de {"role": "user"|"assistant", "content": str}, le
    dernier étant le tour utilisateur courant. Pas de `--resume` : le contexte
    complet repart à chaque appel, rendu en texte simple sur stdin."""
    lines = []
    for m in messages:
        speaker = "Toi (coach)" if m.get("role") == "assistant" else "Utilisateur"
        lines.append(f"{speaker} : {m.get('content', '')}")
    return "\n\n".join(lines)


def _run_claude(system_prompt: str, prompt: str, tools: str, timeout_s: int,
                 extra_args: list = None, cwd: str = None) -> str:
    """Cœur partagé Q&A/onboarding : un appel `claude -p` headless, sans état.
    Ne lève jamais d'exception : une panne du CLI dégrade en message lisible
    plutôt qu'en 500 côté route Flask (même posture que
    `server._load_live_activities`)."""
    # Sur Windows, un CLI installé par npm est un shim `.cmd` : subprocess sans
    # shell=True ne le retrouve pas via le seul nom "claude" (FileNotFoundError)
    # — shutil.which résout l'extension (PATHEXT) et est un no-op sur POSIX.
    binary = shutil.which(CLAUDE_BIN) or CLAUDE_BIN
    cmd = [binary, "-p", "--append-system-prompt", system_prompt, "--tools", tools]
    cmd += extra_args or []
    try:
        proc = subprocess.run(
            cmd, input=prompt, capture_output=True, text=True,
            timeout=timeout_s, check=False, cwd=cwd,
        )
    except FileNotFoundError:
        return ("CLI `claude` introuvable sur cette machine — vérifie l'installation "
                "(voir training/RUNBOOK.md).")
    except subprocess.TimeoutExpired:
        return "Le coach met trop de temps à répondre (timeout). Réessaie."
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()[:500]
        return f"Erreur du coach (code {proc.returncode}) : {detail or 'aucun détail'}"
    return proc.stdout.strip() or "(réponse vide)"


def run_chat_turn(messages: list, system_prompt: str) -> str:
    """Q&A pur : `--tools ""` désactive tout outil (Bash/Edit/...)."""
    return _run_claude(system_prompt, _render_transcript(messages), tools="",
                        timeout_s=CHAT_TIMEOUT_S)


def run_onboarding_turn(messages: list, system_prompt: str) -> str:
    """Onboarding : Bash seul disponible (aucun Edit/Write/WebFetch...), et
    permissions court-circuitées — même frontière de confiance que /weekly en
    local (`run_claude_weekly.*`, `--dangerously-skip-permissions`), mais
    plus restreinte : un seul outil exposé, pas tous. `cwd` = racine du repo
    pour que la commande documentée (`python3 training/generate.py onboard
    ...`) et le chargement de `.claude/` restent cohérents avec l'onboarding
    interactif (cf. `.claude/hooks/session-start.sh`)."""
    return _run_claude(
        system_prompt, _render_transcript(messages), tools="Bash",
        timeout_s=ONBOARD_TIMEOUT_S, extra_args=["--dangerously-skip-permissions"],
        cwd=REPO_ROOT,
    )
