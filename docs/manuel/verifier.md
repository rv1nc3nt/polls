<!-- SPDX-License-Identifier: 0BSD -->

# Vérifier un résultat par vous-même

Ce guide s'adresse à **quiconque** souhaite s'assurer, sans avoir à faire
confiance ni à la mairie, ni à l'éditeur du logiciel, qu'un résultat publié
est bien celui que les bulletins déposés produisent. Vous n'avez besoin
d'aucune compétence en informatique au-delà de savoir ouvrir un terminal et
suivre des instructions — ce document explique chaque étape.

Aucune inscription n'est requise pour cette vérification : les données dont
vous avez besoin sont **publiques**, sur la page de résultats de la
consultation (R-11.2, R-11.4).

## Pourquoi ce programme existe

Le site public affiche déjà le résultat, la matrice des préférences et le
raisonnement. Mais le site public est un juge et partie : il calcule le
résultat *et* l'affiche. Le **vérificateur** est un second programme,
totalement indépendant :

- il est écrit dans un autre langage (Rust, quand le site est écrit en
  Python) et ne partage aucun code avec lui — une divergence dans le premier
  ne peut pas se retrouver dans le second par accident ;
- il ne se connecte à aucune base de données et n'a besoin d'aucun accès à la
  mairie ou à son serveur : il ne lit que le fichier CSV que le site public
  publie pour tout le monde ;
- il recalcule tout depuis zéro — l'empreinte de clôture, la matrice des
  duels, le vainqueur et, s'il y a lieu, le départage — et vous dit s'il
  retrouve exactement ce que le site annonce.

S'il retrouve le même résultat, vous avez la preuve, indépendamment du site,
que le décompte est correct. S'il ne le retrouve pas, quelque chose ne va
pas, et il faut le signaler (voir [« Que faire en cas de désaccord »](#que-faire-en-cas-de-désaccord)
plus bas) plutôt que faire confiance à l'un ou l'autre des deux calculs.

## Ce qu'il vous faut

Trois choses, toutes disponibles depuis la page de résultats de la
consultation (figure 20 du [guide de l'électeur](guide-electeur.md#8-vérifier-après-la-clôture)) :

1. le fichier **CSV** de la liste anonymisée des bulletins — un lien
   « Liste anonymisée des bulletins (CSV) » sur cette page ;
2. l'**empreinte de clôture** affichée sur la même page (une suite de
   caractères hexadécimaux, ex. `87694cf0…`) ;
3. le **vérificateur**, un petit programme à télécharger une seule fois —
   voir ci-dessous.

## Télécharger le vérificateur

Le vérificateur est distribué déjà compilé, pour ne demander à personne
d'installer un environnement de développement. Rendez-vous sur la page des
publications du projet :

    https://github.com/rv1nc3nt/polls/releases

Ouvrez la publication la plus récente et repérez, dans la liste des fichiers
joints (« Assets »), celui qui correspond à votre système :

| Votre système | Fichier à télécharger |
|---|---|
| Windows | `polls-verifier-windows-x86_64.exe` |
| macOS, Mac récent (puce Apple, « M1 », « M2 », « M3 »…) | `polls-verifier-macos-aarch64` |
| macOS, Mac plus ancien (puce Intel) | `polls-verifier-macos-x86_64` |
| Linux | `polls-verifier-linux-x86_64` |

> **Vous ne savez pas quelle puce a votre Mac ?** Menu Pomme (en haut à
> gauche de l'écran) → « À propos de ce Mac ». La ligne « Puce » ou
> « Processeur » indique « Apple M… » (choisissez `aarch64`) ou « Intel »
> (choisissez `x86_64`). En cas de doute, la version Intel fonctionne aussi
> sur les Mac Apple Silicon, seulement un peu plus lentement.

Placez le fichier téléchargé dans un dossier facile à retrouver — par
exemple à côté du fichier CSV que vous avez déjà téléchargé.

## Préparer le programme, selon votre système

Un programme téléchargé sur Internet n'est pas exécutable tout de suite :
votre système le protège par défaut, et il faut lui donner l'autorisation
explicitement. C'est normal, et à faire une seule fois.

### Windows

1. Ouvrez le dossier où vous avez téléchargé le fichier, dans l'Explorateur.
2. Double-cliquez dessus. Windows affiche probablement un écran bleu
   « Windows a protégé votre ordinateur » (SmartScreen) : c'est attendu pour
   un programme peu téléchargé, pas un signe de danger en soi, mais vérifiez
   que vous l'avez bien pris sur `github.com/rv1nc3nt/polls`. Cliquez sur
   « Informations complémentaires », puis « Exécuter quand même ».
3. Une fenêtre noire (l'invite de commandes) s'ouvre et se referme aussitôt —
   c'est normal, le programme a besoin qu'on lui indique quel fichier
   vérifier (étape suivante). Il ne se lance pas tout seul en double-cliquant.
4. Ouvrez une invite de commandes dans ce dossier : dans l'Explorateur,
   maintenez Maj enfoncé, clic droit dans le dossier, « Ouvrir la fenêtre
   PowerShell ici » (ou « Ouvrir dans le terminal »).

### macOS

1. Ouvrez le Terminal (Applications → Utilitaires → Terminal).
2. Rendez le fichier exécutable et retirez le signalement de mise en
   quarantaine que macOS pose sur tout fichier téléchargé :

       cd ~/Downloads
       chmod +x polls-verifier-macos-aarch64
       xattr -d com.apple.quarantine polls-verifier-macos-aarch64

   (remplacez le nom de fichier par celui que vous avez téléchargé, et
   `~/Downloads` par le dossier où il se trouve si différent).
3. Si macOS refuse quand même de le lancer (« ne peut pas être ouvert car
   l'éditeur ne peut pas être vérifié »), ouvrez Réglages Système →
   Confidentialité et sécurité, faites défiler jusqu'au message concernant ce
   fichier et cliquez sur « Ouvrir quand même ».

### Linux

Ouvrez un terminal dans le dossier de téléchargement et rendez le fichier
exécutable :

    cd ~/Téléchargements
    chmod +x polls-verifier-linux-x86_64

## Lancer la vérification

Depuis le terminal ouvert dans le dossier où se trouvent le programme et le
fichier CSV, tapez (en adaptant les noms de fichiers à ce que vous avez
téléchargé, et l'empreinte à celle affichée sur la page de résultats) :

**Windows (PowerShell) :**

    .\polls-verifier-windows-x86_64.exe ballots.csv --closure-hash 87694cf0...

**macOS ou Linux :**

    ./polls-verifier-macos-aarch64 ballots.csv --closure-hash 87694cf0...

Le programme affiche le nombre de bulletins lus, l'empreinte qu'il a
lui-même recalculée, la liste des options, la matrice des duels et le ou les
vainqueurs selon la méthode Schulze — puis, en dernière ligne utile :

    closure hash    AGREES

`AGREES` signifie que l'empreinte que vous avez recalculée est identique à
celle publiée sur le site : le fichier CSV n'a pas été altéré depuis le
calcul de clôture. `DIFFERS` signifierait le contraire (voir plus bas).

Pour vérifier également le vainqueur annoncé, ajoutez `--winner` suivi de
l'identifiant de l'option retenue (visible dans la matrice, entre
parenthèses à côté du libellé sur la page de résultats) :

    ./polls-verifier-macos-aarch64 ballots.csv --closure-hash 87694cf0... --winner option-b

Une ligne `winner AGREES` confirme que le vérificateur, en repartant de zéro
à partir du seul fichier public, retrouve exactement le vainqueur annoncé
par le site.

### En cas d'égalité (départage)

Si la page de résultats indique qu'un départage a eu lieu, elle publie aussi
la **graine d'ouverture** — une seconde suite hexadécimale, distincte de
l'empreinte de clôture. Ajoutez-la avec `--opening-seed` pour que le
vérificateur rejoue le départage lui-même :

    ./polls-verifier-macos-aarch64 ballots.csv --closure-hash 87694cf0... --opening-seed a1b2c3... --winner option-b

Le départage n'utilise ni tirage au sort, ni fonction du langage de
programmation : il est entièrement déterminé par l'empreinte de clôture et
la graine d'ouverture, ce qui est précisément ce que cette commande vérifie.

## Que faire en cas de désaccord

Si une ligne affiche `DIFFERS` :

1. Vérifiez d'abord que vous avez copié l'empreinte (et, le cas échéant, la
   graine d'ouverture) **sans espace ni caractère manquant**, et que le
   fichier CSV téléchargé est bien complet (le refaire depuis la page de
   résultats en cas de doute).
2. Si le désaccord persiste, **ne le gardez pas pour vous** : contactez la
   mairie en indiquant la consultation concernée, la commande exacte que
   vous avez lancée et son résultat complet. C'est exactement le type
   d'anomalie que cette vérifiabilité (R-11.4) est censée pouvoir détecter.

## Pour aller plus loin

Le code source du vérificateur (`verifier/`) et le format exact du fichier
CSV qu'il lit (`docs/canonical-serialisation.md`) sont publics : n'importe
qui peut relire ce que fait exactement ce programme, ou écrire sa propre
version dans un autre langage pour vérifier de manière encore plus
indépendante.
