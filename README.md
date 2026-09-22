<!-- SPDX-License-Identifier: 0BSD -->

[English version](README-en.md)

# Plateforme de consultation citoyenne

Posez une question à vos administrés, laissez-les répondre en ligne ou sur
papier, et publiez un résultat que n'importe qui — un administré, un
journaliste local, un·e élu·e d'opposition — peut recalculer par ses propres
moyens plutôt que de croire la mairie sur parole. C'est à cela que sert ce
logiciel.

Application web auto-hébergée permettant à une commune française d'organiser
des scrutins **consultatifs** auprès de ses électeurs inscrits : budget
participatif, choix d'un nom de rue, consultation d'urbanisme, enquête de
satisfaction. Les bulletins sont exprimés en ligne, ou sur papier et saisis
par un membre du conseil municipal. Les scrutins à préférences sont
dépouillés par la méthode Schulze ; les scrutins à choix unique et par
assentiment sont également pris en charge.

Une instance par commune. L'adoption par une autre commune signifie une
nouvelle instance, jamais une colonne de locataire, et jamais un tiers
détenant les données de vos électeurs.

Écrit à partir de [`spec-plateforme-vote.md`](spec-plateforme-vote.md), qui
restitue les exigences fonctionnelles — les numéros `R-x.y` cités tout du
long — en termes d'implémentation. Les écarts du code par rapport à la
spécification sont consignés dans
[`docs/specification-decision-log.md`](docs/specification-decision-log.md).

## Pourquoi une commune choisirait ce logiciel

- **Gratuit, et à vous.** Licence 0BSD — pas d'abonnement, pas de coût par
  scrutin, pas de prestataire. La commune héberge sa propre instance et garde
  ses propres données ; voir [Licence](#licence) plus bas.
- **Personne ne peut voir comment un administré a voté — pas même la
  mairie.** Une inscription prouve qui a le droit de voter ; un bulletin est
  anonyme dès l'instant où il est exprimé. Les deux ne sont jamais reliés, ni
  dans l'application ni dans la base de données (`INV-1`, imposé par un
  déclencheur de base de données, pas seulement par le code applicatif).
- **Le dépouillement est public, pas seulement annoncé.** La clôture d'un
  scrutin publie les bulletins anonymisés et une empreinte du résultat.
  N'importe qui peut télécharger le [vérificateur](docs/manuel/verifier.md)
  gratuit et recalculer le résultat par lui-même, sans compte et sans avoir à
  faire confiance au logiciel qui l'a produit.
- **Adapté à la réalité d'un scrutin.** La plupart des communes comptent des
  administrés qui ne peuvent pas, ou ne veulent pas, voter en ligne — un
  bulletin papier, saisi et contresigné par un membre du conseil municipal,
  accompagne le canal en ligne plutôt que d'être traité en marge.
- **Une traçabilité qui ne peut pas être discrètement modifiée.** Chaque
  action significative — une décision d'inscription, une correction de
  bulletin, l'attribution d'un rôle — est consignée dans un journal d'audit
  sans possibilité de modification ni de suppression : ce qui s'est
  effectivement passé n'est jamais que la parole de quelqu'un.
- **En français, pour les règles d'une commune française.** L'interface, le
  rapprochement avec la liste électorale et les mises en garde légales
  ci-dessous s'appuient sur `cahier-des-charges.md` et sur les référentiels
  CNIL et ANSSI auxquels un DPO français doit déjà répondre — ce n'est pas la
  traduction d'un produit générique conçu ailleurs.

Parcourez les [captures d'écran](#captures-décran) ci-dessous, puis lisez
[**Ce à quoi ce logiciel n'est pas destiné**](#ce-à-quoi-ce-logiciel-nest-pas-destiné)
avant d'y engager un budget — il est délibérément restrictif sur ce qu'il ne
couvre pas.

## Fonctionnalités principales

- **Import de la liste électorale et inscriptions** (§6.1–6.2) — la commune
  importe sa liste de travail sous forme de CSV ; les administrés s'inscrivent
  en ligne et sont rapprochés de la liste par nom et adresse, tout cas
  ambigu étant envoyé en examen manuel plutôt que deviné.
- **Vote, en ligne et sur papier** (§6.3–6.4) — les électeurs expriment ou
  modifient un bulletin en ligne jusqu'à la clôture ; un membre du conseil
  municipal peut saisir un bulletin papier à la place, avec détection
  automatique si cet électeur a déjà voté en ligne.
- **Trois méthodes de dépouillement** (§8) — choix unique, assentiment, et
  Schulze (Condorcet) pour le vote par préférences classées, avec la matrice
  de préférences deux à deux et le raisonnement du départage affichés à côté
  du résultat, pas seulement le vainqueur.
- **Une publication que chacun peut recalculer** (§9) — la clôture produit une
  empreinte de clôture, un CSV anonymisé des bulletins et un document JSON ;
  un vérificateur Rust indépendant (`verifier/`), ne partageant aucun code
  avec le dépouillement Python, recalcule le même résultat à partir des seuls
  fichiers publiés.
- **Espace mairie** (§6.5) — quatorze écrans d'administration (tableau de
  bord, configuration, liste électorale, file des inscriptions, bulletins
  papier, clôture et publication, comptes opérateurs, rôles par scrutin,
  journal d'audit, paramètres de la commune), chacun accessible uniquement
  via une habilitation auditée propre au scrutin — jamais un indicateur de
  superutilisateur.
- **Journal d'audit strictement additif** (§10) — chaque action significative
  est consignée par référence, sans donnée identifiante et sans possibilité
  de modification ni de suppression, dans l'application comme dans la base de
  données.

## Captures d'écran

<p align="center">
  <img src="docs/manuel/captures/img/02a-site-public-scrutin.png" width="49%" alt="Page publique d'un scrutin ouvert, montrant les trois propositions soumises et un bouton Participer">
  <img src="docs/manuel/captures/img/07-bulletin-vote.png" width="49%" alt="Bulletin en ligne classant trois propositions par préférence">
</p>
<p align="center">
  <img src="docs/manuel/captures/img/11-mairie-tableau-de-bord.png" width="49%" alt="Tableau de bord de l'espace mairie pour un scrutin, montrant la participation et les actions en attente">
  <img src="docs/manuel/captures/img/20-site-public-resultats.png" width="49%" alt="Page publique de résultats avec la matrice de préférences Schulze et les empreintes de clôture">
</p>

De gauche à droite, de haut en bas : la page publique d'un scrutin ouvert, le
bulletin en ligne d'un électeur, le tableau de bord de l'espace mairie pour ce
scrutin, et la page publique de résultats avec le raisonnement Schulze et
l'empreinte de clôture que chacun peut vérifier. D'autres écrans — le parcours
d'inscription, la saisie des bulletins papier, l'import de la liste
électorale, les rôles et le journal d'audit — sont capturés pour chaque rôle
dans [`docs/manuel/`](docs/manuel/captures/README.md), qui explique aussi
comment les régénérer à partir d'une base de démonstration jetable.

## Ce à quoi ce logiciel n'est pas destiné

**Pas des élections légalement contraignantes.** Pas d'authentification forte
de l'électeur, pas de cryptographie vérifiable de bout en bout. Le modèle de
vérifiabilité repose sur la publication : l'ensemble des bulletins anonymisés
est publié, et chacun peut recalculer le résultat et l'empreinte de clôture à
partir de lui.

**L'absence de reçu n'est pas garantie, et ce n'est pas l'objectif.** Un
électeur qui conserve son code de suivi peut retrouver sa propre ligne dans le
CSV publié et ainsi prouver à un tiers comment il a voté. Cela découle
directement de la vérifiabilité par publication — la propriété qui permet à
quiconque de recalculer le résultat est la même qui rend un bulletin
retrouvable par qui détient son code. C'est accepté parce que le scrutin est
consultatif, et cela signifie que ce logiciel **ne doit pas être utilisé là où
la coercition ou l'achat de voix constituent un risque réaliste**.

## Niveau de risque réglementaire, à l'attention d'un DPO

La recommandation de la CNIL relative à la sécurité du vote électronique est
la **délibération n° 2026-045 du 19 mars 2026** (publiée le 24 avril 2026),
qui abroge les textes de 2010 et 2019, accompagnée du guide technique ANSSI
**ANSSI-PA-118** ; les deux textes sont conçus pour être lus ensemble.

**Ce logiciel est conçu pour répondre au niveau de risque 1** — un scrutin
consultatif à faibles enjeux, du type probablement hors du périmètre d'un
texte visant les élections à scrutin secret. **Il n'est pas conçu pour les
niveaux 2 ou 3**, où un budget participatif dans une ville de cinquante mille
habitants peut fort bien se situer. Le DPO d'une commune candidate à
l'adoption devrait pouvoir répondre à cette question à la seule lecture de
cette section, sans avoir à lire le code source ; si le scrutin envisagé ne
relève pas clairement du niveau 1, ce n'est pas le bon logiciel pour ce
scrutin.

Les scrutins déjà en préparation pour 2026 peuvent se poursuivre sous la
version de 2019 ; tout nouveau scrutin relève du nouveau texte.

## Documentation

[`docs/manuel/`](docs/manuel/README.md) est rédigé pour les personnes qui
utiliseront réellement le logiciel, pas pour des développeurs — il ne suppose
jamais que vous ayez lu la spécification, et il est servi par l'application
elle-même, si bien qu'il ne peut jamais devenir obsolète :

| Vous êtes… | Lisez… |
|---|---|
| le responsable informatique qui installe et exploite une instance pour la commune | [Guide de l'administrateur d'instance](docs/manuel/guide-administrateur.md) |
| un·e élu·e ou un·e agent·e travaillant dans l'espace mairie | [Guide de l'espace mairie](docs/manuel/guide-espace-mairie.md) |
| un électeur invité à une consultation | [Guide de l'électeur](docs/manuel/guide-electeur.md) |
| quiconque veut vérifier un résultat publié par ses propres moyens | [Vérifier un résultat par vous-même](docs/manuel/verifier.md) |
| quiconque veut comprendre comment un résultat est obtenu | [Les méthodes de dépouillement, expliquées](docs/manuel/methodes-de-depouillement.md) |
| n'importe lequel des rôles ci-dessus, avec une question précise | [Foire aux questions](docs/manuel/faq.md) |

## Installation

`ansible/` est la voie prise en charge : d'une VM Debian vierge à une instance
en fonctionnement, en modifiant un seul fichier d'inventaire et en exécutant
une seule commande — voir [`ansible/README.md`](ansible/README.md) et le
[guide de l'administrateur d'instance](docs/manuel/guide-administrateur.md)
complet pour l'installation, le déploiement, la sauvegarde, la restauration et
la supervision. Une image de conteneur est l'alternative, pas encore
construite (voir État du build plus bas). `contrib/init/` fournit des fichiers
de service pour systemd, OpenRC, FreeBSD et OpenBSD — **Debian est installé et
testé en intégration continue via le playbook ; les autres plateformes sont du
meilleur effort, installation à la main.**

## Démarrage rapide (développement)

Pour travailler sur le code lui-même, pas pour organiser un scrutin :

    uv sync
    mkdir -p var/locks var/media var/static
    uv run python manage.py migrate
    uv run python manage.py runserver

Tests, lint et typage :

    uv run pytest -q
    uv run ruff check .
    uv run mypy src tests
    cargo test --manifest-path verifier/Cargo.toml

## Arborescence

    src/config/            Projet Django : réglages, URLs, WSGI
    src/apps/core/         Types, cryptographie (§7), sérialisation
                           canonique (§9), rapprochement de noms (§6.2),
                           codes de suivi, verrouillage des tâches
    src/apps/elections/    Scrutin, options, instantané de la liste
                           électorale, la fonction de transition unique
                           (§5.1), la fenêtre de vote (INV-2), la clôture
                           et la publication (§9), la conservation (§11)
    src/apps/registrations/ Inscriptions et examen — aucun lien avec les
                           bulletins
    src/apps/ballots/      Bulletin et PaperBallotLink — aucun lien avec
                           les électeurs
    src/apps/audit/        Journal d'audit additif, par référence (§10)
    src/apps/tally/        Fonctions de dépouillement pures (§8) ;
                           n'importe aucun modèle
    src/apps/backoffice/   Espace mairie (§6.5) — la majeure partie du build
    src/apps/publicsite/   Pages publiques (§6.6) et GET /sante
    verifier/              Vérificateur Rust indépendant ; ne partage aucun
                           code (§14) — core/ la logique de vérification,
                           cli/ et gui/ deux interfaces
    ansible/               Déploiement (§15)
    docs/                  Sérialisation canonique, écarts avec la
                           spécification, manuel/ (manuel utilisateur
                           français, les quatre rôles)

## Propriétés à ne jamais rompre

Lire les §5, §7 et §10 de la spécification avant de toucher au domaine, et
[`CONTRIBUTING.md`](CONTRIBUTING.md) avant d'ouvrir une pull request. En
bref : aucune requête ne doit relier une inscription à un bulletin en ligne ;
le statut de vote vit sur `Registration.channel` ; le journal d'audit ne
contient que des références et un état non identifiant, sans possibilité de
modification ni de suppression ; l'empreinte de clôture ne dépend que des
identifiants d'options et des codes de suivi.

## État du build

Implémenté et testé — les jauges d'intégration continue (`compilemessages`,
`makemigrations --check`, `ruff`, `ruff format`, `mypy --strict`, `pytest`)
et les `cargo test` Rust sont au vert :

- le modèle de domaine et ses migrations, et les déclencheurs de base de
  données imposant INV-2, INV-3, INV-6 et INV-7 ;
- la fonction de transition et ses gardes, la fenêtre de vote, la clôture,
  l'empreinte de clôture et les artefacts de publication, le dépouillement,
  le départage, la conservation ;
- le schéma d'anonymat (§7), le rapprochement de noms et d'adresses ;
- l'import de la liste électorale (§6.1), le parcours d'inscription et
  d'examen (§6.2), le vote en ligne et sa modification (§6.3), la saisie, la
  correction, la suppression et le contreseing des bulletins papier (§6.4) ;
- les quatorze écrans d'administration (§6.5), les pages publiques de scrutin
  et de résultats et `GET /sante` (§6.6) ;
- les commandes d'administration, avec le verrouillage et la sélection par
  état que le §14 impose, et les modèles de courriel qu'elles envoient ;
- le catalogue de messages `en` (le français étant la langue des msgid) ;
- le vérificateur Rust indépendant et son recoupement avec le dépouillement
  Python ;
- le rôle Ansible — `provision`, `deploy`, `backup`, `restore`, `smoke`
  (§15).

Chaque test d'acceptation T-1…T-81 (§12) dispose d'un test ou d'un scénario
Molecule.

Reste à faire :

- **T-16 et T-38** ne s'exécutent que dans le job d'intégration continue
  dédié `molecule` — ils ont besoin d'un hôte systemd jetable, pas de la base
  de données pytest — et le passage manuel **T-13** au lecteur d'écran reste
  une étape manuelle avant chaque ouverture de scrutin (la moitié
  clavier-seul est automatisée).
- Pas encore d'**image de conteneur** prête à l'emploi ni de guide de
  déploiement sans outillage, et pas de **mention des licences tierces**
  générée (§14).
- L'**audit de conformité RGAA** du balisage (R-14.1) et un **test de
  délivrabilité** des courriels vers de vraies boîtes (§14) restent des
  tâches d'avant lancement, pas du code.
- Les éléments du §13 — libellés des options du premier scrutin, langues
  activées, instants d'ouverture et de clôture, référent protection des
  données, bascules du parcours papier, fenêtre de saisie, inscription
  postale, `review_all_registrations` — sont câblés comme configuration et
  attendent les valeurs de la commune.

## Licence

[0BSD](LICENSE), documentation et spécifications comprises. Voir
[`PROVENANCE.md`](PROVENANCE.md) pour la manière dont le code a été produit.
