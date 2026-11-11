# EnkiFlux

EnkiFlux est une application de veille technologique centrée sur le cloud, la sécurité, l'IA, les TI, la finance et la politique autour de l'informatique.
L'outil parfait pour rester à jour.

## Fichiers

| Fichier | Rôle |
|---|---|
| `index.html` | La page (site statique publié par GitHub Pages). |
| `data.json` | Les articles du jour, par rubrique (15 au plus par rubrique, de 10 jours au plus). |
| `archive.json` | Les articles sortis de la sélection (plus de 10 jours, ou remplacés). Rien n'en est retiré. Affichés en bas de page dans « Archives ». |
| `scripts/update.py` | La collecte : une requête à l'API Anthropic (recherche web) par rubrique. |
| `.github/workflows/enkiflux.yml` | La tâche quotidienne. |

## Mise à jour quotidienne

Du lundi au vendredi à 7 h (heure de Montréal), le workflow GitHub Actions `EnkiFlux mise à jour` lance `scripts/update.py`, puis commite `data.json` et `archive.json`. GitHub Pages republie ensuite le site.

Le workflow est planifié à 9 h et à 10 h UTC et ne s'exécute réellement qu'à celle des deux heures qui correspond à 7 h à Montréal (heure d'été ou d'hiver). Il peut aussi être lancé à la main (onglet Actions, « Run workflow »).

Configuration du dépôt :
- secret `ANTHROPIC_API_KEY` (obligatoire) ;
- variable `ANTHROPIC_MODEL` (facultative, `claude-sonnet-5-5` par défaut).

## Tri et mise en avant

- Dans chaque rubrique, les articles sont classés du plus récent au moins récent.
- « À la une » et l'article vedette de chaque rubrique sont choisis selon l'importance (failles exploitées, décisions réglementaires, annonces majeures).

## Maîtrise du coût

- Le modèle reçoit les URL déjà connues et ne recherche que ce qui est paru depuis la dernière collecte.
- 10 recherches web au plus par rubrique, avec filtrage des résultats avant lecture par le modèle.
- Le journal de chaque exécution affiche les tokens consommés, le nombre de recherches et le coût estimé.
