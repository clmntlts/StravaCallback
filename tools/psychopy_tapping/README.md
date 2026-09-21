# Analyse du tapping PsychoPy (tâche Simon + double tâche motrice)

Outil autonome, sans rapport avec le moteur d'entraînement du dépôt : il analyse
la cadence et la régularité des appuis (souris, pédale, boîtier) enregistrés par
un composant **Mouse** PsychoPy pendant la présentation des stimuli.

À partir d'un ou plusieurs fichiers de données PsychoPy, il produit **le
classeur de métriques et toutes les figures** — par essai, par condition et par
participant — dans un dossier daté créé à côté des données.

## Lancer l'analyse

```bash
pip install pandas numpy openpyxl matplotlib      # une seule fois
```

| Mode | Comment |
|---|---|
| **Double-clic** | `analyser_tapping.bat` (Windows) ou `analyser_tapping.command` (macOS) : une fenêtre demande les fichiers, puis un dossier si on annule |
| **Glisser-déposer** | déposer des fichiers **ou un dossier** sur le lanceur |
| **Ligne de commande** | `python3 analyser_tapping.py mes_donnees/ --target-iti 0.333` |

Un dossier est parcouru récursivement ; les `.xlsx`/`.csv` sans composant souris
(et les sorties d'analyses précédentes) sont ignorés, avec la raison dans
`journal.txt`.

### Options

| Option | Effet |
|---|---|
| `--out DOSSIER` | dossier de sortie (défaut : `analyse_tapping_<date>` à côté des données) |
| `--component foot_tapping` | choisit le composant souris (sinon détecté) |
| `--button left\|mid\|right\|any` | bouton considéré comme un appui (défaut `left`) |
| `--min-iti 0.05` | anti-rebond : fusionne deux appuis à moins de 50 ms |
| `--pause-factor 2.5` | un ITI > 2.5 × médiane de l'essai est compté comme pause |
| `--target-iti 0.333` | tempo consigne → métriques de synchronisation |
| `--by Condition Type` | colonnes de regroupement (résumé + figures par condition) |
| `--keep col1 col2` | colonnes supplémentaires à reporter |
| `--no-trial-plots` | pas de figures par essai (utile au-delà de ~500 essais) |
| `--no-plots`, `--no-open` | tables seulement / ne pas ouvrir le dossier à la fin |

`tap_analysis.py` reste utilisable seul pour les tables uniquement
(`python3 tap_analysis.py data/*.xlsx --out results/`).

### Fabriquer un vrai exécutable

`build_exe.bat` (Windows) ou `build_exe.sh` (macOS/Linux) produisent
`dist/AnalyseTapping(.exe)`, à distribuer à des postes sans Python. Le binaire
doit être fabriqué **sur le système cible** (PyInstaller ne compile pas d'un OS
à l'autre).

## Sorties

**Tables**

- `tapping_metrics.xlsx` — onglets `trials`, `taps`, `summary` ;
- `trials.csv` — **une ligne par essai**, avec les colonnes de condition du
  fichier PsychoPy (`Condition`, `Type`, `Stimuli`, `Location`, `participant`,
  index de boucle…) et toutes les métriques ci-dessous ;
- `taps_long.csv` — **un appui par ligne** (essai, index, temps, ITI, pause)
  pour les modèles mixtes ou les graphiques maison ;
- `summary.csv` — moyenne ± SD par condition ;
- `journal.txt` — fichiers traités, ignorés, totaux, liste des sorties.

**Figures**

| Fichier | Contenu |
|---|---|
| `essais_<participant>_raster.png` | un trait par appui, un rang par essai, pauses en orange |
| `essais_<participant>_iti.png` | petits multiples : l'ITI au fil de chaque essai |
| `essais_<participant>_resume.png` | cadence et irrégularité essai par essai |
| `conditions_<colonne>.png` | cadence et CV par condition (un point = un essai, moyenne ± SD, une ligne grise par participant) |
| `conditions_<colonne>_distribution_iti.png` | distribution des ITI par condition |
| `participants_resume.png` | cadence et régularité par participant (si plusieurs) |

Les figures par essai sont paginées (`_p1`, `_p2`, …) au-delà de 40 essais
(raster) ou 24 essais (ITI).

## Métriques par essai

**ITI** = inter-tap interval, l'intervalle entre deux appuis successifs.

| Famille | Colonnes | Lecture |
|---|---|---|
| Cadence | `n_taps`, `iti_mean`, `tap_rate_hz` (= 1/ITI moyen), `tap_rate_per_min` | vitesse du tapping |
| Régularité | `iti_sd`, `iti_cv` (SD/moyenne), `iti_iqr`, `iti_mad` | variabilité globale ; le **CV** est l'indice standard, sans unité, comparable entre cadences |
| Régularité locale | `rmssd`, `cv_rmssd`, `lag1_autocorr` | variabilité d'un appui au suivant ; `lag1_autocorr` < 0 = correction d'erreur (alternance court/long), > 0 = dérive lente |
| Dérive | `iti_slope_s_per_tap`, `iti_slope_r`, `rate_first_half_hz`, `rate_second_half_hz`, `drift_ratio` | accélération (< 1) ou ralentissement (> 1) au cours de l'essai |
| Isochronie | `fitted_period_s`, `isochrony_sd_s`, `isochrony_max_dev_s` | écart des temps d'appui à la meilleure droite « métronome » : capte la dérive cumulée, que le RMSSD ignore |
| Pauses | `n_pauses`, `longest_gap_s`, `paused_time_s`, `pause_threshold_s` | interruptions du tapping (typiquement pendant la réponse Simon) |
| Hors pauses | `clean_*` (mêmes métriques) | régularité une fois les pauses retirées — indispensable : une seule pause de 3 s fait passer le CV de 0.13 à 1.30. **C'est la version utilisée dans les figures** |
| Synchronisation (`--target-iti`) | `phase_locking_r` (0–1), `circular_sd_rad`, `iti_bias_s` | tenue du tempo consigne ; `iti_bias_s` > 0 = trop lent |
| Qualité | `n_short_merged`, `sampling`, `frame_quantized`, `frame_period_s` | rebonds fusionnés, mode d'enregistrement, quantification écran |

Trois colonnes d'identification sont ajoutées : `participant_id` (colonne
`participant`, sinon nom du fichier), `trial_no` / `trial_label` (`E07 · C`) et
`trial_key` (clé de jointure entre `trials` et `taps`).

## Ce que le script gère côté PsychoPy

- Cellules du type `[np.float64(0.23), np.float64(0.61)]` aussi bien que `[0.23, 0.61]`.
- Colonnes dupliquées par la boucle (`foot_tapping.time` **et**
  `Practice.foot_tapping.time`) : une seule série est retenue, le nom de la
  boucle est reporté dans la colonne `loop`.
- Composant enregistré « on click » (un échantillon par clic) **ou** « every
  frame » (un échantillon par frame) : dans le second cas seules les
  transitions relâché → appuyé sont comptées.
- Plusieurs fichiers / participants en une passe, y compris des fichiers de
  structures différentes.

## Limites connues

- **Temps relatifs au composant.** `<comp>.time` part de l'onset du composant
  souris, pas de l'onset du stimulus. Tant que le composant démarre avec le
  stimulus, `time_s` est bien le temps depuis l'apparition du stimulus.
- **Résolution = période écran.** Les appuis sont horodatés à la frame (~16,7 ms
  à 60 Hz), ce qui pose un plancher de variabilité d'environ 5 ms ; sans effet
  sur des ITI de 300 ms, mais à mentionner en méthodes.
- **Export Excel francisé.** Si le `.xlsx` a été produit par un Excel en locale
  FR, les colonnes de timing (`*.started`, `*.rt`, `frameRate`) ont perdu leur
  séparateur décimal (`29.25` → `2925028760000714`). Les listes d'appuis, en
  texte, ne sont pas touchées ; le script le signale et récupère `frameRate`,
  mais pour aligner les appuis sur les onsets/RT il faut repartir du **`.csv`
  PsychoPy** d'origine.

## Tests

```bash
cd tools/psychopy_tapping && python3 -m unittest discover
```
