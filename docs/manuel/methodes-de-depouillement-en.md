<!-- SPDX-License-Identifier: 0BSD -->

# Tally methods, explained

This document explains, with no maths prerequisite, the three tally methods
the platform offers — **Schulze**, **plurality** and **approval** — and the
rule applied when two propositions remain tied. It is for **anyone** who
wants to understand how a published result was reached: a curious voter, an
elected official or staff member configuring a poll, or anyone recomputing a
result on their own.

Each method is first explained in plain terms, with a worked example; the
last part, [«Deep dive: the code»](#deep-dive-the-code), shows the exact
source code that implements it, for whoever wants to go beyond the
intuition. The two parts answer each other: the worked examples are
recomputed there.

## In brief

| Method | What the ballot carries | Who wins |
|---|---|---|
| **Schulze** | a ranking of preferences, complete or not | the option that beats every other, directly or through the strongest chain of preferences, in a head-to-head duel |
| **Plurality** | a single choice | the option chosen first by the largest number |
| **Approval** | a set of approved options, unordered | the option approved by the largest number |

All three are **pure functions**: given the same ballots, they always give
the same result, recomputable by anyone from the published data alone — see
[Verify a result yourself](verifier.md). A given poll uses only **one** of
them, fixed at configuration and published with the result; this document
presents all three so the difference is understood, not to suggest one could
be picked after the fact.

A method can sometimes fail to separate two propositions: see [«Ties and the
tie-break»](#ties-and-the-tie-break) below.

## The Schulze method

Use this method as soon as a poll has **more than two** propositions and you
want to collect an **order of preference**, not just a single choice — "which
project first, which second…". Each voter ranks the propositions; the
ranking may be incomplete or contain ties if the poll's configuration allows
it (unranked propositions then count as tied in last place).

The idea: treat each ballot's ranking as a series of **duels**. A ballot that
ranks *Shared garden* above *Playground* is one vote for *Shared garden* in
the duel between the two. This is counted for every pair of propositions:
how many ballots prefer one to the other. The proposition that wins every one
of its duels — directly, or by resting on a chain of victories stronger than
its opponent's — wins the poll.

### Example

A commune consults residents on how to develop a plot of land: *Shared
garden*, *Playground* or *Car park*. Five ballots are cast:

| Ballot | 1st | 2nd | 3rd |
|---|---|---|---|
| 1 | Garden | Playground | Car park |
| 2 | Garden | Playground | Car park |
| 3 | Playground | Car park | Garden |
| 4 | Car park | Playground | Garden |
| 5 | Playground | Garden | Car park |

**First duel: Garden versus Playground.** Garden is preferred on ballots 1
and 2 (2 votes); Playground on ballots 3, 4 and 5 (3 votes). Playground wins
this duel, 3 votes to 2.

**Second duel: Garden versus Car park.** Garden wins on 1, 2 and 5 (3
votes); Car park on 3 and 4 (2 votes). Garden wins this duel, 3 votes to 2.

**Third duel: Playground versus Car park.** Playground wins on 1, 2, 3 and 5
(4 votes); Car park only on 4 (1 vote). Playground wins this duel, 4 votes
to 1.

*Playground* wins both of its duels directly — against *Garden* and against
*Car park* — and so wins the poll outright, without even needing to reason
about indirect chains: here, the option that beats every other in a direct
duel (called a "Condorcet winner") exists, and Schulze always picks it.

### When a chain of victories matters

The result is not always this simple: three propositions can beat one
another in a circle — *A* beats *B*, *B* beats *C*, *C* beats *A* — with none
of them beating the other two directly. This is where Schulze compares each
option's **strongest chain of victories** to every other, not just the
direct duel: if *A* does not beat *C* directly but beats *B* by a wider
margin than the one by which *C* beats *A*, the chain *A → B → C* can
outweigh the direct duel *C → A*. This is exactly what the [source
code](#schulze) below computes. A perfectly symmetric circle — the same
number of ballots for *A > B > C*, for *B > C > A* and for *C > A > B* —
leaves no chain stronger than any other: Schulze then reports a genuine tie,
settled by the [tie-break](#ties-and-the-tie-break).

## Plurality voting

This is the classic single-round vote: each ballot carries a **single
choice**, and the option chosen by the largest number wins. No ranking, no
notion of a second preference.

### Example

Take the same five ballots as above, but keep only each one's **first
preference** — that is all a plurality poll asks of a voter:

| Proposition | Votes |
|---|---|
| Garden (ballots 1, 2) | 2 |
| Playground (ballots 3, 5) | 2 |
| Car park (ballot 4) | 1 |

On almost the same ballots, the result changes: *Garden* and *Playground*
are now **tied** at two votes each, where Schulze picked *Playground*
unambiguously. This is not a quirk of the example: it is exactly why the
method is chosen *before* the poll, at configuration, and stays frozen
afterwards — switching method afterwards would change the result on the
same ballots.

> **Configuration trap.** If a poll both allows ties on a ballot *and* uses
> the plurality method, a voter who places several propositions tied in
> first place gives a vote to **each** of them — almost always unintended
> for a single-choice question. The mairie-area configuration screen warns
> in this case.

## Approval voting

Here, the ballot ranks nothing: the voter **approves** as many propositions
as they wish, in no particular order — "tick every one that suits you". Each
approved proposition gets one vote; the proposition approved by the largest
number of voters wins. A voter may approve a single proposition, all of
them, or none.

### Example

Same consultation, but voters tick freely whatever suits them instead of
ranking:

| Voter | Approves |
|---|---|
| 1 | Garden, Playground |
| 2 | Garden, Playground |
| 3 | Playground, Car park |
| 4 | Car park |
| 5 | Playground |

*Playground* is approved by voters 1, 2, 3 and 5 — 4 votes — against 3 for
*Garden* (1, 2) and 2 for *Car park* (3, 4). *Playground* wins, with no tie
this time.

This method suits a question of the "which of these options would you
accept?" kind, where forcing a complete ranking would produce information
the voter does not really have.

## Ties and the tie-break

All three methods can leave a **genuine tie**: two or more options level on
votes (plurality, approval), or two or more that no chain of preferences
separates (Schulze — see the circle example above). When this happens, the
poll's own **tie-break rule** applies. Two rules exist:

**Computed drawing of lots (the default).** A deterministic computation,
neither generated by the programming language's own randomness nor
predictable before the poll closes:

1. an **opening seed** is drawn when the poll opens and published at once;
2. at closure, the **closure hash** — which depends on the entire set of
   ballots cast — is computed and published;
3. the **tie-break seed** is the SHA-256 hash of the opening seed followed
   by the closure hash;
4. each tied option is ordered by the SHA-256 hash of this seed followed by
   its own identifier; the smallest value wins.

Because the tie-break seed depends on the closure hash, and therefore on
every ballot cast, the outcome is known to no one — not even the mairie —
before the last ballot has been counted, and it is recomputable by anyone
from the published values alone: this is exactly what the `--opening-seed`
option of the [independent verifier](verifier.md#in-case-of-a-tie-tie-break)
checks.

**Physical drawing of lots.** A poll may instead be configured to use a
drawing of lots conducted publicly (at the mairie, before witnesses) rather
than computed. Its outcome is then entered by a poll admin at closure and
recorded in the publication like everything else.

## Deep dive: the code

This part shows the exact source code that computes each of the results
above — `src/apps/tally/methods.py` and `src/apps/tally/tiebreak.py`. The
tally is a pure function: no database read, no clock, no
randomness beyond the drawing of lots described above; it can be read, like
what follows, with no knowledge of the rest of the application.

### Schulze

The duel matrix — `d[i][j]`, the number of ballots ranking `i` strictly
above `j` — is built like this (a ballot's unranked options count as tied in
last place):

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

On the example above, this function produces exactly the three duels
counted by hand: `d["playground"]["garden"] == 3`,
`d["garden"]["playground"] == 2`, and so on.

The path strengths — the "strongest chain of victories" mentioned above —
are then computed from `d`:

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

`p` starts from the direct duels (`p[i][j] = d[i][j]` if `i` beats `j`, else
0), then the triple loop tries, for every pair `(j, k)`, to do better by
passing through an intermediate option `i`: the strength of the chain
`j → i → k` is the weaker of its two links (`min`), and the best
intermediate option found is kept (`max`). This is the classic
shortest-path algorithm (Floyd–Warshall), applied to strength rather than
distance.

The winner is whichever option, once `p` is computed, holds its own against
every other:

```python
def _schulze_winners(
    p: Mapping[OptionId, Mapping[OptionId, int]], options: Sequence[OptionId]
) -> list[OptionId]:
    return [i for i in options if all(p[i][j] >= p[j][i] for j in options if j != i)]
```

More than one entry in this list means a genuine tie: the symmetric circle
described above is an example. `winners[0] if len(winners) == 1 else None`
is then what the published result calls `winner`; the options left tied
move on to the [tie-break](#ties-and-the-tie-break).

### Plurality and approval

The two counting methods share a single function, which differs only in
what it keeps from each ballot:

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
    # … goes on to build the published TallyResult, omitted here
```

Under **plurality**, `ranking[0]` is the ranking's first group — the option
or options placed first; under ordinary configuration (no ties allowed),
this group holds exactly one option, the voter's single preference. Under
**approval**, `[o for g in ranking for o in g]` flattens *every* group of
the ballot into a single list: this is how "approving several propositions
at once" is represented internally — the ballot places every approved
option together, with no rank distinguishing them.

### The tie-break

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

No pseudo-random generator, no sort keyed by a seed: only SHA-256 hashes,
whose result depends on neither the language, nor the machine, nor the
version of the software recomputing them — this is exactly what lets the
[independent verifier](verifier.md#in-case-of-a-tie-tie-break), written
in an entirely different language, arrive at the same tie-break.

## Going further

The full reasoning behind a given tally — the duel matrix and, for Schulze,
the path strengths — is published in the clear with every result, next to
the anonymised ballot list: see the "Verify, after closure" section of the
[voter's guide](guide-electeur.md#8-verify-after-closure). To recompute a
result yourself without reading a line of code, see [Verify a result
yourself](verifier.md).
