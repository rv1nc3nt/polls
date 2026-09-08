# Test fixture — synthetic electoral roll

`roll-fixture.csv` is a synthetic export reproducing the shape of a REU
*Listes Electeurs Actifs* CSV. It contains **no real personal data**. The
commune, its INSEE code and its postcode are deliberately impossible
(`99999`, `SAINT-EXEMPLE-EN-FIXTURE`) so the file cannot be mistaken for a
real export.

A real roll export is the personal data of every elector in a commune and
must never enter this repository, the test suite, or a bug report.

All surnames, forenames, street names, hamlets and the commune name are
invented and were checked against a real export to ensure none of them
occurs in it. Only country names are shared with real data, and places of
birth are drawn from the ten largest French cities plus a handful of major
foreign ones — neither identifies anybody.

## Format

27 semicolon-separated columns, UTF-8 without BOM, LF line endings, every
field quoted **except** the trailing `numéro d'ordre dans le bureau de vote`,
which the real export leaves unquoted. Empty fields are written as nothing
between two separators, not as `""`. A parser that assumes uniform quoting
will fail on the real file and must fail on this one too.

## Regenerating

```
python3 tests/fixtures/generate_roll_fixture.py --rows 60 --seed 1
```

Deterministic: the same seed produces the same file. Raise `--rows` for a
larger roll; the edge cases below are always present regardless of size.

## What each case exercises

| Case in the file | Exercises |
|---|---|
| `nom d'usage` differing from the birth surname (~15 rows) | matching must try both; a registrant may type either |
| `nom d'usage` identical to the birth surname | the redundant case, which real exports contain |
| `nom d'usage` empty (majority of rows) | absence is the normal case, not an anomaly |
| Same surname *and* forenames, two different dates of birth | father and son; the date is what separates them |
| Same surname, forenames **and** date of birth (`NOIRTIER Victorin`) | genuine homonyms — must route to the review queue, never auto-match |
| Same surname and date of birth, different forenames | twins; forenames must participate in matching |
| `DE LA ROCHEFOUCAULD`, `LE BRETHON`, `DU PLESSIS-MORNAY`, `D'AUBIGNE`, `O'SULLIVAN`, `VAN DER MEULEN` | particles, apostrophes, internal spaces |
| `SCHÖNBERGER`, `ÉLÉONORE-BLIN`, forenames with accents | NFKD normalisation and diacritic stripping |
| Four forenames; hyphenated forenames (`Gwenaëlle-Rosalie`, `Baptiste-Amaury`) | forename tokenisation and order-insensitive comparison |
| `00/00/1953` and `1961` in the date column | unparseable and partial dates: import must succeed, flag `date_uncertain`, and route the registration to review |
| Two EU nationals each appearing on **both** complementary lists | person collapsing — one roll entry with two list types, or that elector registers twice |
| One elector on the European complementary list **only** | eligibility filtering: no standing on a municipal question |
| A row with no polling station, constituency, canton or order number | incomplete rows must import, not abort |
| A row with no street number; a row with only a hamlet | address completeness for postal enrolment |
| `complément 1` / `complément 2` filled on single rows | rarely-populated columns |
| The commune's own name in four different spellings | the source is free text; do not key on it |
| Both `FRANCE` and `France` in the birth-country column | inconsistent casing in the source |
| `U.R.S.S.` as a country of birth | historic entities; another reason not to match on birthplace |
| A duplicated `numéro d'ordre` | the order number is not unique and is renumbered on every roll change |

## Expected import outcome

With `eligible_list_types = [principale, complémentaire municipale]`:

- 60 rows in, 58 roll entries out (two electors collapsed across list types).
- 57 entries eligible; one (European list only) ineligible.
- 2 entries flagged `date_uncertain`.
- 1 pair of entries indistinguishable on name and date of birth, which no
  automatic match may resolve.
