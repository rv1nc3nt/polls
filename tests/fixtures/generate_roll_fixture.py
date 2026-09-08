#!/usr/bin/env python3
"""
Generate a synthetic electoral-roll export for testing.

Reproduces the shape of a REU "Listes Electeurs Actifs" CSV export
(27 semicolon-separated columns, UTF-8, quoted fields, LF line endings,
unquoted empty fields) without containing any real personal data.

The commune, postcode and INSEE codes are deliberately impossible so the
file can never be mistaken for a real export.

Deterministic: same seed, same file.

Usage:  python3 tests/fixtures/generate_roll_fixture.py [--rows 60] [--seed 1] [--out FILE]
"""

# A standalone data script, not application or test code: correctness is checked
# by regenerating and byte-comparing against the committed roll-fixture.csv, and
# --strict annotations would only be noise here.
# mypy: ignore-errors

import argparse
import pathlib
import random
import unicodedata

DEFAULT_OUT = pathlib.Path(__file__).with_name("roll-fixture.csv")

COLUMNS = [
    "code du l'ugle",
    "libellé de l'ugle",
    "libellé du type de liste",
    "nom de naissance",
    "nom d'usage",
    "prénoms",
    "sexe",
    "date de naissance",
    "code commune de naissance",
    "libellé commune de naissance",
    "code département de naissance",
    "pays de naissance",
    "libellé nationalité",
    "numéro de voie",
    "libellé de voie",
    "complément 1",
    "complément 2",
    "lieu-dit",
    "code postal",
    "commune",
    "pays",
    "code du bureau de vote",
    "libellé du bureau de vote",
    "code circonscription législative du bureau de vote",
    "libellé canton du bureau de vote",
    "libellé circonscription métropolitaine du bureau de vote",
    "numéro d'ordre dans le bureau de vote",
]

UGLE_CODE, UGLE_LABEL = "99999", "SAINT-EXEMPLE-EN-FIXTURE"
POSTCODE = "99999"
# the commune's own name, spelled inconsistently, as real exports do
COMMUNE_SPELLINGS = [
    "SAINT EXEMPLE EN FIXTURE",
    "Saint-Exemple-en-Fixture",
    "ST EXEMPLE EN FIXTURE",
    "SAINT-EXEMPLE-EN-FIXTURE",
]

SURNAMES = [
    "ABADIE",
    "BALTHAZAR",
    "CARBONNEL",
    "DELAVIGNE",
    "ESCOFFIER",
    "FALGUIERE",
    "GRANDMOUGIN",
    "HAUTEFEUILLE",
    "IRIGARAY",
    "JOUBERT-VALLE",
    "KERGUELEN",
    "LAVOISIER",
    "MONTGOLFIER",
    "NOIRTIER",
    "ORSATTI",
    "PELLETANT",
    "QUENTIN-BRUYERE",
    "RAVANEL",
    "SOUBEYRAN",
    "TREMBLAY",
    "URBANI",
    "VAUCANSON",
    "WATTEBLED",
    "XAINTRAILLES",
    "YVERNAULT",
    "ZAMPIERI",
    "BRESSANDE",
    "CHANTEMERLE",
    "DAUVERGNE",
    "ENGILBERT",
    "FOUGEROLLE",
    "GRIVOLLET",
    "HUBERDEAU",
    "JASSERAND",
    "LOMBARDOT",
    "MAUFFREY",
    "NIVOLLET",
    "PERRACHON",
    "ROUSSILLE",
    "SAVOURNIN",
    "TOURNADRE",
    "VUILLERMOZ",
    "BOISSERAND",
    "CHAMPOLLION",
]
ODD_SURNAMES = [
    "DE LA ROCHEFOUCAULD",
    "LE BRETHON",
    "DU PLESSIS-MORNAY",
    "D'AUBIGNE",
    "SCHÖNBERGER",
    "TRAN VAN",
    "O'SULLIVAN",
    "SAINT-AMOUR",
    "VAN DER MEULEN",
    "ÉLÉONORE-BLIN",
]
M_FORENAMES = [
    "Aurélien",
    "Baptiste-Amaury",
    "Corentin",
    "Ewen",
    "Hilaire",
    "Isidore",
    "Joachim",
    "Kilian",
    "Ludovic",
    "Marceau",
    "Nathanaël",
    "Octave",
    "Prosper",
    "Raphaël",
    "Séverin",
    "Tanguy",
    "Ulysse",
    "Victorin",
    "Wilfried",
    "Zéphirin",
    "Barnabé",
    "Clovis",
    "Dorian",
    "Eloi",
    "Gontran",
    "Fulbert",
    "Amaury",
    "Ansgar",
]
F_FORENAMES = [
    "Apolline",
    "Capucine",
    "Eugénie",
    "Faustine",
    "Gwenaëlle",
    "Hortense",
    "Iseult",
    "Joséphine",
    "Léonie",
    "Maëlys",
    "Noémie",
    "Ombline",
    "Pénélope",
    "Quitterie",
    "Rosalie",
    "Sidonie",
    "Tiphaine",
    "Ursule",
    "Violaine",
    "Xavière",
    "Yolande",
    "Zélie",
    "Bérangère",
    "Clémence",
    "Domitille",
    "Églantine",
    "Armelle",
    "Solange",
]
STREETS = [
    "Rue du Cadran-Solaire",
    "Route des Charbonniers",
    "Chemin de la Sauge",
    "Place du Vieux-Pressoir",
    "Rue des Quatre-Vents",
    "Impasse du Colombier",
    "Route de la Ganterie",
    "Chemin des Corbeaux",
    "Allée des Sorbiers",
    "Rue du Pont-Levant",
]
HAMLETS = ["Le Serre-Bariol", "Les Granges-Neuves", "La Croix-Frimont", "Le Clos-Pigeon"]
BIRTH_FR = [
    ("75056", "PARIS", "75"),
    ("13055", "MARSEILLE", "13"),
    ("69123", "LYON", "69"),
    ("31555", "TOULOUSE", "31"),
    ("06088", "NICE", "06"),
    ("44109", "NANTES", "44"),
    ("34172", "MONTPELLIER", "34"),
    ("67482", "STRASBOURG", "67"),
    ("33063", "BORDEAUX", "33"),
    ("59350", "LILLE", "59"),
]
# inconsistent country spellings and a historic entity, as real exports contain
BIRTH_ABROAD = [
    ("", "BRUXELLES", "99", "BELGIQUE"),
    ("", "CASABLANCA", "99", "MAROC"),
    ("", "STUTTGART", "99", "ALLEMAGNE"),
    ("", "", "99", "U.R.S.S."),
    ("", "LISBOA", "99", "PORTUGAL"),
    ("", "LONDON", "99", "ROYAUME-UNI DE GRANDE-BRETAGNE ET D'IRLANDE"),
]

PRINCIPALE = "Liste principale"
COMP_MUN = "Liste complémentaire municipale"
COMP_EUR = "Liste complémentaire européenne"


def norm(s):
    s = unicodedata.normalize("NFKD", s.lower())
    return "".join(c for c in s if not unicodedata.combining(c))


class Builder:
    def __init__(self, rng):
        self.rng = rng
        self.rows = []
        self.order = 0

    def row(self, **kw):
        r = dict.fromkeys(COLUMNS, "")
        r["code du l'ugle"] = UGLE_CODE
        r["libellé de l'ugle"] = UGLE_LABEL
        r["libellé du type de liste"] = PRINCIPALE
        r["libellé nationalité"] = "Française"
        r["code postal"] = POSTCODE
        r["commune"] = self.rng.choice(COMMUNE_SPELLINGS)
        r["code du bureau de vote"] = "0001"
        r["libellé du bureau de vote"] = "Mairie"
        r["code circonscription législative du bureau de vote"] = "99-01"
        r["libellé canton du bureau de vote"] = "Canton de Fixture"
        self.order += 1
        r["numéro d'ordre dans le bureau de vote"] = str(self.order)
        # address
        r["numéro de voie"] = str(self.rng.randint(1, 90))
        r["libellé de voie"] = self.rng.choice(STREETS)
        if self.rng.random() < 0.12:
            r["lieu-dit"] = self.rng.choice(HAMLETS)
        if self.rng.random() < 0.20:
            r["pays"] = self.rng.choice(["FRANCE", "France"])
        # birthplace
        if self.rng.random() < 0.9:
            code, label, dept = self.rng.choice(BIRTH_FR)
            r["code commune de naissance"] = code
            r["libellé commune de naissance"] = label
            r["code département de naissance"] = dept
            r["pays de naissance"] = self.rng.choice(["FRANCE", "France"])
        else:
            code, label, dept, country = self.rng.choice(BIRTH_ABROAD)
            r["code commune de naissance"] = code
            r["libellé commune de naissance"] = label
            r["code département de naissance"] = dept
            r["pays de naissance"] = country
        r.update(kw)
        self.rows.append(r)
        return r

    def person(self, sex=None, surname=None, forenames=None, dob=None, **kw):
        sex = sex or self.rng.choice("MF")
        surname = surname or self.rng.choice(SURNAMES)
        if forenames is None:
            pool = M_FORENAMES if sex == "M" else F_FORENAMES
            n = self.rng.choice([1, 2, 2, 3, 3])
            forenames = " ".join(self.rng.sample(pool, n))
        dob = dob or (
            f"{self.rng.randint(1, 28):02d}/"
            f"{self.rng.randint(1, 12):02d}/"
            f"{self.rng.randint(1935, 2008)}"
        )
        if "nom d'usage" not in kw and sex == "F" and self.rng.random() < 0.35:
            other = self.rng.choice(SURNAMES)
            if other != surname:
                kw["nom d'usage"] = other
        return self.row(
            **{
                "nom de naissance": surname,
                "prénoms": forenames,
                "sexe": sex,
                "date de naissance": dob,
                **kw,
            }
        )


def build(rows_wanted, seed):
    rng = random.Random(seed)  # noqa: S311 — a reproducible fixture, not a security context
    b = Builder(rng)

    # --- deliberate edge cases, documented in tests/fixtures/README.md ---

    # 1. married name: nom d'usage differs from birth name
    b.person(
        sex="F",
        surname="DELAVIGNE",
        forenames="Apolline Capucine",
        dob="14/03/1962",
        **{"nom d'usage": "RAVANEL"},
    )
    # 2. nom d'usage identical to birth name (happens in real exports)
    b.person(
        sex="F",
        surname="SOUBEYRAN",
        forenames="Léonie",
        dob="02/11/1971",
        **{"nom d'usage": "SOUBEYRAN"},
    )
    # 3. father and son: same surname AND forenames, different dates
    b.person(sex="M", surname="ESCOFFIER", forenames="Marceau Prosper", dob="09/06/1948")
    b.person(sex="M", surname="ESCOFFIER", forenames="Marceau Prosper", dob="21/09/1979")
    # 4. true homonyms: same surname, forenames AND date of birth -> review queue
    b.person(sex="M", surname="NOIRTIER", forenames="Victorin", dob="30/04/1965")
    b.person(sex="M", surname="NOIRTIER", forenames="Victorin", dob="30/04/1965")
    # 5. same surname and date of birth, different forenames (twins)
    b.person(sex="F", surname="FOUGEROLLE", forenames="Sidonie", dob="17/07/1990")
    b.person(sex="F", surname="FOUGEROLLE", forenames="Violaine", dob="17/07/1990")
    # 6. awkward surnames: particles, apostrophe, diacritics, spaces, hyphens
    for s in ODD_SURNAMES:
        b.person(surname=s)
    # 7. four forenames, and hyphenated forenames
    b.person(
        sex="M", surname="VUILLERMOZ", forenames="Barnabé Clovis Isidore Ulysse", dob="05/02/1954"
    )
    b.person(sex="F", surname="TOURNADRE", forenames="Gwenaëlle-Rosalie", dob="28/08/1986")
    # 8. dates that do not parse as dd/mm/yyyy -> date_uncertain
    b.person(
        sex="M",
        surname="ORSATTI",
        forenames="Zéphirin",
        dob="00/00/1953",
        **{
            "pays de naissance": "ESPAGNE",
            "libellé commune de naissance": "MADRID",
            "code commune de naissance": "",
            "code département de naissance": "99",
        },
    )
    b.person(
        sex="F",
        surname="TRAN VAN",
        forenames="Quitterie",
        dob="1961",
        **{
            "pays de naissance": "VIET NAM",
            "libellé commune de naissance": "",
            "code commune de naissance": "",
            "code département de naissance": "99",
        },
    )
    # 9. EU nationals: one on BOTH complementary lists (must collapse to one
    #    person), one on the European list only (ineligible for a municipal poll)
    for surname, forenames, sex, dob, nat in [
        ("SCHÖNBERGER", "Ombline", "F", "12/05/1975", "Allemande"),
        ("VAN DER MEULEN", "Gontran", "M", "23/10/1968", "Belge"),
    ]:
        common = {
            "nom de naissance": surname,
            "prénoms": forenames,
            "sexe": sex,
            "date de naissance": dob,
            "libellé nationalité": nat,
            "code commune de naissance": "",
            "code département de naissance": "99",
            "libellé commune de naissance": "BERLIN" if nat == "Allemande" else "ANTWERPEN",
            "pays de naissance": "ALLEMAGNE" if nat == "Allemande" else "BELGIQUE",
        }
        b.row(**{**common, "libellé du type de liste": COMP_MUN})
        b.row(**{**common, "libellé du type de liste": COMP_EUR})
    b.person(
        sex="F",
        surname="ZAMPIERI",
        forenames="Églantine",
        dob="08/01/1983",
        **{
            "libellé du type de liste": COMP_EUR,
            "libellé nationalité": "Italienne",
            "libellé commune de naissance": "TORINO",
            "code commune de naissance": "",
            "code département de naissance": "99",
            "pays de naissance": "ITALIE",
        },
    )
    # 10. incomplete rows: no polling station; no street number; only a hamlet
    b.person(
        **{
            "code du bureau de vote": "",
            "libellé du bureau de vote": "",
            "code circonscription législative du bureau de vote": "",
            "libellé canton du bureau de vote": "",
            "numéro d'ordre dans le bureau de vote": "",
        }
    )
    b.person(**{"numéro de voie": ""})
    b.person(**{"numéro de voie": "", "libellé de voie": "", "lieu-dit": rng.choice(HAMLETS)})
    # 11. address complements, rarely filled in real exports
    b.person(**{"complément 1": "Bâtiment B"})
    b.person(**{"complément 2": "Appartement 3"})

    # --- filler, avoiding accidental collisions with the cases above ---
    seen = {
        (norm(r["nom de naissance"]), norm(r["prénoms"]), r["date de naissance"]) for r in b.rows
    }
    while len(b.rows) < rows_wanted:
        r = b.person()
        key = (norm(r["nom de naissance"]), norm(r["prénoms"]), r["date de naissance"])
        if key in seen:
            b.rows.pop()
            b.order -= 1
            continue
        seen.add(key)

    # duplicate one order number, as observed in a real export
    if len(b.rows) > 3:
        b.rows[-1]["numéro d'ordre dans le bureau de vote"] = b.rows[-2][
            "numéro d'ordre dans le bureau de vote"
        ]
    return b.rows


def write(rows, path):
    last = COLUMNS[-1]

    def field(col, v):
        if v == "":
            return ""
        # the export quotes every field except the trailing order number
        return v if col == last else f'"{v}"'

    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(";".join(f'"{c}"' for c in COLUMNS) + "\n")
        for r in rows:
            f.write(";".join(field(c, r[c]) for c in COLUMNS) + "\n")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", type=int, default=60)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    a = ap.parse_args()
    rows = build(a.rows, a.seed)
    write(rows, a.out)
    print(f"{len(rows)} rows written to {a.out}")
