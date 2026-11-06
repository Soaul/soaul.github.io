# Veille GIRO

Site statique : `index.html` (la page) + `data.json` (les articles). Seul `data.json` change chaque jour.

## Mise en ligne (GitHub Pages)
1. Sur GitHub, crée un dépôt (public, pour que Pages soit gratuit), par exemple `veille`.
2. Dépose les fichiers `index.html`, `data.json`, `.nojekyll` et `README.md` à la racine du dépôt (bouton « Add file » > « Upload files »).
3. Dépôt > Settings > Pages > Source : « Deploy from a branch », branche `main`, dossier `/ (root)`. Enregistre.
4. Après une minute, le site est en ligne sur `https://TON-COMPTE.github.io/veille/`.

## Nom de domaine (optionnel)
1. Achète un domaine (Cloudflare, Namecheap, registraire .ca accrédité CIRA).
2. Dépôt > Settings > Pages > Custom domain : saisis ton domaine, puis coche « Enforce HTTPS ».
3. Chez le registraire, crée les enregistrements DNS indiqués par GitHub (un CNAME vers `TON-COMPTE.github.io` pour un sous-domaine comme `veille.exemple.ca`).

## Mise à jour quotidienne
Chaque matin à 9 h, la tâche planifiée de Claude remplace le contenu de `data.json` dans le dépôt. GitHub Pages republie le site automatiquement.
