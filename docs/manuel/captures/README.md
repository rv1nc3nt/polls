<!-- SPDX-License-Identifier: 0BSD -->

# Captures d'écran du manuel

- `*.html` — le balisage réel de chaque écran. C'est la **source**. Chaque
  fichier renvoie à la feuille de style et aux scripts de l'application
  elle-même (`src/static/`), par un chemin relatif : il n'en existe qu'un
  exemplaire, et une modification du style n'apparaît qu'une fois dans
  l'historique. Une capture s'ouvre hors ligne depuis n'importe quelle copie
  du dépôt. `outils/capture.css` ne contient qu'une règle propre aux captures.
- `img/*.png` — le rendu de ces mêmes pages, c'est ce que le manuel affiche.

## Régénérer

À chaque version publiée, avant l'étiquette : les captures suivent les gabarits,
et un écran modifié depuis la dernière régénération apparaîtrait autrement
dans le manuel tel qu'il était.

```sh
# 1. base de démonstration, jetable : DJANGO_DB_PATH la tient à l'écart de
#    var/dev.sqlite3, que cette recette ne touche pas
export DJANGO_SETTINGS_MODULE=config.settings.dev PYTHONPATH=src
export DJANGO_DB_PATH="$(mktemp -d)/captures.sqlite3"
uv run python manage.py migrate
uv run python docs/manuel/captures/outils/demo_seed.py

# 2. HTML de chaque écran dans docs/manuel/captures/
uv run python docs/manuel/captures/outils/render_captures.py

# 3. HTML -> PNG dans docs/manuel/captures/img/ (navigateur sans affichage)
mkdir -p docs/manuel/captures/img
for f in docs/manuel/captures/*.html; do
  b=$(basename "$f" .html)
  chrome-headless-shell --headless --disable-gpu --no-sandbox --hide-scrollbars \
    --allow-file-access-from-files \
    --window-size=1360,9000 --screenshot="docs/manuel/captures/img/$b.png" "file://$PWD/$f"
  convert "docs/manuel/captures/img/$b.png" -bordercolor white -border 1 \
    -trim +repage -bordercolor white -border 24 "docs/manuel/captures/img/$b.png"
done
```

`--allow-file-access-from-files` laisse la page charger, sous `file://`, les
polices que la feuille de style désigne : sans lui, le navigateur les refuse et
la capture s'affiche dans une police de substitution.

Toute commande de capture d'un navigateur sans affichage convient à l'étape 3
(`chromium --headless`, `google-chrome --headless`, Playwright…). Le
rognage `convert` (ImageMagick) enlève le blanc en bas de page ; il est
facultatif.

## Inventaire

| Fichier | Écran | Acteur |
|---|---|---|
| `01-site-public-liste.html` | Liste publique des consultations | électeur |
| `02-site-public-scrutin-annonce.html` | Page publique d'un scrutin annoncé, pas encore ouvert | électeur |
| `02a-site-public-scrutin.html` | Page publique d'un scrutin ouvert | électeur |
| `03-inscription-formulaire.html` | Formulaire d'inscription | électeur |
| `04-inscription-confirmee.html` | Accusé — courriel de confirmation envoyé | électeur |
| `05-inscription-en-examen.html` | Accusé — inscription mise en examen | électeur |
| `06-mairie-connexion.html` | Connexion à l'espace mairie | espace mairie |
| `07-bulletin-vote.html` | Bulletin — premier vote | électeur |
| `08-bulletin-modification.html` | Bulletin — modification | électeur |
| `09-bulletin-deja-enregistre.html` | Message « vote déjà enregistré » | électeur |
| `10-mairie-index-scrutins.html` | Liste des scrutins de l'espace mairie | espace mairie |
| `11-mairie-tableau-de-bord.html` | Tableau de bord d'un scrutin | espace mairie |
| `12-mairie-configuration-annoncee.html` | Configuration en lecture seule (scrutin annoncé), avec *Ouvrir maintenant* | espace mairie |
| `12a-mairie-configuration-cloture-manuelle.html` | Configuration (scrutin ouvert, échéance dépassée), avec *Clôturer maintenant* | espace mairie |
| `12b-mairie-configuration-lecture.html` | Configuration en lecture seule (scrutin ouvert) | espace mairie |
| `13-mairie-configuration-brouillon.html` | Configuration modifiable (brouillon), avec *Annoncer* | espace mairie |
| `14-mairie-file-inscriptions.html` | File d'attente des inscriptions | espace mairie |
| `15-mairie-import-liste.html` | Écran 3 (commune) : dépôt du fichier et consultation de la liste de travail en vigueur | espace mairie |
| `15a-mairie-liste-electorale-scrutin.html` | Copie figée de la liste électorale d'un scrutin ouvert, browsable | espace mairie |
| `16-mairie-bulletin-papier.html` | Saisie d'un bulletin papier — recherche | espace mairie |
| `16a-mairie-bulletin-papier-recherche.html` | Résultats de recherche d'électeur | espace mairie |
| `16b-mairie-bulletin-papier-collision.html` | Interstitiel « a déjà voté en ligne » | espace mairie |
| `16c-mairie-recu-papier.html` | Reçu de vote papier (imprimable) | espace mairie |
| `16d-mairie-bulletins-papier-liste.html` | Liste des bulletins papier saisis | espace mairie |
| `17-mairie-depouillement.html` | Clôture et publication | espace mairie |
| `18-mairie-comptes.html` | Comptes opérateurs | espace mairie |
| `19-mairie-roles.html` | Rôles par scrutin | espace mairie |
| `20-site-public-resultats.html` | Page publique de résultats | électeur |
| `21-mairie-journal-audit.html` | Journal d'audit | espace mairie |
| `22-mairie-parametres-commune.html` | Paramètres de la commune | espace mairie |
