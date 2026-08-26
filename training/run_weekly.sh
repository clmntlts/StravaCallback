#!/usr/bin/env bash
# Lancement hebdomadaire LOCAL du moteur d'entraînement (pour cron).
#
# Charge training/.env, génère + envoie la semaine, planifie sur Garmin Connect,
# et journalise le tout. Conçu pour tourner sur TA machine (IP résidentielle) :
# le login Garmin et le refresh des jetons y fonctionnent, contrairement au cloud.
#
# Usage :
#   ./training/run_weekly.sh              # génère, envoie l'email, planifie Garmin
#   ./training/run_weekly.sh --dry-run    # génère SANS envoyer (test)
#   ./training/run_weekly.sh 12           # force la semaine 12
#   (tout argument est transmis tel quel à `generate.py send`)
#
# Cron (dimanche 19h) :
#   0 19 * * 0  /chemin/StravaCallback/training/run_weekly.sh >> /chemin/cron.out 2>&1
set -euo pipefail

# Répertoire de ce script = .../training, quel que soit le cwd de cron.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 1) Charger les secrets locaux depuis training/.env (jamais committé).
if [[ -f .env ]]; then
  set -a                      # exporte automatiquement les variables sourcées
  # shellcheck disable=SC1091
  source .env
  set +a
else
  echo "⚠️  training/.env introuvable — copie training/.env.example puis renseigne-le." >&2
  echo "    (Les variables déjà présentes dans l'environnement sont tout de même utilisées.)" >&2
fi

# 2) Push Garmin Connect seulement si des identifiants sont là ; sinon on se
#    contente de l'email + FIT (le moteur ignore proprement le push de toute façon).
PUSH_ARGS=()
if [[ -n "${GARMIN_EMAIL:-}" && -n "${GARMIN_PASSWORD:-}" ]] || [[ -n "${GARMIN_TOKENS_BASE64:-}" ]]; then
  PUSH_ARGS+=(--push-connect)
fi

# 3) Journalisation horodatée.
mkdir -p logs
LOG="logs/weekly-$(date +%Y-%m-%d).log"
echo "===== run $(date -Is) =====" | tee -a "$LOG"

# 4) Exécuter. `--live` récupère Strava en direct. Les arguments de l'appelant
#    (ex. --dry-run, un numéro de semaine) passent APRÈS et priment.
set -o pipefail
python3 generate.py send --live "${PUSH_ARGS[@]}" "$@" 2>&1 | tee -a "$LOG"
rc=${PIPESTATUS[0]}

echo "===== fin $(date -Is) — code $rc =====" | tee -a "$LOG"
exit "$rc"
