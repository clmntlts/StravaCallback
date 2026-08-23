# Préparation Backyard Ultra 🏃‍♂️🌲

Coaching + séances structurées pour ta backyard ultra d'avril
(objectif **18-24 yards**), livrées au format **`.FIT`** importable sur Garmin.

## Contenu

| Fichier | Rôle |
|---|---|
| `plan.md` | Le plan sur **34 semaines** (calendrier semaine par semaine). |
| `workouts/*.fit` | **25 séances structurées** prêtes à importer dans Garmin Connect. |
| `build_workouts.py` | Génère les `.FIT` à partir de **tes allures** (à éditer). |
| `build_plan.py` | Génère `plan.md`. |
| `fit_encoder.py` | Encodeur FIT maison (aucune dépendance). |

## Importer les séances sur ta Garmin

1. Va sur **Garmin Connect** (web : connect.garmin.com).
2. **Entraînement & planification → Entraînements → Importer**.
3. Sélectionne un fichier `workouts/XX_....fit`. Répète pour chaque séance
   (à ne faire **qu'une fois** : ce sont des modèles réutilisables).
4. Depuis l'appli/le web, **envoie la séance vers la montre** ou
   **planifie-la sur une date** du calendrier — elle se synchronise à la
   prochaine synchro de la montre.
5. Sur la montre : *Entraînement → Séances* → tu suis les étapes, la montre
   te guide (durée, allure cible, bips de transition).

> Astuce : plutôt que d'importer les 25 d'un coup, importe au fil des semaines
> celles dont tu as besoin. Le `plan.md` te dit exactement laquelle faire quand.

## ⚙️ Personnaliser tes allures (important)

Les allures par défaut sont calées pour un coureur à ~30-50 km/sem. Pour les
adapter aux tiennes :

1. Ouvre `build_workouts.py`, édite le dictionnaire **`PACES`** (min/km).
2. Relance :
   ```bash
   python3 build_workouts.py
   ```
3. Réimporte les `.FIT` modifiés dans Garmin Connect.

### Recalibrage automatique via Strava

Le connecteur **Strava** est installé mais **désactivé dans ce chat**. Active-le
dans les réglages de connecteurs de la conversation : je lirai alors ton
historique (volume, allures endurance/seuil, D+, régularité) et je re-calerai
`PACES` + le plan sur tes vraies données.

## Rappels backyard (le format qui change tout)

- **Boucle de 6,7 km à relancer chaque heure, à l'heure pile.** Ce qui te sort
  n'est jamais la vitesse : c'est la **gestion** (allure basse, nutrition,
  pieds, sommeil, mental). Le plan est construit là-dessus.
- **Vise ~48-52 min par boucle** en début de course : tu cours "trop
  facile", tu ranges du temps pour manger/pisser/te changer. Les séances
  *Simu Backyard* t'entraînent exactement à ce rythme boucle + repos.
- **Mange et bois à CHAQUE boucle**, dès le début. Les séances *Marche-course*
  et *Simu Backyard* servent à roder ton estomac et ton ravito.
- **Entraîne la nuit et les jambes fatiguées** : c'est le rôle des sorties de
  nuit et des week-ends *back-to-back* (B2B).
- **Le repos fait partie du plan** : les semaines 🟢 de décharge, tu lèves le
  pied pour vraiment progresser. Ne les saute pas.

*Séances générées et validées (CRC + parsing FIT). Ajuste, relance, cours.*
