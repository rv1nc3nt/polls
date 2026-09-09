<!-- SPDX-License-Identifier: 0BSD -->

# Guide de l'administrateur d'instance

Ce guide s'adresse à la personne qui installe la plateforme sur un serveur et
la maintient en état de marche. Il ne traite pas de l'usage métier (création de
scrutins, dépouillement) : voir le [guide de l'espace mairie](guide-espace-mairie.md).

> **Une instance = une commune.** Le logiciel n'a pas de notion de multi-commune.
> Si une autre commune l'adopte, elle installe sa propre instance, avec sa
> propre base et ses propres clés (R-1.3, R-1.5).

## 1. Ce que fait le logiciel, du point de vue de l'exploitation

- Application **Django 5.2 LTS**, **Python 3.13**, base **SQLite** en mode WAL.
- Un processus web **gunicorn** derrière **nginx** (terminaison TLS, en-têtes de
  sécurité, limitation de débit).
- Quatre **tâches planifiées** courtes et idempotentes : `open_poll`,
  `close_poll`, `send_reminders`, `retention_purge`.
- Un **vérificateur Rust indépendant** (`verifier/`), hors instance, qui
  recalcule un résultat publié à partir du seul CSV. Il ne se déploie pas sur le
  serveur.
- Pas d'admin Django, dans aucun environnement (§14). L'unique zone
  authentifiée est l'espace mairie, sous `/mairie/`.

### Frontières de confidentialité à connaître avant toute chose

| Donnée | Où elle vit | Conséquence pour l'exploitation |
|---|---|---|
| `poll.token_salt` (sel des jetons de vote, §7) | dans la base, donc dans **toute sauvegarde** | le répertoire de sauvegarde fait partie du périmètre du secret du vote : il reste en `0700`, propriété du compte de service, y compris hors site. |
| `SECRET_KEY` | fichier `0600` sous `/etc/polls/`, généré **une seule fois** | le régénérer invalide toutes les sessions et tous les liens signés, **y compris les liens de modification de bulletin d'un scrutin en cours** (§15). |
| Données d'identité (inscriptions, liste électorale figée, lien bulletin papier ↔ électeur) | dans la base | supprimées automatiquement **deux mois après la clôture** du scrutin par `retention_purge` (R-13.3). |
| Adresses IP (limitation de débit) | cache applicatif (table `polls_cache`) | non conservées au-delà du strict nécessaire (R-13.5). |
| Journal d'audit | dans la base, **sans chemin de modification ni de suppression** (INV-3) | doit survivre à un redéploiement et à une restauration : c'est le test T-16. |

## 2. Cible supportée

**Debian stable courante, une seule distribution.** Le playbook Ansible vérifie
le système et échoue tôt s'il tourne ailleurs. C'est délibéré : un playbook qui
prétend gérer quatre distributions sans en tester aucune est pire qu'un playbook
qui refuse de démarrer sur le reste (§15).

Pour les autres systèmes (systemd hors Debian, OpenRC, FreeBSD, OpenBSD),
`contrib/init/` fournit des fichiers de service. **Deux niveaux de support,
sans ambiguïté :** Debian est installée par le playbook et testée en CI ; le
reste, ce sont des fichiers de service fournis, installation à la main, au
mieux. Sur une cible musl (Alpine), `argon2-cffi` peut devoir être compilé
depuis les sources si aucune roue `musllinux` n'est publiée pour le Python
installé.

## 3. Installation par Ansible (voie recommandée)

Objectif : d'une VM Debian nue à une instance en service, en éditant **un seul
fichier d'inventaire** et en lançant **une seule commande**.

### 3.1 Préparer le poste de contrôle

```sh
git clone <dépôt> polls && cd polls
git checkout <tag>          # jamais une branche de travail : §15 veut un artefact taggé
python3 -m pip install --user ansible
cd ansible
cp inventory.example.ini inventory.ini
```

### 3.2 Renseigner l'inventaire

`inventory.ini` (extrait de `inventory.example.ini`) :

```ini
[polls]
vote.exemple-commune.fr

[polls:vars]
polls_domain=vote.exemple-commune.fr
polls_admin_email=mairie@exemple-commune.fr
polls_smoke_test_email=informatique@exemple-commune.fr
polls_scheduler=cron
```

### 3.3 Les secrets : `ansible-vault`, jamais le dépôt

Les identifiants SMTP et toute autre valeur sensible passent par
`ansible-vault`. Le dépôt n'en contient aucun. Variables concernées :
`polls_email_host`, `polls_email_port`, `polls_email_user`,
`polls_email_password`, `polls_from_email`.

```sh
ansible-vault create group_vars/polls/vault.yml
# y placer polls_email_user, polls_email_password, …
```

### 3.4 Lancer

```sh
# run complet : provisionnement + déploiement + sauvegarde + smoke
ansible-playbook -i inventory.ini site.yml --ask-vault-pass

# ou par étapes, grâce aux tags
ansible-playbook -i inventory.ini site.yml --tags provision
ansible-playbook -i inventory.ini site.yml --tags deploy
ansible-playbook -i inventory.ini site.yml --tags backup
```

Tout est idempotent et propre en `--check`. Un second passage ne change rien.

### 3.5 Ce que le playbook met en place

1. **Système** : paquets de base, locale `fr_FR.UTF-8`, fuseau `Europe/Paris`,
   mises à jour de sécurité automatiques, pare-feu nftables n'ouvrant que 22, 80
   et 443.
2. **Compte de service** non privilégié (`polls`), arborescence dont rien n'est
   lisible par tout le monde :
   - code applicatif sous `/opt/polls/` (releases versionnées + lien
     symbolique `current`) ;
   - base et verrous de tâches sous `/var/lib/polls/` — **jamais touché par le
     tag `deploy`** ;
   - sauvegardes sous `/var/backups/polls/` en `0700` ;
   - configuration sous `/etc/polls/` (`polls.env` en `0600`, `secret_key` en
     `0600`).
3. **Release** depuis un artefact taggé (dépôt distant via `polls_repo_url`, ou
   archive de l'arbre local), dans un répertoire versionné ; le retour arrière
   est un changement de lien symbolique.
4. **Virtualenv** depuis `uv.lock` (`uv sync --frozen`), puis `migrate`,
   `createcachetable`, `collectstatic`, `compilemessages`, et un contrôle
   « aucune migration en attente ».
5. **Fichier d'environnement** rendu en `0600`, propriété du compte de service.
6. **Service web gunicorn** supervisé + invocation périodique des quatre tâches
   selon `polls_scheduler`.
7. **Vhost nginx** depuis un gabarit, TLS (certbot par défaut), en-têtes de
   sécurité, zone de limitation de débit cohérente avec l'application.
8. **Sauvegardes** : `VACUUM INTO` nocturne, fenêtre de rétention, réplication
   hors site optionnelle.
9. **Smoke play** en dernier : service up, `/sante` répond, **un courriel de
   test part réellement** vers `polls_smoke_test_email`. Le déploiement n'est
   pas « vert » tant que le mail n'a pas quitté la machine : chaque vote en
   ligne en dépend.

## 4. Variables du rôle

Fichier de référence : `ansible/roles/polls/defaults/main.yml`. Les plus
utilisées :

| Variable | Défaut | Rôle |
|---|---|---|
| `polls_release` | `""` | **obligatoire** au déploiement : le tag à livrer. |
| `polls_domain` | `""` | nom d'hôte public, utilisé par nginx, `ALLOWED_HOSTS`, CSRF. |
| `polls_admin_email` | `""` | destinataire `MAILTO` des tâches cron, contact certbot. |
| `polls_repo_url` | `""` | dépôt à cloner ; vide ⇒ archive de l'arbre local. |
| `polls_require_tagged_release` | `false` | `true` ⇒ un HEAD non taggé est une erreur bloquante. |
| `polls_scheduler` | `cron` | `cron`, `systemd` (timers, `Persistent=true`), ou `none`. |
| `polls_job_interval_minutes` | `5` | assez court pour honorer `opens_at`/`closes_at` à la minute. |
| `polls_allow_migrate_during_open_poll` | `false` | garde-fou : voir §7. |
| `polls_open_poll_count` | `0` | nombre de scrutins `open`, pour ce garde-fou. |
| `polls_tls_method` | `certbot` | `certbot` (recommandé) ou terminaison TLS en amont. |
| `polls_enable_tls`, `polls_manage_firewall` | `true` | à laisser à `true` en production réelle. |
| `polls_backup_retention_days` | `30` | `0` conserve tout. |
| `polls_backup_hour` / `polls_backup_minute` | `3` / `17` | heure locale (Europe/Paris). |
| `polls_backup_replicate_to` | `""` | cible rsync hors site (ex. `backups@host:/srv/polls`) ; vide ⇒ désactivé. |
| `polls_restore_from` | `""` | snapshot à restaurer ; vide ⇒ le plus récent. |
| `polls_smoke_require_mail` | `true` | à ne passer à `false` que pour monter un hôte avant son relais. |
| `polls_python_version` | `3.13` | `uv` gère son propre interpréteur sous le préfixe. |
| `polls_bind` | `127.0.0.1:8000` | adresse d'écoute de gunicorn (derrière nginx). |
| `polls_gunicorn_workers` | `3` | |

## 5. Première mise en service applicative

Le playbook **ne crée pas** de compte. Après le déploiement, l'assistant de
**première installation** (`/mairie/installation/`) crée en une transaction la
fiche commune (nom, référent données personnelles, contact du référent — R-13.1,
R-13.2) et le **premier compte administrateur de la commune**. L'assistant se
ferme définitivement dès qu'un compte existe. Aucune commande
`createsuperuser` : il n'y en a pas, et `is_superuser` n'ouvre aucun écran (§14,
§6.5.11).

Voir le [guide de l'espace mairie, §2](guide-espace-mairie.md) pour la suite
(création des comptes opérateurs, import de la liste électorale, premier
scrutin).

## 6. Le planificateur

Les quatre tâches sont **auto-verrouillantes** (une ligne `JobRun` + un
`flock`) et **pilotées par l'état** : une seconde copie lancée par cron pendant
qu'une première tourne se termine en code 0 sans rien faire ; un hôte qui était
éteint rattrape au passage suivant plutôt que de sauter (§14).

| Tâche | Ce qu'elle fait | Sélection |
|---|---|---|
| `open_poll` | `draft → open` : fige la copie de la liste électorale et tire la graine d'ouverture, dans la même transaction que l'état. | scrutins `draft` dont `opens_at` est atteint |
| `close_poll` | `open → closed` : calcule l'empreinte de clôture, fige les compteurs de participation. Ne dépouille pas. | scrutins `open` dont l'échéance de saisie est atteinte |
| `send_reminders` | rappel 48 h avant clôture aux inscrits actifs n'ayant pas voté (R-5.7). | |
| `retention_purge` | efface les données d'identité des scrutins clos depuis deux mois (R-13.3). | |

**Sous cron** (défaut, universel) : `/etc/cron.d/polls` ; le script
`/opt/polls/bin/polls-manage` **source explicitement** le fichier
d'environnement — l'environnement minimal de cron est la cause classique d'une
tâche qui marche à la main et échoue en silence à trois heures du matin.

**Sous systemd** : timers avec `Persistent=true` et un délai aléatoire.

**`none`** : pour un exploitant qui a son propre ordonnanceur ; il invoque
lui-même `polls-manage <tâche>` à un intervalle court.

> Changer `polls_scheduler` sur un hôte existant **laisse en place les unités du
> mode précédent** ; les retirer à la main.

## 7. Mises à jour applicatives

1. Publier un tag.
2. `ansible-playbook -i inventory.ini site.yml --tags deploy -e polls_release=<tag>`.
3. Le bascule se fait par lien symbolique ; retour arrière = repointer `current`.

**Deux pièges que le playbook gère, et un que vous devez gérer :**

- `SECRET_KEY` est généré **au premier install et jamais régénéré**. Un gabarit
  naïf le régénère à chaque déploiement et casse toute session et tout lien
  signé en cours. C'est la façon la plus probable de casser un scrutin en cours.
  Le rôle lit la clé persistée et ne la réécrit jamais.
- Le répertoire d'état (`/var/lib/polls/`) — base, instantané de liste, journal
  d'audit — n'est **jamais** touché par le tag `deploy`.
- **Vous** : ne lancez pas `migrate` pendant qu'un scrutin est `open`. Le rôle
  refuse (`assert`) sauf si `polls_allow_migrate_during_open_poll=true` **et**
  `polls_open_poll_count` reflète la réalité. Planifiez les changements de
  schéma **entre deux scrutins**. Le tableau de bord fournit le compte de
  scrutins ouverts.

## 8. Sauvegarde

- **Nightly `VACUUM INTO`** vers `/var/backups/polls/db-<horodatage>Z.sqlite3`,
  écrit d'abord en `.partial` puis renommé, avec `PRAGMA integrity_check` : un
  snapshot corrompu est refusé sur place (installer un fichier corrompu est pire
  qu'une sauvegarde ratée — le dégât ne se voit que plus tard, contre le journal
  d'audit).
- Lien `latest.sqlite3` vers le dernier snapshot valide.
- Fenêtre de rétention : `find -mtime +(jours-1) -delete`.
- **Réplication hors site** via rsync si `polls_backup_replicate_to` est
  renseigné. L'identité SSH du compte `polls` est à vous d'installer, comme les
  secrets SMTP viennent du vault.
- Le tag `backup` réaffirme les permissions `0700` du répertoire et ne les
  élargit jamais : `token_salt` est dans chaque snapshot.
- Un **premier snapshot** est pris à la fin de l'installation, pour que
  `restore.yml` ait toujours de quoi travailler.

Vérifier :

```sh
ls -l /var/backups/polls/
sqlite3 /var/backups/polls/latest.sqlite3 'PRAGMA integrity_check;'
```

## 9. Restauration

`restore.yml` **fait partie de la livraison, pas d'un pense-bête**. Une
procédure de sauvegarde jamais restaurée n'est pas une procédure de sauvegarde,
et pour un système dont la crédibilité repose sur un journal d'audit, perdre ce
journal dans une restauration non testée serait la pire des défaillances (T-16).

```sh
# hôte perdu : provisionne, déploie, restaure le plus récent, rejoue le smoke
ansible-playbook -i inventory.ini restore.yml --ask-vault-pass

# snapshot précis
ansible-playbook -i inventory.ini restore.yml \
  -e polls_restore_from=/var/backups/polls/db-20260901T031700Z.sqlite3
```

Déroulé : vérification d'intégrité du snapshot **avant** de s'y fier → arrêt du
service web → l'ancienne base est mise de côté en `db.sqlite3.pre-restore-<...>`
→ suppression des sidecars WAL/SHM périmés → copie du snapshot en base vive →
`migrate` (un snapshot peut précéder le code déployé) → redémarrage du service →
smoke play. `provision` et `deploy` étant idempotents, lancer `restore.yml`
contre un hôte simplement endommagé est sûr : seule la base est remplacée.

## 10. Supervision

- **`GET /sante`** (hors `i18n_patterns`, jamais redirigé) : `200` avec
  `{"version": …, "migrations_pending": bool}`. Pas d'authentification, pas de
  donnée personnelle, pas de compteur — lu par le smoke play et par la
  supervision, tous deux hors périmètre de confiance.
- **Journaux** : gunicorn et les commandes écrivent sur stdout/stderr →
  journald sous systemd. nginx **supprime la journalisation de l'URI de requête
  pour le préfixe `/bulletin/`** : le jeton de vote transite dans un lien et ne
  doit jamais atteindre un log (R-7.4 ter). Ne rétablissez pas cette
  journalisation.
- **Ce qu'il faut alerter** : `/sante` qui ne répond pas ; `migrations_pending`
  à `true` après un déploiement ; échec d'une tâche cron (le `MAILTO` du
  `cron.d` pointe sur `polls_admin_email`) ; absence de nouveau snapshot depuis
  plus de 24 h ; certificat TLS proche de l'expiration.
- **Pas de compteur de participation** exposé nulle part quand
  `show_live_participation` est désactivé sur un scrutin (R-11.5) : ne
  construisez pas de sonde qui en dériverait un.

## 11. Sécurité et conformité — points techniques

- **TLS** obligatoire (certbot par défaut, renouvellement automatique). nginx
  pose HSTS, `X-Frame-Options: DENY`, `nosniff`, et `Referrer-Policy:
  no-referrer` sur les routes de bulletin.
- **Limitation de débit** (R-5.8) sur l'inscription et l'envoi de courriels ;
  elle compte à travers les workers via la table de cache en base
  (`createcachetable` est lancé par le déploiement).
- **Comptes nominatifs** (R-2.2) : un compte par personne physique, jamais de
  compte partagé. Le journal d'audit ne survit pas à un login partagé.
- **Rétention** : `retention_purge` efface, deux mois après la clôture, les
  enregistrements d'inscription, la copie figée de la liste, l'association
  bulletin papier ↔ électeur, et les champs déclarés « données personnelles »
  de chaque catégorie d'événement d'audit — **en conservant l'événement, son
  auteur, sa date et son motif** (R-12.4, R-13.3). Les bulletins anonymisés, le
  résultat publié et le journal lui-même sont conservés au-delà.
- **Un vrai export de liste électorale est la donnée personnelle de tous les
  électeurs de la commune** (R-13.6) : il ne va jamais dans le dépôt, la suite
  de tests ou un rapport d'incident. Les données de test sont synthétiques.
- **Niveau de risque CNIL** : le logiciel est conçu pour le **niveau 1**
  (consultation à faible enjeu). Voir le `README.md` racine et faire valider par
  le DPO de la commune avant tout scrutin qui ne serait pas clairement de
  niveau 1.

## 12. Dépannage rapide

| Symptôme | Piste |
|---|---|
| `/sante` répond `migrations_pending: true` | relancer le tag `deploy` ; vérifier qu'aucun scrutin n'est `open` si `migrate` a été bloqué. |
| Les liens de modification de bulletin ne fonctionnent plus après un déploiement | `SECRET_KEY` a été régénéré. Restaurer `/etc/polls/secret_key` depuis une sauvegarde ; les liens signés avant le changement restent perdus. |
| Le smoke play échoue sur le courriel | relais SMTP injoignable ou identifiants du vault faux. Corriger, relancer `--tags deploy` puis le smoke. Un hôte peut être monté sans relais avec `polls_smoke_require_mail=false`, à corriger avant l'ouverture d'un scrutin. |
| Une tâche cron « marche à la main » mais pas planifiée | l'environnement n'est pas sourcé. Utiliser `/opt/polls/bin/polls-manage <tâche>`, pas `manage.py` directement. |
| `open_poll` n'ouvre pas un scrutin à l'heure dite | vérifier que le planificateur tourne (`systemctl list-timers`, ou `/etc/cron.d/polls`) et l'intervalle `polls_job_interval_minutes`. Le tableau de bord du scrutin liste ce qui bloque l'ouverture (traduction manquante, pas de liste à figer). |
| Après restauration, le service ne démarre pas | sidecars `db.sqlite3-wal`/`-shm` périmés (normalement supprimés par `restore.yml`) ; ou snapshot d'un schéma plus récent que le code déployé — déployer d'abord le bon tag. |
