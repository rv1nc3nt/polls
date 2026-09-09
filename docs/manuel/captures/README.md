<!-- SPDX-License-Identifier: 0BSD -->

# Captures d'écran du manuel

Chaque fichier `*.html` de ce dossier est une capture d'un écran réel de
l'application, rendue à partir d'une instance de démonstration et livrée avec sa
feuille de style intégrée, donc consultable hors ligne dans n'importe quel
navigateur.

## Régénérer les captures

```sh
# 1. base de démonstration (settings dev, SQLite jetable)
rm -f var/dev.sqlite3
DJANGO_SETTINGS_MODULE=config.settings.dev PYTHONPATH=src \
  uv run python manage.py migrate
PYTHONPATH=src uv run python docs/manuel/captures/outils/demo_seed.py

# 2. rendu des captures dans docs/manuel/captures/
DJANGO_SETTINGS_MODULE=config.settings.dev PYTHONPATH=src \
  uv run python docs/manuel/captures/outils/render_captures.py
```

## Convertir en images

Sur une machine dotée d'un navigateur sans affichage :

```sh
for f in docs/manuel/captures/*.html; do
  chromium --headless --screenshot="${f%.html}.png" \
    --window-size=1280,1800 "$f"
done
```

## Inventaire

| Fichier | Écran | Acteur |
|---|---|---|
| `01-site-public-liste.html` | Liste publique des consultations | électeur |
| `02-site-public-scrutin.html` | Page publique d'un scrutin ouvert | électeur |
| `03-inscription-formulaire.html` | Formulaire d'inscription | électeur |
| `04-inscription-confirmee.html` | Accusé — courriel de confirmation envoyé | électeur |
| `05-inscription-en-examen.html` | Accusé — inscription mise en examen | électeur |
| `06-mairie-connexion.html` | Connexion à l'espace mairie | espace mairie |
| `07-bulletin-vote.html` | Bulletin — premier vote | électeur |
| `08-bulletin-modification.html` | Bulletin — modification | électeur |
| `09-bulletin-deja-enregistre.html` | Message « vote déjà enregistré » | électeur |
| `10-mairie-index-scrutins.html` | Liste des scrutins de l'espace mairie | espace mairie |
| `11-mairie-tableau-de-bord.html` | Tableau de bord d'un scrutin | espace mairie |
| `12-mairie-configuration-lecture.html` | Configuration en lecture seule (scrutin ouvert) | espace mairie |
| `13-mairie-configuration-brouillon.html` | Configuration modifiable (brouillon) | espace mairie |
| `14-mairie-file-inscriptions.html` | File d'attente des inscriptions | espace mairie |
| `15-mairie-import-liste.html` | Import de la liste électorale — étape 1 | espace mairie |
| `16-mairie-bulletin-papier.html` | Saisie d'un bulletin papier — recherche | espace mairie |
| `16a-mairie-bulletin-papier-recherche.html` | Résultats de recherche d'électeur | espace mairie |
| `16b-mairie-bulletins-papier-liste.html` | Liste des bulletins papier saisis | espace mairie |
| `16c-mairie-recu-papier.html` | Reçu de vote papier (imprimable) | espace mairie |
| `16d-mairie-bulletin-papier-collision.html` | Interstitiel « a déjà voté en ligne » (R-9.3) | espace mairie |
| `17-mairie-depouillement.html` | Clôture et publication | espace mairie |
| `18-mairie-comptes.html` | Comptes opérateurs | espace mairie |
| `19-mairie-roles.html` | Rôles par scrutin | espace mairie |
| `20-site-public-resultats.html` | Page publique de résultats | électeur |
| `21-mairie-journal-audit.html` | Journal d'audit | espace mairie |
