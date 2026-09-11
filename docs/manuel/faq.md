<!-- SPDX-License-Identifier: 0BSD -->

# Foire aux questions

Trois sous-parties : [administrateur d'instance](#a-administrateur-dinstance),
[espace mairie](#b-espace-mairie), [électeur](#c-électeur).

---

## A. Administrateur d'instance

### Puis-je faire tourner plusieurs communes sur une même installation ?
Non. Une instance = une commune (R-1.3, R-1.5). Il n'y a pas de colonne
« locataire ». Une autre commune installe sa propre instance, avec sa propre
base et ses propres clés.

### Le playbook refuse de tourner sur ma distribution.
C'est voulu. La cible supportée est **Debian stable courante**, une seule
(§15). Pour un autre système, `contrib/init/` fournit des fichiers de service à
installer à la main, sans garantie de support.

### J'ai lancé un déploiement et tous les liens de modification de bulletin sont cassés.
`SECRET_KEY` a été régénéré. Il doit être généré **une seule fois** et jamais
réécrit ; le rôle Ansible le persiste sous `/etc/polls/secret_key` et le relit.
Restaurez ce fichier depuis une sauvegarde. Les liens signés **avant** le
changement de clé restent perdus.

### Puis-je appliquer une migration de schéma pendant qu'un scrutin est ouvert ?
Non, sauf raison mûrement pesée. Le rôle refuse (`assert`) tant que
`polls_open_poll_count > 0`, à moins de
`polls_allow_migrate_during_open_poll=true`. Planifiez les changements de schéma
**entre deux scrutins**.

### Un redéploiement va-t-il écraser la liste électorale figée ou le journal d'audit ?
Non. Ils vivent dans `/var/lib/polls/`, que le tag `deploy` ne touche jamais.
Seul `migrate` y écrit.

### Où est la clé qui protège l'anonymat du vote ?
`poll.token_salt` est **dans la base**, donc dans **chaque sauvegarde**. Le
répertoire de sauvegarde (`/var/backups/polls/`, y compris la copie hors site)
fait partie du périmètre du secret : il reste en `0700`, propriété du compte de
service. Ne l'élargissez jamais.

### Comment je teste que mes sauvegardes sont restaurables ?
`ansible-playbook -i inventory.ini restore.yml` : il provisionne un hôte,
restaure le snapshot le plus récent et rejoue le smoke play. Une sauvegarde
jamais restaurée n'est pas une sauvegarde (T-16). `restore.yml` vérifie
l'intégrité du snapshot **avant** de s'y fier et met l'ancienne base de côté en
`db.sqlite3.pre-restore-*`.

### Le déploiement s'arrête sur l'envoi d'un courriel de test.
Le smoke play exige qu'**un courriel parte réellement** vers
`polls_smoke_test_email` : chaque vote en ligne en dépend. Corrigez le relais
SMTP (identifiants dans `ansible-vault`), relancez `--tags deploy` puis le
smoke. On peut monter un hôte sans relais avec `polls_smoke_require_mail=false`,
à corriger avant d'ouvrir un scrutin.

### Une tâche planifiée « marche à la main » mais échoue en cron.
L'environnement de cron est quasi vide. Utilisez le wrapper
`/opt/polls/bin/polls-manage <tâche>`, qui source explicitement
`/etc/polls/polls.env`.

### `open_poll` n'a pas ouvert un scrutin à l'heure prévue.
Vérifiez que le planificateur tourne (`systemctl list-timers` ou
`/etc/cron.d/polls`) et l'intervalle (`polls_job_interval_minutes`, 5 min par
défaut). Les tâches sont pilotées par l'état : un hôte éteint rattrape au
passage suivant. Si le scrutin ne s'ouvre toujours pas, son tableau de bord
liste ce qui bloque (traduction manquante, liste non figée).

### Comment supervise-t-on l'instance ?
`GET /sante` renvoie `{"version", "migrations_pending"}` sans authentification
ni donnée personnelle. Alertez sur : `/sante` muet, `migrations_pending: true`
après déploiement, échec d'une tâche cron (`MAILTO` = `polls_admin_email`),
absence de snapshot depuis > 24 h, certificat TLS proche de l'expiration.

### Puis-je activer la journalisation complète des URL dans nginx ?
Non pour le préfixe `/bulletin/` : le jeton de vote y transite dans un lien et
ne doit jamais atteindre un log (R-7.4 ter). Le gabarit nginx supprime
délibérément la journalisation de l'URI pour ce préfixe.

### Ce logiciel convient-il à un budget participatif d'une grande ville ?
Probablement pas. Il est conçu pour le **niveau de risque 1** de la CNIL
(consultation à faible enjeu). Il n'est pas conçu pour les niveaux 2 ou 3. Le
DPO de la commune doit trancher avant tout scrutin qui ne serait pas clairement
de niveau 1 (voir le `README.md` racine).

### Où sont les données personnelles, et quand disparaissent-elles ?
Inscriptions, copie figée de la liste, association bulletin papier ↔ électeur :
dans la base, **supprimées deux mois après la clôture** par `retention_purge`,
qui efface aussi les champs « données personnelles » du journal d'audit **en
conservant** l'entrée, son auteur, sa date et son motif (R-12.4, R-13.3). Les
adresses IP de limitation de débit ne sont pas conservées au-delà du nécessaire.

---

## B. Espace mairie

### Je suis administrateur de la commune : pourquoi n'ai-je pas accès aux écrans d'un scrutin ?
Parce que `commune_admin` est un rôle **de niveau commune**, pas un
super-utilisateur. Il crée les scrutins et attribue les rôles ; il ne donne
accès à aucun bulletin. Attribuez-vous le rôle voulu sur le scrutin — cela écrit
un événement d'audit, ce qui est le but : chaque accès aux écrans sensibles doit
découler d'une attribution tracée.

### Comment démarre-t-on une instance neuve, sans `createsuperuser` ?
Par l'assistant de **première installation** (`/mairie/installation/`), qui crée
la fiche commune (dont le référent données personnelles) et le premier compte
administrateur. Il se ferme dès qu'un compte existe.

### Je me suis trompé dans la configuration et le scrutin est déjà ouvert.
La configuration se fige à l'ouverture (R-3.3, INV-6), et c'est un déclencheur
de base qui le tient. **Seule** la **date de clôture** peut être reportée
(action séparée, motif obligatoire, affichée publiquement). Pour le reste, il
faut un nouveau scrutin. Aucune transition n'est réversible.

### Peut-on revenir de « clos » à « ouvert » ?
Non. `brouillon → [annoncé] → ouvert → clos → publié`, sans retour (R-3.2).
« Annoncé » est une étape facultative : un scrutin peut aussi passer directement
de brouillon à ouvert.

### Peut-on ouvrir ou clore un scrutin sans attendre la tâche planifiée ?
Oui, depuis l'écran de configuration (écran 2) : *Annoncer maintenant*, *Ouvrir
maintenant* et *Clôturer maintenant* (R-2.1). *Ouvrir maintenant* est permis à
tout moment, y compris par avance — cela ne fait voter personne avant l'heure
configurée. *Clôturer maintenant* n'apparaît qu'une fois l'échéance de saisie
des bulletins papier atteinte.

### À quoi sert l'état « annoncé » ?
À rendre un scrutin visible sur le site public — propositions et calendrier —
avant son ouverture, sans inscription ni vote possibles (R-3.10). Utile
notamment si le scrutin n'autorisera pas la modification d'un bulletin déjà
voté : les électeurs peuvent réfléchir aux propositions avant de voter. La
configuration se fige au moment de l'annonce, comme elle l'aurait fait à
l'ouverture.

### L'import de la liste électorale signale des doublons et des dates douteuses. Dois-je corriger le fichier ?
Non. Le rapport **informe, il ne bloque pas**. Seuls une colonne obligatoire non
mappée ou une ligne sans aucun nom interrompent l'import. Les dates non
analysables (marquées « incertaines »), les lignes incomplètes et les doublons
sont **importés** : ce sont des faits sur la liste, pas des défauts du fichier.
Les cas douteux arrivent ensuite dans la file d'attente des inscriptions.

### Un nouvel import va-t-il changer un scrutin déjà ouvert ?
Non. L'import remplace la **liste de travail** ; un scrutin ouvert travaille sur
sa **copie figée** prise à l'ouverture.

### Peut-on consulter le détail de la liste électorale, pas seulement son statut ?
Oui, sur les deux écrans : le menu général « Liste électorale » (commune)
montre la liste de travail en vigueur, paginée et cherchable ; le menu
« Liste électorale » d'un scrutin déjà ouvert montre sa **propre copie figée**
(R-4.4), accessible à l'administrateur du scrutin et à l'auditeur.

### La liste de travail importée est-elle conservée indéfiniment si personne ne l'utilise ?
Non. Une liste importée mais qu'aucun scrutin encore en brouillon (ou annoncé)
ne consomme plus est supprimée deux mois après son import (R-13.3 bis) —
distinct de la rétention de la copie figée d'un scrutin, qui part de sa
clôture (R-13.3).

### Un électeur dit être inscrit mais le rapprochement échoue.
Sa demande part en **file d'attente des inscriptions**. Comparez la déclaration
aux entrées proches ; **acceptez** (en choisissant l'entrée de liste) ou
**refusez**, avec un motif. Une inscription acceptée passe en attente de
confirmation d'adresse, jamais directement à l'état actif.

### Un couple partage une seule adresse électronique.
Une adresse ne sert qu'une fois par scrutin (R-5.10). L'un des deux vote **sur
papier à la mairie**. Aucune normalisation d'alias n'est faite : toute règle sur
les points ou suffixes fusionnerait des personnes distinctes ou donnerait une
fausse assurance.

### Un électeur a voté en ligne et veut maintenant un bulletin papier.
Refusé (R-9.3). Le bulletin en ligne est anonyme et introuvable depuis
l'inscription : il ne peut être ni remplacé, ni supprimé. Si le scrutin autorise
la modification, l'électeur modifie **lui-même** son bulletin en ligne ; sinon,
le vote en ligne est définitif.

### Un électeur a un bulletin papier et veut voter en ligne.
Il doit se présenter en mairie pour faire **supprimer** le bulletin papier
d'abord. La suppression (motif obligatoire, avant/après tracé) efface
l'indicateur de canal et rouvre le vote en ligne (R-9.4).

### Différence entre « corriger » et « modifier » un bulletin papier ?
La **correction** répare une erreur de saisie de l'opérateur ; elle reste
possible même si le scrutin n'autorise pas les électeurs à modifier leur vote.
Ce n'est pas le même acte qu'un électeur qui change d'avis. Motif obligatoire,
avant/après au journal (R-8.5).

### La clôture est refusée : « n bulletins en attente de contreseing ».
Soit vous obtenez les contreseings (écran 7), soit l'administrateur du scrutin
**passe outre avec un motif obligatoire**, qui est enregistré et **apparaît dans
la publication**. Les bulletins non contresignés ne sont pas comptés ; on
n'abandonne pas de bulletins en silence (R-8.7 bis).

### Puis-je afficher la participation en direct ?
Seulement si la configuration du scrutin le prévoit (désactivé par défaut) :
publier la participation en cours de vote peut l'influencer. Quand c'est
désactivé, **aucune** page, API ou en-tête n'expose de compteur.

### Qui peut voir le journal d'audit ? Peut-on y corriger une erreur ?
Les **auditeurs** y ont accès en lecture seule, ainsi que les administrateurs du
scrutin. **Aucun** événement ne peut être modifié ni supprimé (INV-3), y compris
par un administrateur. Une précision se met sur la ligne référencée (inscription,
lien de bulletin papier), pas sur l'événement, dont le motif est un code.

### Un scrutin « test » apparaîtra-t-il dans les résultats publics ?
Non. L'indicateur est fixé à la création, non modifiable ; le scrutin est exclu
des listes publiques, des résultats et de toute statistique (R-3.7).

### Pourquoi ne puis-je pas changer l'identifiant d'une proposition ?
Parce que les bulletins et le résultat publié le portent ; le dépouillement et
l'empreinte reposent sur les identifiants, pas sur les libellés (R-10.7). Les
libellés, eux, se corrigent librement — mais uniquement tant que le scrutin est
en brouillon.

---

## C. Électeur

### Mon vote est-il vraiment secret ?
Un bulletin voté **en ligne** n'est relié à votre identité par aucune donnée de
la base : la plateforme sait que vous avez voté, jamais comment (R-7.4). Un
bulletin **papier** reste, lui, associé à votre identité (pour la traçabilité et
une suppression à votre demande), jusqu'à son effacement deux mois après la
clôture.

### Est-ce une élection ? Le résultat s'impose-t-il au conseil ?
Non. C'est une **consultation** : le résultat éclaire la décision du conseil
municipal sans la lier. Ce n'est pas une élection à valeur légale (pas
d'authentification forte de l'électeur, pas de cryptographie de bout en bout).

### Je n'ai pas reçu le courriel de confirmation.
Vérifiez les indésirables. L'adresse doit être **exactement** celle saisie.
Sans confirmation, aucun bulletin n'existe et vous ne pouvez pas voter. En cas
de blocage, adressez-vous à la mairie ; vous pouvez aussi voter **sur papier**.

### J'ai perdu le lien reçu par courriel.
Si vous **n'avez pas encore voté**, adressez-vous à la mairie. Si vous **avez
déjà voté** : votre bulletin **reste enregistré et compté**, mais vous ne
pourrez plus le modifier. Personne — pas même la mairie — ne peut retrouver ce
lien ni vous en renvoyer un autre.

### Puis-je m'inscrire avec mon nom de naissance ou mon nom d'usage ?
Les deux sont acceptés. La date de naissance porte l'essentiel de la
vérification.

### Pourquoi les propositions ne sont-elles pas dans le même ordre que sur la page publique ?
L'ordre du bulletin est **tiré au hasard pour chaque électeur** (R-6.2), pour
ne pas favoriser une proposition par sa position.

### Puis-je changer mon vote après l'avoir déposé ?
Seulement si le scrutin l'autorise — la page du bulletin vous le dit **avant**
la validation. Si oui, rouvrez le lien de votre inscription autant de fois que
voulu jusqu'à la clôture ; chaque version remplace la précédente, votre code de
suivi ne change pas, aucun nouveau courriel n'est envoyé.

### À quoi sert le code de suivi ? Quand est-ce que je le reçois ?
Il vous est donné **au moment du vote** (à l'écran et par courriel), pas à
l'inscription. Après la clôture, il vous permet de **retrouver votre bulletin
dans la liste publiée** et de vérifier votre classement, **sans révéler votre
identité**.

### Avec mon code de suivi, quelqu'un peut-il savoir comment j'ai voté ?
Vous-même pouvez retrouver votre ligne dans le fichier publié — et donc, si vous
communiquez votre code, prouver à un tiers comment vous avez voté. C'est le
revers de la vérifiabilité par publication. Pour cette raison, cette plateforme
ne doit pas être utilisée là où la contrainte ou l'achat de voix sont un risque
réel.

### J'ai reçu un rappel alors que j'ai déjà voté.
Le rappel est envoyé 48 h avant la clôture aux inscrits dont **aucun bulletin
n'est enregistré**. Si vous venez de voter, les deux ont pu se croiser ; votre
vote est bien pris en compte. Vous pouvez le vérifier après la clôture avec
votre code de suivi.

### On m'a répondu que je ne suis pas éligible à cette consultation.
Une seule entrée de la liste correspond à votre déclaration, mais son **type de
liste** ne donne pas voix sur **ce** scrutin (par exemple, être inscrit sur la
seule liste complémentaire européenne pour une question municipale — R-4.7). En
cas de doute sur votre inscription, adressez-vous à la mairie.

### Puis-je voter à la fois en ligne et sur papier ?
Non. Un seul canal par électeur. Si un bulletin papier a été saisi pour vous, le
vote en ligne est refusé (et inversement) tant que le premier n'a pas été
supprimé en mairie.

### L'interface est-elle utilisable au téléphone et avec un lecteur d'écran ?
Oui. L'interface est conforme au RGAA et utilisable au téléphone. Le classement
des propositions dispose toujours d'une alternative au glisser-déposer (listes
déroulantes numérotées), utilisable au clavier et au lecteur d'écran.
