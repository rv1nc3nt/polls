<!-- SPDX-License-Identifier: 0BSD -->

# Les méthodes de dépouillement, expliquées

Ce document explique, sans prérequis mathématique, les trois méthodes de
dépouillement que propose la plateforme — **Schulze**, **majoritaire** et
**par assentiment** — ainsi que la règle appliquée quand deux propositions
restent à égalité. Il s'adresse à **quiconque** veut comprendre comment un
résultat publié a été obtenu : électeur curieux, élu·e ou agent·e qui
configure un scrutin, ou toute personne qui recalcule un résultat par
elle-même.

Chaque méthode est d'abord expliquée en clair, avec un exemple chiffré ; la
dernière partie, [« Approfondissement : le code »](#approfondissement-le-code),
montre le code source exact qui l'implémente, pour qui veut aller plus loin
que l'intuition. Les deux parties se répondent : les exemples chiffrés y
apparaissent recalculés.

## En bref

| Méthode | Ce que porte le bulletin | Qui gagne |
|---|---|---|
| **Schulze** | un classement de préférences, complet ou non | l'option qui bat, directement ou par le chemin de préférences le plus fort, chacune des autres en duel |
| **Majoritaire** | un choix unique | l'option choisie en premier par le plus grand nombre |
| **Par assentiment** | un ensemble d'options approuvées, sans ordre | l'option approuvée par le plus grand nombre |

Les trois sont des **fonctions pures** : à bulletins identiques, elles
donnent toujours le même résultat, recalculable par n'importe qui à partir
des seules données publiées — voir [Vérifier un résultat par
vous-même](verifier.md). Un scrutin donné n'en utilise qu'**une seule**,
fixée à sa configuration et publiée avec le résultat ; ce document les
présente toutes pour qu'on comprenne la différence, pas pour suggérer qu'on
pourrait choisir après coup.

Il arrive qu'une méthode ne départage pas deux propositions : voir
[« Égalités et départage »](#égalités-et-départage) plus bas.

## La méthode de Schulze

C'est la méthode à utiliser dès qu'un scrutin comporte **plus de deux**
propositions et qu'on veut recueillir un **ordre de préférence**, pas
seulement un choix unique — « quel projet en premier, lequel en second… ».
Chaque électeur classe les propositions ; le classement peut être incomplet
ou comporter des ex æquo si la configuration du scrutin l'autorise (les
propositions non classées comptent alors ex æquo en dernière position).

L'idée : traiter le classement de chaque bulletin comme une série de
**duels**. Un bulletin qui classe *Jardin partagé* avant *Aire de jeux* est
une voix pour *Jardin partagé* dans le duel qui les oppose. On compte ainsi,
pour chaque paire de propositions, combien de bulletins préfèrent l'une à
l'autre. La proposition qui gagne tous ses duels — directement, ou en
s'appuyant sur une chaîne de victoires plus forte que celle de son
adversaire — remporte le scrutin.

### Exemple

Une commune consulte ses habitants sur l'aménagement d'un terrain :
*Jardin partagé*, *Aire de jeux* ou *Parking*. Cinq bulletins sont déposés :

| Bulletin | 1ᵉʳ | 2ᵉ | 3ᵉ |
|---|---|---|---|
| 1 | Jardin | Jeux | Parking |
| 2 | Jardin | Jeux | Parking |
| 3 | Jeux | Parking | Jardin |
| 4 | Parking | Jeux | Jardin |
| 5 | Jeux | Jardin | Parking |

**Premier duel : Jardin contre Jeux.** Jardin est préféré sur les bulletins
1 et 2 (2 voix) ; Jeux l'est sur les bulletins 3, 4 et 5 (3 voix). Jeux gagne
ce duel, 3 voix à 2.

**Deuxième duel : Jardin contre Parking.** Jardin gagne sur 1, 2 et 5
(3 voix) ; Parking sur 3 et 4 (2 voix). Jardin gagne ce duel, 3 voix à 2.

**Troisième duel : Jeux contre Parking.** Jeux gagne sur 1, 2, 3 et 5
(4 voix) ; Parking seulement sur 4 (1 voix). Jeux gagne ce duel, 4 voix à 1.

*Jeux* gagne ses deux duels directement — contre *Jardin* et contre
*Parking* — et remporte donc le scrutin, sans qu'il soit même nécessaire de
raisonner sur des chemins indirects : ici, l'option qui bat toutes les
autres en duel direct (on l'appelle le « vainqueur de Condorcet ») existe, et
Schulze la retient toujours.

### Quand une chaîne de victoires compte

Le résultat n'est pas toujours aussi simple : trois propositions peuvent se
battre en cercle — *A* bat *B*, *B* bat *C*, *C* bat *A* — sans qu'aucune ne
batte les deux autres directement. C'est dans ce cas que Schulze compare la
**chaîne de victoires la plus forte** de chaque option vers chaque autre, pas
seulement le duel direct : si *A* ne bat pas *C* directement mais bat *B* par
une marge plus large que celle par laquelle *C* bat *A*, alors la chaîne
*A → B → C* peut l'emporter sur le duel direct *C → A*. C'est précisément le
calcul du [code source](#schulze-81) ci-dessous. Un cercle parfaitement
symétrique — le même nombre de bulletins pour *A > B > C*, pour *B > C > A*
et pour *C > A > B* — ne laisse subsister aucune chaîne plus forte qu'une
autre : Schulze rapporte alors une véritable égalité, tranchée par le
[départage](#égalités-et-départage).

## Le vote majoritaire

C'est le scrutin classique à un tour : chaque bulletin porte un **choix
unique**, et l'option choisie par le plus grand nombre l'emporte. Aucun
classement, aucune notion de deuxième préférence.

### Exemple

Reprenons les cinq mêmes bulletins que ci-dessus, mais en ne retenant que la
**première préférence** de chacun — c'est tout ce qu'un scrutin majoritaire
demande à l'électeur :

| Proposition | Voix |
|---|---|
| Jardin (bulletins 1, 2) | 2 |
| Jeux (bulletins 3, 5) | 2 |
| Parking (bulletin 4) | 1 |

À bulletins presque identiques, le résultat change : *Jardin* et *Jeux* sont
à **égalité** à deux voix chacun, alors que Schulze désignait *Jeux* sans
ambiguïté. Ce n'est pas une bizarrerie de l'exemple : c'est la raison même
pour laquelle le choix de la méthode se fait *avant* le scrutin, à la
configuration, et reste figé ensuite — changer de méthode après coup
changerait le résultat sur les mêmes bulletins.

> **Piège de configuration.** Si le scrutin autorise les ex æquo sur un
> bulletin *et* utilise la méthode majoritaire, un électeur qui place
> plusieurs propositions à égalité en tête donne une voix à **chacune**
> d'elles — presque toujours involontaire pour une question à choix unique.
> L'écran de configuration de l'espace mairie avertit dans ce cas.

## Le vote par assentiment

Ici, le bulletin ne classe rien : l'électeur **approuve** autant de
propositions qu'il le souhaite, sans les ordonner — « cochez toutes celles
qui conviennent ». Chaque proposition approuvée reçoit une voix ; la
proposition approuvée par le plus grand nombre d'électeurs l'emporte. Un
électeur peut approuver une seule proposition, toutes, ou aucune.

### Exemple

Même consultation, mais les électeurs cochent librement ce qui leur convient
plutôt que de classer :

| Électeur | Approuve |
|---|---|
| 1 | Jardin, Jeux |
| 2 | Jardin, Jeux |
| 3 | Jeux, Parking |
| 4 | Parking |
| 5 | Jeux |

*Jeux* est approuvé par les électeurs 1, 2, 3 et 5 — 4 voix — contre 3 pour
*Jardin* (1, 2) et 2 pour *Parking* (3, 4). *Jeux* l'emporte, sans égalité
cette fois.

Cette méthode convient bien à une question du type « laquelle de ces options
seriez-vous prêt·e à accepter ? », où forcer un classement complet donnerait
une information que l'électeur n'a pas vraiment.

## Égalités et départage

Les trois méthodes peuvent laisser subsister une **égalité réelle** : deux
options ou plus à égalité de voix (majoritaire, assentiment), ou deux options
ou plus qu'aucune chaîne de préférences ne départage (Schulze — voir
l'exemple du cercle ci-dessus). Dans ce cas, la **règle de départage** propre
au scrutin s'applique. Deux règles existent :

**Tirage au sort calculé (par défaut).** Un calcul déterministe, ni généré
par le hasard du langage de programmation, ni prévisible avant la clôture du
scrutin :

1. une **graine d'ouverture** est tirée à l'ouverture du scrutin et publiée
   aussitôt ;
2. à la clôture, l'**empreinte de clôture** — qui dépend de l'ensemble des
   bulletins déposés — est calculée et publiée ;
3. la **graine de départage** est le hachage SHA-256 de la graine d'ouverture
   suivie de l'empreinte de clôture ;
4. chaque option à égalité est classée par le hachage SHA-256 de cette graine
   suivie de son identifiant ; la plus petite valeur gagne.

Comme la graine de départage dépend de l'empreinte de clôture, et donc de
chaque bulletin déposé, l'issue n'est connue de personne — pas même de la
mairie — avant que le dernier bulletin ne soit compté, et elle est
recalculable par n'importe qui à partir des seules valeurs publiées : c'est
exactement ce que vérifie l'option `--opening-seed` du [vérificateur
indépendant](verifier.md#en-cas-dégalité-départage).

**Tirage au sort physique.** Une consultation peut opter, à sa configuration,
pour un tirage au sort mené publiquement (à la mairie, devant témoins) plutôt
que calculé. Son résultat est alors saisi par un·e responsable au moment de
la clôture et consigné dans la publication au même titre que le reste.

## Approfondissement : le code

Cette partie montre le code source exact qui calcule chacun des résultats
ci-dessus — `src/apps/tally/methods.py` et `src/apps/tally/tiebreak.py`. Le
dépouillement est une fonction pure (§8, R-10.1) : aucune donnée en base,
aucune horloge, aucun aléa hors le tirage au sort décrit ci-dessus ; on peut
donc le lire, comme ce qui suit, sans connaître le reste de l'application.

### Schulze (§8.1)

La matrice des duels — `d[i][j]`, le nombre de bulletins classant `i`
strictement avant `j` — se construit ainsi (les options non classées d'un
bulletin comptent ex æquo en dernier, règle R-10.4) :

```python
def pairwise_matrix(
    ballots: Sequence[Ranking], options: Sequence[OptionId]
) -> dict[OptionId, dict[OptionId, int]]:
    d: dict[OptionId, dict[OptionId, int]] = {i: {j: 0 for j in options if j != i} for i in options}
    option_set = set(options)
    for ranking in ballots:
        rank_of: dict[OptionId, int] = {}
        for position, group in enumerate(ranking):
            for option in group:
                if option in option_set:
                    rank_of[option] = position
        unranked = option_set - rank_of.keys()
        last = len(ranking)
        for option in unranked:
            rank_of[option] = last
        for i in options:
            for j in options:
                if i != j and rank_of[i] < rank_of[j]:
                    d[i][j] += 1
    return d
```

Sur l'exemple ci-dessus, cette fonction produit exactement les trois duels
comptés à la main : `d["jeux"]["jardin"] == 3`, `d["jardin"]["jeux"] == 2`, et
ainsi de suite.

Les forces de chemin — la « chaîne de victoires la plus forte » évoquée plus
haut — se calculent ensuite à partir de `d` :

```python
def schulze_paths(
    d: Mapping[OptionId, Mapping[OptionId, int]], options: Sequence[OptionId]
) -> dict[OptionId, dict[OptionId, int]]:
    p: dict[OptionId, dict[OptionId, int]] = {
        i: {j: (d[i][j] if d[i][j] > d[j][i] else 0) for j in options if j != i} for i in options
    }
    for i in options:
        for j in options:
            if j == i:
                continue
            for k in options:
                if k in (i, j):
                    continue
                p[j][k] = max(p[j][k], min(p[j][i], p[i][k]))
    return p
```

`p` part des duels directs (`p[i][j] = d[i][j]` si `i` bat `j`, sinon 0), puis
la triple boucle essaie, pour chaque paire `(j, k)`, de faire mieux en
passant par une option intermédiaire `i` : la force du chemin `j → i → k` est
le plus faible de ses deux maillons (`min`), et on retient la meilleure
option intermédiaire trouvée (`max`). C'est l'algorithme classique de plus
court chemin (Floyd–Warshall), appliqué à la force plutôt qu'à la distance.

Le vainqueur est l'option qui, une fois `p` calculée, tient tête à toutes les
autres :

```python
def _schulze_winners(
    p: Mapping[OptionId, Mapping[OptionId, int]], options: Sequence[OptionId]
) -> list[OptionId]:
    return [i for i in options if all(p[i][j] >= p[j][i] for j in options if j != i)]
```

Plus d'un élément dans cette liste signifie une égalité réelle : le cercle
symétrique décrit plus haut en est l'exemple. `winners[0] if len(winners) ==
1 else None` est alors ce que le résultat publié appelle `winner` ; les
options restées à égalité passent au [départage](#égalités-et-départage).

### Majoritaire et par assentiment (§8.2)

Les deux méthodes de comptage partagent une seule fonction, qui ne diffère
que sur ce qu'elle retient de chaque bulletin :

```python
def _tally_counted(
    ballots: Sequence[Ranking], options: Sequence[OptionId], method: Method
) -> TallyResult:
    counts: dict[OptionId, int] = dict.fromkeys(options, 0)
    for ranking in ballots:
        if not ranking:
            continue
        chosen = ranking[0] if method is Method.PLURALITY else [o for g in ranking for o in g]
        for option in chosen:
            if option in counts:
                counts[option] += 1
    best = max(counts.values()) if ballots else 0
    winners = [o for o in options if counts[o] == best] if ballots else []
    # … construit ensuite le TallyResult publié, omis ici
```

En **majoritaire**, `ranking[0]` est le premier groupe du classement — la ou
les options placées en tête ; en configuration ordinaire (sans ex æquo
autorisés), ce groupe ne contient qu'une seule option, la préférence unique
de l'électeur. En **par assentiment**, `[o for g in ranking for o in g]`
aplatit *tous* les groupes du bulletin en une seule liste : c'est ce qui
traduit « approuver plusieurs propositions à la fois » en interne — le
bulletin place toutes les options approuvées ensemble, sans les distinguer
par un rang.

### Départage (§8.3)

```python
def tiebreak_seed(opening_seed: bytes, closure_hash: bytes) -> bytes:
    return hashlib.sha256(opening_seed + closure_hash).digest()


def tiebreak_order(
    tied: Sequence[OptionId], opening_seed: bytes, closure_hash: bytes
) -> list[tuple[OptionId, bytes]]:
    seed = tiebreak_seed(opening_seed, closure_hash)
    drawn = [
        (option, hashlib.sha256(seed + str(option).encode("utf-8")).digest()) for option in tied
    ]
    drawn.sort(key=lambda pair: pair[1])
    return drawn


def break_tie(tied: Sequence[OptionId], opening_seed: bytes, closure_hash: bytes) -> OptionId:
    if not tied:
        raise ValueError("break_tie called with no tied options")
    return tiebreak_order(tied, opening_seed, closure_hash)[0][0]
```

Aucun générateur pseudo-aléatoire, aucune fonction de tri assortie d'une
graine : uniquement des hachages SHA-256, dont le résultat ne dépend ni du
langage, ni de la machine, ni de la version du logiciel qui les recalcule —
c'est précisément ce qui permet au [vérificateur
indépendant](verifier.md#en-cas-dégalité-départage), écrit dans un tout
autre langage, de retrouver le même départage.

## Pour aller plus loin

Le raisonnement complet d'un dépouillement donné — matrice des duels et,
pour Schulze, forces de chemin — est publié en clair avec chaque résultat, à
côté de la liste anonymisée des bulletins : voir la section « Vérifier, après
la clôture » du [guide de l'électeur](guide-electeur.md#8-vérifier-après-la-clôture).
Pour recalculer un résultat par vous-même, sans lire une ligne de code, voir
[Vérifier un résultat par vous-même](verifier.md). La spécification complète
de ces méthodes — algorithmes en pseudo-code, invariants, tests d'acceptation
— est à la section 8 de `spec-plateforme-vote.md`, dans le dépôt du projet.
