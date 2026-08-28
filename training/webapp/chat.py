"""Backend chat headless (Phase 3, Q&A) de l'interface web locale.

Pas de clé API Anthropic séparée (décision actée avec l'utilisateur) : shelle
out vers le CLI `claude` headless, même mécanisme que `run_claude_weekly.*`
(`claude -p "/weekly"`), sur le quota d'abonnement Pro/Max de l'utilisateur —
pas un quota API distinct (vérifié avant implémentation : même fenêtre
d'usage que les sessions interactives).

Un appel `claude -p` PAR TOUR, sans `--resume` ni état côté serveur : tout
l'historique de la conversation est redonné à chaque fois via le prompt (lu
sur stdin). `--tools ""` désactive tout outil (Bash/Edit/...) : ce chat est
un pur Q&A en lecture seule sur le plan, pas un agent qui modifie des
fichiers (cf. Phase 4 / onboarding pour l'usage d'outils).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess

CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")
CHAT_TIMEOUT_S = 120


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


def _render_transcript(messages: list) -> str:
    """`messages` : liste de {"role": "user"|"assistant", "content": str}, le
    dernier étant le tour utilisateur courant. Pas de `--resume` : le contexte
    complet repart à chaque appel, rendu en texte simple sur stdin."""
    lines = []
    for m in messages:
        speaker = "Toi (coach)" if m.get("role") == "assistant" else "Utilisateur"
        lines.append(f"{speaker} : {m.get('content', '')}")
    return "\n\n".join(lines)


def run_chat_turn(messages: list, system_prompt: str) -> str:
    """Un tour de chat = un appel `claude -p` headless, sans état. Ne lève
    jamais d'exception : une panne du CLI dégrade en message lisible plutôt
    qu'en 500 côté route Flask (même posture que `_load_live_activities`)."""
    prompt = _render_transcript(messages)
    # Sur Windows, un CLI installé par npm est un shim `.cmd` : subprocess sans
    # shell=True ne le retrouve pas via le seul nom "claude" (FileNotFoundError)
    # — shutil.which résout l'extension (PATHEXT) et est un no-op sur POSIX.
    binary = shutil.which(CLAUDE_BIN) or CLAUDE_BIN
    cmd = [binary, "-p", "--append-system-prompt", system_prompt, "--tools", ""]
    try:
        proc = subprocess.run(
            cmd, input=prompt, capture_output=True, text=True,
            timeout=CHAT_TIMEOUT_S, check=False,
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
