# EnkiFlux

EnkiFlux est une application de veille technologique centrée sur le Cloud, La sécurité, l'IA et la politique autour de l'informatique. 
L'outil parfait pour rester au jour. 

Site statique : `index.html` (la page) + `data.json` (les articles). Seul `data.json` change chaque jour.

## Mise à jour quotidienne
Chaque matin à 9 h, la tâche planifiée de Claude remplace le contenu de `data.json` dans le dépôt. GitHub Pages republie le site automatiquement.
