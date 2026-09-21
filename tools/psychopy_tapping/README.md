# Analyse du tapping PsychoPy (tâche Simon + double tâche motrice)

Outil autonome, sans rapport avec le moteur d'entraînement du dépôt : il analyse
la cadence et la régularité des clics (souris, pédale, boîtier) enregistrés par
un composant **Mouse** PsychoPy pendant la présentation des stimuli.

```bash
pip install pandas numpy openpyxl matplotlib      # matplotlib seulement pour --plots
python3 tools/psychopy_tapping/tap_analysis.py data/*.xlsx --out results/ --plots
```

Options utiles :

| Option | Effet |
|---|---|
| `--component foot_tapping` | choisit le composant souris (sinon détecté) |
| `--button left\|mid\|right\|any` | bouton considéré comme un tap (défaut `left`) |
| `--min-iti 0.05` | anti-rebond : fusionne deux appuis à moins de 50 ms |
| `--pause-factor 2.5` | un ITI > 2.5 × médiane de l'essai est compté comme pause |
| `--target-iti 0.333` | tempo consigne → métriques de synchronisation |
| `--by Condition Type` | colonnes d'agrégation du résumé |
| `--keep col1 col2` | colonnes supplémentaires à reporter |

## Sorties (`--out`)

- `trials.csv` — **une ligne par essai**, avec les colonnes de condition du
  fichier PsychoPy (`Condition`, `Type`, `Stimuli`, `Location`, `participant`,
  index de boucle…) et toutes les métriques ci-dessous ;
- `taps_long.csv` — **un tap par ligne** (essai, index, temps, ITI, pause) pour
  les analyses en modèle mixte ou les graphiques maison ;
- `summary.csv` — moyenne ± SD par condition ;
- `tapping_metrics.xlsx` — les trois tables en onglets ;
- `tap_raster.png`, `iti_series.png`, `trial_summary.png` avec `--plots`.

## Métriques par essai

**ITI** = inter-tap interval, l'intervalle entre deux appuis successifs.

| Famille | Colonnes | Lecture |
|---|---|---|
| Cadence | `n_taps`, `iti_mean`, `tap_rate_hz` (= 1/ITI moyen), `tap_rate_per_min` | vitesse du tapping |
| Régularité | `iti_sd`, `iti_cv` (SD/moyenne), `iti_iqr`, `iti_mad` | variabilité globale ; le **CV** est l'indice standard, sans unité, comparable entre cadences |
| Régularité locale | `rmssd`, `cv_rmssd`, `lag1_autocorr` | variabilité d'un tap au suivant ; `lag1_autocorr` < 0 = correction d'erreur (alternance court/long), > 0 = dérive lente |
| Dérive | `iti_slope_s_per_tap`, `iti_slope_r`, `rate_first_half_hz`, `rate_second_half_hz`, `drift_ratio` | accélération (< 1) ou ralentissement (> 1) au cours de l'essai |
| Isochronie | `fitted_period_s`, `isochrony_sd_s`, `isochrony_max_dev_s` | écart des temps de tap à la meilleure droite « métronome » : capte la dérive cumulée, que le RMSSD ignore |
| Pauses | `n_pauses`, `longest_gap_s`, `paused_time_s`, `pause_threshold_s` | interruptions du tapping (typiquement pendant la réponse Simon) |
| Hors pauses | `clean_*` (mêmes métriques) | régularité une fois les pauses retirées — indispensable : une seule pause de 3 s fait passer le CV de 0.13 à 1.30 |
| Synchronisation (`--target-iti`) | `phase_locking_r` (0–1), `circular_sd_rad`, `iti_bias_s` | tenue du tempo consigne ; `iti_bias_s` > 0 = trop lent |
| Qualité | `n_short_merged`, `sampling`, `frame_quantized`, `frame_period_s` | rebonds fusionnés, mode d'enregistrement, quantification écran |

## Ce que le script gère côté PsychoPy

- Cellules du type `[np.float64(0.23), np.float64(0.61)]` aussi bien que `[0.23, 0.61]`.
- Colonnes dupliquées par la boucle (`foot_tapping.time` **et**
  `Practice.foot_tapping.time`) : une seule série est retenue, le nom de la
  boucle est reporté dans la colonne `loop`.
- Composant enregistré « on click » (un échantillon par clic) **ou** « every
  frame » (un échantillon par frame) : dans le second cas seules les
  transitions relâché → appuyé sont comptées.

## Limites connues

- **Temps relatifs au composant.** `<comp>.time` part de l'onset du composant
  souris, pas de l'onset du stimulus. Tant que le composant démarre avec le
  stimulus, `time_s` est bien le temps depuis l'apparition du stimulus.
- **Résolution = période écran.** Les taps sont horodatés à la frame (~16,7 ms
  à 60 Hz), ce qui pose un plancher de variabilité d'environ 5 ms ; sans effet
  sur des ITI de 300 ms, mais à mentionner en méthodes.
- **Export Excel francisé.** Si le `.xlsx` a été produit par un Excel en locale
  FR, les colonnes de timing (`*.started`, `*.rt`, `frameRate`) ont perdu leur
  séparateur décimal (`29.25` → `2925028760000714`). Les listes de taps, en
  texte, ne sont pas touchées ; le script le signale et récupère `frameRate`,
  mais pour aligner les taps sur les onsets/RT il faut repartir du **`.csv`
  PsychoPy** d'origine.
