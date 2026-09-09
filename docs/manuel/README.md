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

Les images du manuel sont dans [`captures/img/`](captures/img/). Ce sont des
captures d'**écrans réels** de l'application, rendues à partir d'une instance de
démonstration alimentée par des **données synthétiques**. Le HTML source de
chaque écran est conservé à côté, dans [`captures/`](captures/), et sert à
régénérer les images.

Chaîne de production, entièrement reproductible (voir
[`captures/README.md`](captures/README.md)) :

1. `captures/outils/demo_seed.py` construit une base SQLite jetable — commune,
   comptes, rôles, liste électorale, inscriptions, bulletins, un scrutin ouvert,
   un brouillon, un scrutin publié ;
2. `captures/outils/render_captures.py` se connecte dans chaque rôle et écrit le
   HTML de chaque écran dans `captures/*.html`, feuille de style intégrée ;
3. un navigateur sans affichage transforme chaque HTML en PNG dans
   `captures/img/`.

Ces outils ne servent qu'à la documentation et n'ont aucun rôle en production.
Les noms (« Commune de Saint-Aubin-des-Bois », les électeurs, les adresses en
`@example.fr`) sont fictifs : aucun export réel de liste électorale ne figure
ici, conformément à R-13.6.
