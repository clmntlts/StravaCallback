#!/usr/bin/env bash
# Routine hebdo LOCALE avec Claude comme coach.
#
# Lance le CLI Claude Code en mode headless sur la commande /weekly, DEPUIS TA
# MACHINE (IP résidentielle) : Claude génère la semaine, la juge, envoie l'email
# et planifie sur Garmin Connect. À planifier via cron/launchd de ton OS.
#
# ⚠️ Ce n'est PAS la "Routine" cloud du produit (celle-ci tourne dans le cloud,
#    IP datacenter → Garmin bloqué). Ici tout tourne en local.
#
# Prérequis (une fois) :
#   - Claude Code installé et authentifié :  claude login   (ou ANTHROPIC_API_KEY)
#   - Secrets renseignés dans training/.env  (cp training/.env.example …)
#   - Login Garmin fait une fois :  python3 training/generate.py garmin-connect-login
#
# Cron (dimanche 19h, heure locale) :
#   0 19 * * 0  /chemin/StravaCallback/run_claude_weekly.sh >> /chemin/StravaCallback/training/logs/claude-cron.out 2>&1
set -euo pipefail

# Racine du projet = dossier de ce script (pour que Claude charge .claude/).
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

# 1) Charger les secrets locaux (jamais committés).
if [[ -f training/.env ]]; then
  set -a; # shellcheck disable=SC1091
  source training/.env; set +a
else
  echo "⚠️  training/.env introuvable — copie training/.env.example puis renseigne-le." >&2
fi

# 2) Binaire Claude + posture de permissions (surchargeables par l'environnement).
#    En run non-surveillé, --dangerously-skip-permissions évite tout prompt. C'est
#    puissant : n'utilise ça que sur TA machine de confiance. Alternative plus
#    stricte : remplacer par une allowlist, ex.
#      CLAUDE_PERM='--allowedTools Bash Read Edit'
CLAUDE_BIN="${CLAUDE_BIN:-claude}"
CLAUDE_PERM="${CLAUDE_PERM:---dangerously-skip-permissions}"

# 3) Journalisation horodatée.
mkdir -p training/logs
LOG="training/logs/claude-weekly-$(date +%Y-%m-%d).log"
echo "===== run $(date -Is) =====" | tee -a "$LOG"

# 4) Lancer Claude headless sur la commande /weekly. `-p` = mode non-interactif.
#    (Vérifie les drapeaux dispo avec `claude --help` selon ta version.)
set -o pipefail
"$CLAUDE_BIN" -p "/weekly" $CLAUDE_PERM 2>&1 | tee -a "$LOG"
rc=${PIPESTATUS[0]}

echo "===== fin $(date -Is) — code $rc =====" | tee -a "$LOG"
exit "$rc"
