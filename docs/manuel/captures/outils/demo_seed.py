"""Seed a realistic demo instance for documentation screenshots. Dev DB only."""
from __future__ import annotations

import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
django.setup()

from datetime import timedelta

from django.utils import timezone

from apps.backoffice import accounts, firstrun
from apps.core.models import PollRole, Role, User
from apps.elections.models import (
    Poll,
    PollOption,
    TallyMethod,
    WorkingRollEntry,
)
from apps.elections.transitions import announce_poll, open_poll
from apps.registrations import services as reg
from apps.registrations.models import Registration, RegistrationState
from apps.ballots import services as bal

PW = "correction-cheval-agrafe-2026"

# ---------------------------------------------------------------- first run
if firstrun.is_open():
    admin = firstrun.install(
        commune_name="Commune de Saint-Aubin-des-Bois",
        data_protection_referent="Secrétariat général de la mairie",
        data_protection_contact="dpo@saint-aubin-des-bois.fr — 12 place de la Mairie, 28300",
        username="m.rousseau",
        full_name="Marie Rousseau",
        raw_password=PW,
    )
else:
    admin = User.objects.get(username="m.rousseau")

def op(username: str, full_name: str) -> User:
    u = User.objects.filter(username=username).first()
    if u is None:
        u = accounts.create_account(
            username=username, full_name=full_name, raw_password=PW, is_commune_admin=False
        )
    return u

poll_admin = op("j.mercier", "Jean Mercier")
operator = op("s.blanchard", "Sophie Blanchard")
auditor = op("a.klein", "André Klein")

# ---------------------------------------------------------------- working roll
WorkingRollEntry.objects.all().delete()
ROLL = [
    ("Lefèvre", "Camille", "1902", "14/03/1962", ["principale"]),
    ("Nguyen", "Thi Lan", "", "07/11/1985", ["principale", "complementaire_municipale"]),
    ("Da Silva", "João Pedro", "", "22/07/1978", ["principale"]),
    ("Bouchard", "Michel", "", "30/09/1954", ["principale"]),
    ("Andriamahefa", "Noro", "", "1971 (date incomplète)", ["principale"]),
    ("Petit", "Élodie", "Petit-Durand", "03/01/1990", ["principale", "complementaire_municipale"]),
    ("Kowalski", "Piotr", "", "19/05/1969", ["complementaire_europeenne"]),
    ("Garnier", "Hélène", "", "28/02/1948", ["principale"]),
    ("Traoré", "Aminata", "", "11/08/1996", ["principale"]),
    ("Meyer", "Lucas", "", "05/12/1982", ["principale"]),
]
for birth, first, usual, dob, lists in ROLL:
    parsed = None
    uncertain = False
    try:
        d, m, y = dob.split("/")
        from datetime import date

        parsed = date(int(y), int(m), int(d))
    except ValueError:
        uncertain = True
    WorkingRollEntry.objects.create(
        birth_name=birth,
        usual_name=usual,
        first_names=first,
        date_of_birth=dob,
        date_of_birth_parsed=parsed,
        date_uncertain=uncertain,
        list_types=lists,
    )

now = timezone.now()

# ---------------------------------------------------------------- open poll
poll = Poll.objects.filter(title_i18n__fr__startswith="Réaménagement").first()
if poll is None:
    poll = Poll.objects.create(
        title_i18n={"fr": "Réaménagement de la place de la Mairie"},
        description_i18n={
            "fr": "Le conseil municipal soumet trois scénarios d'aménagement de la place "
            "de la Mairie et de ses abords. Les électeurs sont invités à les classer "
            "par ordre de préférence. Cette consultation est à titre consultatif : "
            "elle éclaire la décision du conseil sans la lier."
        },
        languages=["fr"],
        opens_at=now - timedelta(days=3),
        closes_at=now + timedelta(days=11),
        paper_entry_deadline=now + timedelta(days=12),
        tally_method=TallyMethod.SCHULZE,
        require_complete_ranking=True,
        allow_ties_in_ballot=False,
        allow_ballot_modification=True,
        show_live_participation=False,
    )
    for pos, (oid, label) in enumerate(
        [
            ("mineral", "Scénario A — place minérale et ombrières"),
            ("jardin", "Scénario B — jardin planté et noue paysagère"),
            ("mixte", "Scénario C — solution mixte, kiosque conservé"),
        ]
    ):
        PollOption.objects.create(
            poll=poll, option_id=oid, label_i18n={"fr": label}, position=pos
        )
    open_poll(poll)
    poll.refresh_from_db()

for role, u in [
    (Role.POLL_ADMIN, poll_admin),
    (Role.ENTRY_OPERATOR, operator),
    (Role.AUDITOR, auditor),
]:
    PollRole.objects.get_or_create(
        poll=poll, user=u, role=role, defaults={"granted_by": admin}
    )

# ---------------------------------------------------------------- draft poll
if not Poll.objects.filter(title_i18n__fr__startswith="Nom de la").exists():
    draft = Poll.objects.create(
        title_i18n={"fr": "Nom de la future salle des fêtes"},
        description_i18n={"fr": "Choix du nom de l'équipement en cours de construction rue des Écoles."},
        languages=["fr"],
        opens_at=now + timedelta(days=20),
        closes_at=now + timedelta(days=34),
        paper_entry_deadline=now + timedelta(days=34),
        tally_method=TallyMethod.PLURALITY,
        require_complete_ranking=False,
        allow_ballot_modification=False,
    )
    for pos, (oid, label) in enumerate(
        [("hugo", "Salle Victor-Hugo"), ("marie-curie", "Salle Marie-Curie"), ("tilleuls", "Salle des Tilleuls")]
    ):
        PollOption.objects.create(poll=draft, option_id=oid, label_i18n={"fr": label}, position=pos)
    PollRole.objects.get_or_create(poll=draft, user=poll_admin, role=Role.POLL_ADMIN, defaults={"granted_by": admin})

# ---------------------------------------------------------------- announced poll
if not Poll.objects.filter(title_i18n__fr__startswith="Tracé de la future piste cyclable").exists():
    announced = Poll.objects.create(
        title_i18n={"fr": "Tracé de la future piste cyclable"},
        description_i18n={
            "fr": "Deux tracés sont à l'étude pour relier le centre-bourg à la zone "
            "d'activités. Consultation à titre consultatif ; l'ouverture du vote "
            "est prévue dans un mois, le temps que chacun prenne connaissance "
            "des deux options."
        },
        languages=["fr"],
        opens_at=now + timedelta(days=30),
        closes_at=now + timedelta(days=44),
        paper_entry_deadline=now + timedelta(days=44),
        tally_method=TallyMethod.PLURALITY,
        require_complete_ranking=False,
        allow_ballot_modification=True,
    )
    for pos, (oid, label) in enumerate(
        [
            ("nord", "Tracé nord — le long de la voie ferrée"),
            ("sud", "Tracé sud — par la coulée verte"),
        ]
    ):
        PollOption.objects.create(poll=announced, option_id=oid, label_i18n={"fr": label}, position=pos)
    PollRole.objects.get_or_create(
        poll=announced, user=poll_admin, role=Role.POLL_ADMIN, defaults={"granted_by": admin}
    )
    announce_poll(announced, actor=poll_admin)
    announced.refresh_from_db()

# ---------------------------------------------------------- open poll past its deadline
# Demonstrates screen 2's manual *clôturer maintenant* (R-2.1): a poll whose
# paper_entry_deadline has already passed but which the scheduler has not yet
# closed — exactly the "may run late" case §4 describes. closes_at and
# paper_entry_deadline are the two fields that stay mutable once a poll is no
# longer draft (R-3.4), so they are set directly after opening rather than
# through the (not-yet-implemented-here) reasoned extension flow.
if not Poll.objects.filter(title_i18n__fr__startswith="Aire de jeux du parc").exists():
    late = Poll.objects.create(
        title_i18n={"fr": "Aire de jeux du parc des Tilleuls"},
        description_i18n={
            "fr": "Choix du type d'équipement pour la nouvelle aire de jeux du parc des Tilleuls."
        },
        languages=["fr"],
        opens_at=now - timedelta(days=15),
        closes_at=now + timedelta(days=1),
        paper_entry_deadline=now + timedelta(days=1),
        tally_method=TallyMethod.APPROVAL,
    )
    for pos, (oid, label) in enumerate(
        [
            ("toboggan", "Structure avec toboggan"),
            ("grimpe", "Structure d'escalade"),
            ("mixte", "Structure mixte"),
        ]
    ):
        PollOption.objects.create(poll=late, option_id=oid, label_i18n={"fr": label}, position=pos)
    open_poll(late)
    late.refresh_from_db()
    late.closes_at = now - timedelta(hours=2)
    late.paper_entry_deadline = now - timedelta(hours=2)
    late.save()
    PollRole.objects.get_or_create(
        poll=late, user=poll_admin, role=Role.POLL_ADMIN, defaults={"granted_by": admin}
    )

# ---------------------------------------------------------------- registrations + ballots
def register_and_vote(last, first, dob, email, ranking=None, confirm=True):
    if Registration.objects.filter(poll=poll, email_canonical=email.lower()).exists():
        return
    try:
        registration, token = reg.register(
            poll,
            {
                "last_name": last,
                "first_names": first,
                "date_of_birth": dob,
                "email": email,
                "declared_on_honour": "on",
            },
            "fr",
        )
    except reg.RegistrationRefused as exc:
        print("refused", email, exc)
        return
    if token is None:
        print("review", email)
        return
    if confirm:
        reg.confirm_mailbox(registration)
    if ranking is not None:
        bal.cast_online(poll, token, ranking)


register_and_vote("Lefèvre", "Camille", "14/03/1962", "camille.lefevre@example.fr",
                  [["jardin"], ["mixte"], ["mineral"]])
register_and_vote("Nguyen", "Thi Lan", "07/11/1985", "tl.nguyen@example.fr",
                  [["mixte"], ["jardin"], ["mineral"]])
register_and_vote("Da Silva", "João Pedro", "22/07/1978", "jp.dasilva@example.fr",
                  [["jardin"], ["mineral"], ["mixte"]])
register_and_vote("Bouchard", "Michel", "30/09/1954", "m.bouchard@example.fr",
                  [["mineral"], ["mixte"], ["jardin"]])
# confirmed, not yet voted
register_and_vote("Garnier", "Hélène", "28/02/1948", "h.garnier@example.fr", None, confirm=True)
# registered, mailbox not confirmed
register_and_vote("Meyer", "Lucas", "05/12/1982", "l.meyer@example.fr", None, confirm=False)
# no match -> review queue
register_and_vote("Dubois", "Marc", "17/06/1975", "marc.dubois@example.fr", None, confirm=False)

# ---------------------------------------------------------------- paper ballot
entry = poll.roll_entries.filter(birth_name="Traoré").first()
if entry and not entry.paper_links.exists():
    bal.enter_paper(
        poll,
        str(entry.pk),
        [["mixte"], ["jardin"], ["mineral"]],
        str(operator.pk),
        "fr",
        identity_confirmed=True,
    )

# ---------------------------------------------------------------- published poll
from apps.elections.transitions import close_poll, publish_poll
from apps.elections.models import PollState

pub = Poll.objects.filter(title_i18n__fr__startswith="Horaires").first()
if pub is None:
    pub = Poll.objects.create(
        title_i18n={"fr": "Horaires d'ouverture de la médiathèque municipale"},
        description_i18n={
            "fr": "Trois grilles horaires sont proposées pour la médiathèque à compter "
            "de janvier. Consultation à titre consultatif."
        },
        languages=["fr"],
        opens_at=now - timedelta(days=30),
        closes_at=now - timedelta(days=1),
        paper_entry_deadline=now - timedelta(days=1),
        tally_method=TallyMethod.SCHULZE,
        require_complete_ranking=True,
    )
    for pos, (oid, label) in enumerate(
        [
            ("soir", "Grille 1 — nocturne le jeudi jusqu'à 20 h"),
            ("midi", "Grille 2 — ouverture continue le midi"),
            ("dimanche", "Grille 3 — ouverture le dimanche matin"),
        ]
    ):
        PollOption.objects.create(poll=pub, option_id=oid, label_i18n={"fr": label}, position=pos)
    # window still open at this point (closes_at moved below after casting)
    pub.closes_at = now + timedelta(days=1)
    pub.paper_entry_deadline = now + timedelta(days=1)
    pub.save()
    open_poll(pub)
    pub.refresh_from_db()
    PollRole.objects.get_or_create(poll=pub, user=poll_admin, role=Role.POLL_ADMIN, defaults={"granted_by": admin})

    votes = [
        ("Lefèvre", "Camille", "14/03/1962", "cl@example.fr", [["soir"], ["midi"], ["dimanche"]]),
        ("Nguyen", "Thi Lan", "07/11/1985", "n@example.fr", [["soir"], ["dimanche"], ["midi"]]),
        ("Da Silva", "João Pedro", "22/07/1978", "d@example.fr", [["midi"], ["soir"], ["dimanche"]]),
        ("Bouchard", "Michel", "30/09/1954", "b@example.fr", [["soir"], ["midi"], ["dimanche"]]),
        ("Garnier", "Hélène", "28/02/1948", "g@example.fr", [["dimanche"], ["soir"], ["midi"]]),
        ("Petit", "Élodie", "03/01/1990", "p@example.fr", [["soir"], ["midi"], ["dimanche"]]),
        ("Meyer", "Lucas", "05/12/1982", "m@example.fr", [["midi"], ["dimanche"], ["soir"]]),
    ]
    for last, first, dob, email, ranking in votes:
        registration, token = reg.register(
            pub,
            {"last_name": last, "first_names": first, "date_of_birth": dob,
             "email": email, "declared_on_honour": "on"},
            "fr",
        )
        reg.confirm_mailbox(registration)
        bal.cast_online(pub, token, ranking)

    close_poll(pub, actor=poll_admin)
    pub.refresh_from_db()
    publish_poll(pub, actor=poll_admin)
    pub.refresh_from_db()

print("OK")
print("poll id:", poll.pk)
for p in Poll.objects.all():
    print(" ", p.state, p.pk, p.title())
