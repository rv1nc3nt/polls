"""Render the real screens to self-contained HTML captures under docs/captures/.

No browser is available in this environment to rasterise them; each file is the
genuine page markup with the stylesheet inlined, so it opens stand-alone and can
be turned into a PNG with one command on any machine with a browser:

    chromium --headless --screenshot=01.png --window-size=1280,1600 01-*.html
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
django.setup()

from django.test import Client

from apps.core.models import User
from apps.elections.models import Poll, PollState
from apps.registrations import services as reg
from apps.registrations.models import Channel, Registration, RegistrationState

ROOT = Path("/home/claude/Projects/polls")
OUT = ROOT / "docs" / "manuel" / "captures"
OUT.mkdir(parents=True, exist_ok=True)
CSS = (ROOT / "src" / "static" / "css" / "app.css").read_text(encoding="utf-8")
TABS_JS = (ROOT / "src" / "static" / "js" / "tabs.js").read_text(encoding="utf-8")
OPTION_EDITOR_JS = (ROOT / "src" / "static" / "js" / "option-editor.js").read_text(encoding="utf-8")

poll = Poll.objects.get(title_i18n__fr__startswith="Réaménagement")
draft = Poll.objects.get(state=PollState.DRAFT)
pub = Poll.objects.get(state=PollState.PUBLISHED)
admin = User.objects.get(username="m.rousseau")
padmin = User.objects.get(username="j.mercier")
operator = User.objects.get(username="s.blanchard")
auditor = User.objects.get(username="a.klein")

paper_ballot = poll.ballots.filter(source="paper").first()
review_reg = Registration.objects.filter(poll=poll, state=RegistrationState.PENDING_REVIEW).first()


def save(name: str, html: str) -> None:
    html = re.sub(
        r'<link rel="stylesheet" href="[^"]*app\.css[^"]*">',
        f"<style>\n{CSS}\n</style>",
        html,
    )
    # The theme toggle is progressive enhancement (static/js/theme.js); a
    # stand-alone capture has no server to load it from and does not need it —
    # the control stays hidden and the OS theme drives the page, as designed.
    html = re.sub(r'\s*<script src="[^"]*theme\.js[^"]*"></script>', "", html)
    # tabs.js and option-editor.js are *not* dropped the same way: screen 2's
    # configuration editor (13-mairie-configuration-brouillon) is the tabbed
    # view, and the capture should show what an operator actually sees, not
    # the no-JS fallback of every fieldset stacked open. A root-relative
    # `<script src="/static/...">` 404s under `file://`, so inline both in
    # place — same treatment as app.css above.
    # (lambda replacements: the JS source has backslashes re.sub would
    # otherwise read as backreferences)
    html = re.sub(
        r'<script src="[^"]*\btabs\.js[^"]*" defer></script>', lambda _: f"<script>\n{TABS_JS}\n</script>", html
    )
    html = re.sub(
        r'<script src="[^"]*\boption-editor\.js[^"]*" defer></script>',
        lambda _: f"<script>\n{OPTION_EDITOR_JS}\n</script>",
        html,
    )
    # Drop `autofocus` (login username, paper-entry search): the headless render
    # would freeze that field focused, drawing a :focus-visible ring on one
    # control and making the form look lopsided. A capture shows the resting
    # state.
    html = re.sub(r"\s+autofocus(?=[\s/>])", "", html)
    (OUT / name).write_text(html, encoding="utf-8")
    print("  ", name, len(html))


def get(client: Client, url: str, name: str) -> str:
    resp = client.get(url, follow=True, SERVER_NAME="localhost")
    body = resp.content.decode("utf-8")
    if resp.status_code != 200:
        print("  !! ", url, resp.status_code)
    save(name, body)
    return body


anon = Client()
get(anon, "/fr/", "01-site-public-liste.html")
get(anon, f"/fr/scrutin/{poll.pk}/", "02-site-public-scrutin.html")
get(anon, f"/fr/inscription/{poll.pk}/", "03-inscription-formulaire.html")
get(anon, f"/fr/inscription/{poll.pk}/recu/pending_email/", "04-inscription-confirmee.html")
get(anon, f"/fr/inscription/{poll.pk}/recu/pending_review/", "05-inscription-en-examen.html")
get(anon, f"/fr/scrutin/{pub.pk}/resultats/", "20-site-public-resultats.html")
get(anon, "/fr/mairie/connexion/", "06-mairie-connexion.html")

# --- announced poll: public preview, no registration nor vote (R-3.10) ------
announced = Poll.objects.get(title_i18n__fr__startswith="Tracé de la future piste cyclable")
get(anon, f"/fr/scrutin/{announced.pk}/", "02a-site-public-scrutin-annonce.html")

# --- ballot: first cast (channel none) -------------------------------------
garnier = Registration.objects.get(poll=poll, email_canonical="h.garnier@example.fr")
token = reg.issue_token(garnier)  # fresh plaintext; only voter_hash is stored
get(Client(), f"/fr/bulletin/{poll.pk}/acces/{token.reveal()}/", "07-bulletin-vote.html")

# --- ballot: modification (needs the original token, so cast one fresh) -----
from apps.ballots import services as bal

r2, tok2 = reg.register(
    poll,
    {"last_name": "Petit", "first_names": "Élodie", "date_of_birth": "03/01/1990",
     "email": "elodie.petit@example.fr", "declared_on_honour": "on"},
    "fr",
)
reg.confirm_mailbox(r2)
bal.cast_online(poll, tok2, [["jardin"], ["mixte"], ["mineral"]])
get(Client(), f"/fr/bulletin/{poll.pk}/acces/{tok2.reveal()}/", "08-bulletin-modification.html")
get(Client(), f"/fr/bulletin/{poll.pk}/info/enregistre/", "09-bulletin-deja-enregistre.html")

# --- back-office ----------------------------------------------------------
ca = Client()
ca.force_login(admin)
get(ca, "/fr/mairie/", "10-mairie-index-scrutins.html")
get(ca, "/fr/mairie/comptes/", "18-mairie-comptes.html")
get(ca, "/fr/mairie/comptes/roles/", "19-mairie-roles.html")
# Screen 3 (upload + working-roll browse, R-4.4's spirit extended to it) is
# commune-level, reached from the general menu — not a poll's own URL.
get(ca, "/fr/mairie/liste-electorale/", "15-mairie-import-liste.html")

pa = Client()
pa.force_login(padmin)
get(pa, f"/fr/mairie/scrutin/{poll.pk}/", "11-mairie-tableau-de-bord.html")
get(pa, f"/fr/mairie/scrutin/{poll.pk}/configuration/", "12-mairie-configuration-lecture.html")
get(pa, f"/fr/mairie/scrutin/{draft.pk}/configuration/", "13-mairie-configuration-brouillon.html")
get(pa, f"/fr/mairie/scrutin/{poll.pk}/inscriptions/", "14-mairie-file-inscriptions.html")
# A poll's own read-only view of its frozen roll copy, browsable per R-4.4.
get(pa, f"/fr/mairie/scrutin/{poll.pk}/liste-electorale/", "15a-mairie-liste-electorale-scrutin.html")
get(pa, f"/fr/mairie/scrutin/{pub.pk}/depouillement/", "17-mairie-depouillement.html")

# --- announced poll: config read-only, with *ouvrir maintenant* (R-3.10) ----
announced_pa = Poll.objects.get(title_i18n__fr__startswith="Tracé de la future piste cyclable")
get(pa, f"/fr/mairie/scrutin/{announced_pa.pk}/configuration/", "12a-mairie-configuration-annoncee.html")

# --- open poll past its deadline: config read-only, *clôturer maintenant* --
late_poll = Poll.objects.get(title_i18n__fr__startswith="Aire de jeux du parc")
get(pa, f"/fr/mairie/scrutin/{late_poll.pk}/configuration/", "12b-mairie-configuration-cloture-manuelle.html")

eo = Client()
eo.force_login(operator)
get(eo, f"/fr/mairie/scrutin/{poll.pk}/bulletin-papier/", "16-mairie-bulletin-papier.html")
get(eo, f"/fr/mairie/scrutin/{poll.pk}/bulletin-papier/?q=Garnier",
    "16a-mairie-bulletin-papier-recherche.html")
bouchard = poll.roll_entries.get(birth_name="Bouchard")
_r = eo.post(
    f"/fr/mairie/scrutin/{poll.pk}/bulletin-papier/",
    {"q": "Bouchard", "roll_entry": str(bouchard.pk)},
    follow=True, SERVER_NAME="localhost",
)
save("16d-mairie-bulletin-papier-collision.html", _r.content.decode("utf-8"))
get(eo, f"/fr/mairie/scrutin/{poll.pk}/bulletins-papier/", "16b-mairie-bulletins-papier-liste.html")
if paper_ballot:
    get(eo, f"/fr/mairie/scrutin/{poll.pk}/bulletin-papier/{paper_ballot.pk}/recu/",
        "16c-mairie-recu-papier.html")

au = Client()
au.force_login(auditor)
get(au, f"/fr/mairie/scrutin/{poll.pk}/journal/", "21-mairie-journal-audit.html")

print("done ->", OUT)
