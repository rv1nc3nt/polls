<!-- SPDX-License-Identifier: 0BSD -->

# Vérifier un résultat par vous-même

Ce guide s'adresse à **quiconque** souhaite s'assurer, sans avoir à faire
confiance ni à la mairie, ni à l'éditeur du logiciel, qu'un résultat publié
est bien celui que les bulletins déposés produisent. Vous n'avez besoin
d'aucune compétence en informatique au-delà de savoir télécharger un fichier
et suivre des instructions — ce document explique chaque étape, à la souris
comme au clavier.

Aucune inscription n'est requise pour cette vérification : les données dont
vous avez besoin sont **publiques**, sur la page de résultats de la
consultation.

## Pourquoi ce programme existe

Le site public affiche déjà le résultat, la matrice des préférences et le
raisonnement. Mais le site public est un juge et partie : il calcule le
résultat *et* l'affiche. Le **vérificateur** est un second programme,
totalement indépendant :

- il est écrit dans un autre langage (Rust, quand le site est écrit en
  Python) et ne partage aucun code avec lui — une divergence dans le premier
  ne peut pas se retrouver dans le second par accident ;
- il ne se connecte à aucune base de données et n'a besoin d'aucun accès à la
  mairie ou à son serveur : il ne lit que ce que le site public publie pour
  tout le monde — le document de publication ou le fichier CSV ;
- il recalcule tout depuis zéro — l'empreinte de clôture, la matrice des
  duels, le vainqueur et, s'il y a lieu, le départage — et vous dit s'il
  retrouve exactement ce que le site annonce.

S'il retrouve le même résultat, vous avez la preuve, indépendamment du site,
que le décompte est correct. S'il ne le retrouve pas, quelque chose ne va
pas, et il faut le signaler (voir [« Que faire en cas de désaccord »](#que-faire-en-cas-de-désaccord)
plus bas) plutôt que faire confiance à l'un ou l'autre des deux calculs.

## Ce qu'il vous faut

Deux choses :

1. le **document de publication** de la consultation — le lien « Document de
   publication complet (JSON) » de sa page de résultats (figure 20 du [guide
   de l'électeur](guide-electeur.md#8-vérifier-après-la-clôture)). Il contient
   la liste anonymisée des bulletins et toutes les valeurs que le site
   publie : méthode de dépouillement, options, empreinte de clôture, matrice
   des duels, vainqueur et, s'il y a lieu, départage ;
2. le **vérificateur**, un petit programme à télécharger une seule fois —
   voir ci-dessous.

La même page propose aussi la **liste anonymisée des bulletins (CSV)**, qui
s'ouvre dans un tableur. Le vérificateur la lit également, mais elle ne
contient que les bulletins : il faut alors lui indiquer soi-même les valeurs
à comparer, recopiées depuis la page de résultats (voir plus bas).

Le vérificateur existe sous deux formes, construites à partir du même code de
vérification : une **application graphique**, recommandée pour la plupart des
gens, et une **ligne de commande**, pour qui est à l'aise avec un terminal ou
souhaite automatiser des vérifications répétées. Les deux donnent exactement
le même résultat ; choisissez selon votre confort.

## Télécharger le vérificateur

Le vérificateur est distribué déjà compilé, pour ne demander à personne
d'installer un environnement de développement. Rendez-vous sur la page des
publications du projet :

    https://github.com/rv1nc3nt/polls/releases

Ouvrez la publication la plus récente et repérez, dans la liste des fichiers
joints (« Assets »), celui qui correspond à votre système — l'application
graphique si vous n'êtes pas à l'aise avec un terminal, sinon la ligne de
commande :

| Votre système | Application graphique | Ligne de commande |
|---|---|---|
| Windows | `polls-verifier-gui-windows-x86_64.exe` | `polls-verifier-windows-x86_64.exe` |
| macOS, Mac récent (puce Apple, « M1 », « M2 », « M3 »…) | `polls-verifier-gui-macos-aarch64` | `polls-verifier-macos-aarch64` |
| macOS, Mac plus ancien (puce Intel) | `polls-verifier-gui-macos-x86_64` | `polls-verifier-macos-x86_64` |
| Linux | `polls-verifier-gui-linux-x86_64` | `polls-verifier-linux-x86_64` |

> **Vous ne savez pas quelle puce a votre Mac ?** Menu Pomme (en haut à
> gauche de l'écran) → « À propos de ce Mac ». La ligne « Puce » ou
> « Processeur » indique « Apple M… » (choisissez `aarch64`) ou « Intel »
> (choisissez `x86_64`). En cas de doute, la version Intel fonctionne aussi
> sur les Mac Apple Silicon, seulement un peu plus lentement.

Placez le fichier téléchargé dans un dossier facile à retrouver — par
exemple à côté du document de publication que vous avez déjà téléchargé.

## Utiliser l'application graphique (recommandé)

### Windows

Double-cliquez sur le fichier téléchargé. Windows affiche probablement un
écran bleu « Windows a protégé votre ordinateur » (SmartScreen) : c'est
attendu pour un programme peu téléchargé, pas un signe de danger en soi, mais
vérifiez que vous l'avez bien pris sur `github.com/rv1nc3nt/polls`. Cliquez
sur « Informations complémentaires », puis « Exécuter quand même ». La
fenêtre de l'application s'ouvre.

### macOS

Double-cliquez sur le fichier téléchargé dans le Finder. Si macOS refuse de
le lancer (« ne peut pas être ouvert car l'éditeur ne peut pas être
vérifié »), ouvrez le Terminal (Applications → Utilitaires → Terminal) et
retirez le signalement de mise en quarantaine :

    cd ~/Downloads
    chmod +x polls-verifier-gui-macos-aarch64
    xattr -d com.apple.quarantine polls-verifier-gui-macos-aarch64

(remplacez le nom de fichier par celui que vous avez téléchargé). Double-
cliquez à nouveau ; si macOS demande encore confirmation, ouvrez Réglages
Système → Confidentialité et sécurité, faites défiler jusqu'au message
concernant ce fichier et cliquez sur « Ouvrir quand même ».

### Linux

Rendez le fichier exécutable puis double-cliquez dessus dans votre
gestionnaire de fichiers (ou lancez-le depuis un terminal) :

    cd ~/Téléchargements
    chmod +x polls-verifier-gui-linux-x86_64
    ./polls-verifier-gui-linux-x86_64

### Vérifier

La fenêtre « Vérificateur indépendant » propose trois étapes ; avec le
document de publication, seules la première et la dernière servent :

1. **Fichier** — cliquez sur « Choisir un fichier… » et sélectionnez le
   document de publication (JSON) téléchargé, ou déposez-le directement dans
   la fenêtre.
2. **Valeurs à comparer** — à laisser vide avec le document de publication,
   qui les contient toutes. Elles ne servent qu'avec le fichier CSV : la
   **méthode de dépouillement** que la page de résultats indique (Schulze,
   majoritaire ou par assentiment), les **identifiants des options**
   séparés par des virgules, l'**empreinte de clôture attendue**, la
   **graine d'ouverture** en cas d'égalité et le **vainqueur annoncé**. Tous
   sont facultatifs — sans eux, l'application affiche quand même ce qu'elle a
   recalculé, simplement sans rien comparer.
3. Cliquez sur **Vérifier**.

Avec le document de publication, le résultat commence par une ligne verte
« ✓ … concorde » ou rouge « ✗ … NE concorde PAS » pour chacune des valeurs
publiées : nombre de bulletins, matrice des duels, voix par option (scrutin
majoritaire ou par assentiment), départage s'il y en a eu un, empreinte de
clôture et vainqueur. Viennent ensuite la méthode de dépouillement, telle que
le document la déclare — comparez-la avec celle que la consultation
annonçait avant son ouverture, c'est la seule valeur que le vérificateur ne
peut pas recalculer —, la matrice et le ou les vainqueurs recalculés. C'est
l'équivalent exact des lignes `AGREES` / `DIFFERS` de la version en ligne de
commande ci-dessous ; voir [« Que faire en cas de
désaccord »](#que-faire-en-cas-de-désaccord) si vous obtenez un désaccord.

## Utiliser la ligne de commande

Cette section s'adresse à qui préfère un terminal — pour scripter une
vérification, ou en automatiser plusieurs. Le résultat est identique à celui
de l'application graphique ; les deux appellent le même code de vérification.

### Préparer le programme, selon votre système

Un programme téléchargé sur Internet n'est pas exécutable tout de suite :
votre système le protège par défaut, et il faut lui donner l'autorisation
explicitement. C'est normal, et à faire une seule fois.

#### Windows

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

#### macOS

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

#### Linux

Ouvrez un terminal dans le dossier de téléchargement et rendez le fichier
exécutable :

    cd ~/Téléchargements
    chmod +x polls-verifier-linux-x86_64

### Lancer la vérification

Depuis le terminal ouvert dans le dossier où se trouvent le programme et le
document de publication, tapez (en adaptant les noms de fichiers à ce que
vous avez téléchargé) :

**Windows (PowerShell) :**

    .\polls-verifier-windows-x86_64.exe publication.json

**macOS ou Linux :**

    ./polls-verifier-macos-aarch64 publication.json

Aucune autre valeur n'est à fournir : le document les contient toutes. Le
programme affiche la méthode de dépouillement que le document déclare, le
nombre de bulletins lus, l'empreinte qu'il a lui-même recalculée, la liste
des options, la matrice des duels, le nombre de voix de chaque option pour un
scrutin majoritaire ou par assentiment et le ou les vainqueurs — puis une
ligne par valeur publiée qu'il a vérifiée :

    closure hash    AGREES
    ballot count    AGREES
    matrix          AGREES
    winner          AGREES

`AGREES` signifie que la valeur recalculée à partir des seuls bulletins est
identique à celle que le site publie ; `DIFFERS` signifierait le contraire
(voir plus bas). S'y ajoutent une ligne `counts` pour un scrutin majoritaire
ou par assentiment, et une ligne `tie-break` si un départage a eu lieu.

La méthode de dépouillement est la seule valeur que le vérificateur ne peut
pas recalculer, puisque c'est elle qui décide du vainqueur : il l'affiche en
première ligne (`method`) pour que vous la compariez avec celle que la
consultation annonçait avant son ouverture.

#### Avec le fichier CSV

Le fichier CSV ne contient que les bulletins : les valeurs à comparer se
recopient depuis la page de résultats. Tapez (en adaptant les noms de
fichiers, et l'empreinte à celle affichée sur la page de résultats) :

**Windows (PowerShell) :**

    .\polls-verifier-windows-x86_64.exe ballots.csv --closure-hash 87694cf0...

**macOS ou Linux :**

    ./polls-verifier-macos-aarch64 ballots.csv --closure-hash 87694cf0...

Le programme affiche le nombre de bulletins lus, l'empreinte qu'il a
lui-même recalculée, la liste des options, la matrice des duels et le ou les
vainqueurs — puis, en dernière ligne utile :

    closure hash    AGREES

`AGREES` signifie que l'empreinte que vous avez recalculée est identique à
celle publiée sur le site : le fichier CSV n'a pas été altéré depuis le
calcul de clôture. `DIFFERS` signifierait le contraire (voir plus bas).

Pour vérifier également le vainqueur annoncé, ajoutez `--winner` suivi de
l'identifiant de l'option retenue (visible dans la matrice, entre
parenthèses à côté du libellé sur la page de résultats), et `--method` suivi
de la méthode de dépouillement que la page de résultats indique :
`schulze`, `majoritaire` ou `assentiment` :

    ./polls-verifier-macos-aarch64 ballots.csv --closure-hash 87694cf0... --method majoritaire --winner option-b

Une ligne `winner AGREES` confirme que le vérificateur, en repartant de zéro
à partir du seul fichier public, retrouve exactement le vainqueur annoncé
par le site.

Le fichier CSV ne dit pas quelle méthode le scrutin a employée : c'est à vous
de la donner. Sans `--method`, le vérificateur compte selon la méthode de
Schulze, et il indique en première ligne (`method`) la méthode qu'il a
appliquée. Un vainqueur recalculé selon une autre méthode que celle du scrutin
peut différer sans que rien ne soit faux. La vérification de l'empreinte,
elle, vaut quelle que soit la méthode.

Le fichier CSV ne dit pas non plus quelles options le scrutin proposait : il
ne connaît que celles qu'un bulletin au moins a classées. Pour retrouver
toutes les lignes de la matrice publiée, y compris celle d'une option que
personne n'a classée, ajoutez `--options` suivi des identifiants des options,
séparés par des virgules (`--options option-a,option-b,option-c`). Une option
absente de la liste mais classée par un bulletin est signalée comme une
erreur : la liste ou le fichier n'est pas celui du scrutin.

#### En cas d'égalité (départage)

Avec le document de publication, il n'y a rien à ajouter : le vérificateur
rejoue lui-même le départage calculé à partir de la graine d'ouverture que le
document contient, et le compare à celui publié (ligne `tie-break`). Si la
consultation avait prévu un **tirage au sort physique**, mené à la mairie,
aucun programme ne peut le rejouer : le vérificateur contrôle seulement que
le tirage publié porte exactement sur les options à égalité, et le signale.

Avec le fichier CSV, la page de résultats publie aussi la **graine
d'ouverture** — une seconde suite hexadécimale, distincte de l'empreinte de
clôture. Ajoutez-la avec `--opening-seed` pour que le vérificateur rejoue le
départage lui-même :

    ./polls-verifier-macos-aarch64 ballots.csv --closure-hash 87694cf0... --method schulze --opening-seed a1b2c3... --winner option-b

Le départage n'utilise ni tirage au sort, ni fonction du langage de
programmation : il est entièrement déterminé par l'empreinte de clôture et
la graine d'ouverture, ce qui est précisément ce que cette commande vérifie.
Voir [Les méthodes de dépouillement, expliquées](methodes-de-depouillement.md#égalités-et-départage)
pour le détail de ce calcul.

## Que faire en cas de désaccord

Si une ligne affiche `DIFFERS` :

1. Vérifiez d'abord que le fichier téléchargé est bien complet (le
   télécharger à nouveau depuis la page de résultats en cas de doute) et,
   avec le fichier CSV, que vous avez copié l'empreinte (et, le cas échéant,
   la graine d'ouverture) **sans espace ni caractère manquant**.
2. Si le désaccord persiste, **ne le gardez pas pour vous** : contactez la
   mairie en indiquant la consultation concernée, la commande exacte que
   vous avez lancée et son résultat complet. C'est exactement le type
   d'anomalie que cette vérifiabilité est censée pouvoir détecter.

## Pour aller plus loin

Le code source du vérificateur (`verifier/`) et le format exact des fichiers
qu'il lit (`docs/publication-format.md` pour le document de publication,
`docs/canonical-serialisation.md` pour les bulletins et l'empreinte) sont
publics : n'importe qui peut relire ce que fait exactement ce programme, ou
écrire sa propre version dans un autre langage pour vérifier de manière
encore plus indépendante. Pour comprendre ce que le vérificateur recalcule au juste — la
méthode de Schulze, majoritaire ou par assentiment, et le départage — voir
[Les méthodes de dépouillement, expliquées](methodes-de-depouillement.md).
