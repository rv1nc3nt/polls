<!-- SPDX-License-Identifier: 0BSD -->

# Manuel de la plateforme de consultation citoyenne

Ce manuel accompagne le logiciel décrit par les [exigences
fonctionnelles](../../cahier-des-charges.md) (règles `R-x.y`) et la
[spécification](../../spec-plateforme-vote.md) (sections `§n`). Il est rédigé en
français ; c'est la seule langue de référence.

Il se lit selon le rôle que l'on tient :

| Vous êtes… | Lisez… |
|---|---|
| responsable informatique qui installe et exploite une instance pour la commune | **[Guide de l'administrateur d'instance](guide-administrateur.md)** — installation, déploiement, planificateur, sauvegarde, restauration, supervision, mises à jour, obligations RGPD techniques |
| élu·e ou agent·e travaillant dans l'espace mairie | **[Guide de l'espace mairie](guide-espace-mairie.md)** — rôles, création et configuration d'un scrutin, import de la liste électorale, file des inscriptions, bulletins papier, contreseing, clôture, publication, journal d'audit |
| électeur ou électrice invité·e à une consultation | **[Guide de l'électeur](guide-electeur.md)** — s'inscrire, confirmer son adresse, voter, modifier son vote, vérifier l'enregistrement, voter sur papier |
| n'importe lequel des trois, avec une question précise | **[Foire aux questions](faq.md)** — une sous-partie par rôle |

## À propos des captures d'écran

Les figures de ce manuel renvoient au dossier [`captures/`](captures/). Faute
de navigateur graphique sur la machine où le manuel a été rédigé, ce sont des
**captures HTML** : le balisage réel de chaque écran, produit à partir d'une
instance de démonstration alimentée par des données synthétiques, avec la
feuille de style intégrée. Chaque fichier s'ouvre seul dans un navigateur et se
convertit en image en une commande :

```sh
chromium --headless --screenshot=11.png --window-size=1280,1600 \
  docs/manuel/captures/11-mairie-tableau-de-bord.html
```

Le jeu de données et le script de génération sont dans
[`captures/outils/`](captures/outils/) ; ils ne servent qu'à la documentation et
n'ont aucun rôle en production. Les noms (« Commune de Saint-Aubin-des-Bois »,
les électeurs, les adresses en `@example.fr`) sont fictifs : aucun export réel
de liste électorale ne figure ici, conformément à R-13.6.
