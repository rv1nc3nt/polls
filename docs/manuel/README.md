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
| n'importe qui, électeur ou non, souhaitant recalculer un résultat publié par ses propres moyens | **[Vérifier un résultat par vous-même](verifier.md)** — télécharger et utiliser le vérificateur indépendant, sans compétence technique préalable |
| n'importe qui voulant comprendre *comment* un résultat est obtenu, au-delà du simple « qui gagne » | **[Les méthodes de dépouillement, expliquées](methodes-de-depouillement.md)** — Schulze, majoritaire, par assentiment et départage, en clair puis avec le code source qui les calcule |
| n'importe lequel des rôles ci-dessus, avec une question précise | **[Foire aux questions](faq.md)** — une sous-partie par rôle |

## Servi par l'application elle-même

`guide-electeur.md`, `verifier.md`, `methodes-de-depouillement.md` et la
sous-partie « Électeur » de `faq.md` sont servis sur le site public, sous
`/aide/` ; `guide-espace-mairie.md` et la sous-partie « Espace mairie » de
`faq.md` sont servis dans l'espace mairie, sous `/mairie/aide/`, ouvert à
tout compte opérateur connecté, quel que soit son rôle
(`apps.backoffice.access.require_operator`) — lire la documentation n'est pas
en soi un accès aux données d'un scrutin ; ce dernier renvoie vers
`methodes-de-depouillement.md` plutôt que de le dupliquer, puisque ce
document n'a rien de spécifique à l'espace mairie. Tous le sont par
`apps.core.manual`, qui lit et rend ces fichiers depuis le disque à chaque
requête : le fichier source **est** la page servie, il n'existe jamais de
copie à tenir à jour à la main. `guide-administrateur.md` et la sous-partie
« Administrateur d'instance » de `faq.md` ne sont servis nulle part : ce
public n'a par construction pas encore de compte espace mairie, et il lit ce
guide dans le dépôt.

Chacun des cinq documents servis existe aussi en anglais, dans un fichier
jumeau suffixé `-en` (`guide-electeur-en.md`, etc.) — même convention que
`requirements-en.md` à côté de `cahier-des-charges.md` à la racine du dépôt.
Le français reste la seule langue de référence (ci-dessus) : la version
anglaise est une traduction, à corriger pour suivre le français plutôt que
l'inverse. La langue servie suit celle de la page (le sélecteur de langue
déjà présent sur le site), pas un réglage séparé.

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
ici.
