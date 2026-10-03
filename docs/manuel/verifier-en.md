<!-- SPDX-License-Identifier: 0BSD -->

# Verify a result yourself

This guide is for **anyone** who wants to make sure, without having to trust
either the mairie or the software's publisher, that a published result is
indeed the one the cast ballots produce. You need no computer skill beyond
knowing how to download a file and follow instructions — this document
explains every step, for mouse and keyboard alike.

No registration is needed for this check: the data you need is **public**,
on the consultation's results page.

## Why this program exists

The public site already shows the result, the preference matrix and the
reasoning. But the public site is both judge and party: it computes the
result *and* displays it. The **verifier** is a second, entirely independent
program:

- it is written in a different language (Rust, where the site is written in
  Python) and shares no code with it — a bug in the first cannot accidentally
  reappear in the second;
- it connects to no database and needs no access to the mairie or its
  server: it only reads what the public site publishes for everyone — the
  publication document or the CSV file;
- it recomputes everything from scratch — the closure hash, the pairwise
  matrix, the winner and, where applicable, the tie-break — and tells you
  whether it finds exactly what the site announces.

If it finds the same result, you have proof, independent of the site, that
the tally of the published ballots is correct — which does not prove
everything (see ["What the verifier does not prove"](#what-the-verifier-does-not-prove)). If it does not, something is wrong, and it should be
reported (see ["What to do in case of disagreement"](#what-to-do-in-case-of-disagreement)
below) rather than trusting either of the two computations.

## What you need

Two things:

1. the consultation's **publication document** — the "Full publication
   document (JSON)" link on its results page (figure 20 of the [voter's
   guide](guide-electeur-en.md#8-verify-after-closure)). It contains the
   anonymised list of ballots and every value the site publishes: tally
   method, options, closure hash, pairwise matrix, winner and, where
   applicable, the tie-break;
2. the **verifier**, a small program to download once — see below.

The same page also offers the **"Anonymised ballot list (CSV)"**, which
opens in a spreadsheet. The verifier reads it too, but it holds the ballots
only: you then supply the values to compare yourself, copied from the results
page (see below).

The verifier comes in two forms, built from the same verification code: a
**graphical application**, recommended for most people, and a **command
line**, for anyone comfortable with a terminal or who wants to automate
repeated checks. Both give exactly the same result; choose whichever suits
you.

### Before publication: note two values

Two values appear on the consultation's public page before the results do,
and cannot change afterwards:

- the **opening seed**, from the moment voting opens;
- the **closure hash** and the number of **ballots counted**, from the moment
  it closes.

Note them then (a screenshot is enough) and give them to the verifier
afterwards: they are what shows the published files are the poll's, and not
files rebuilt after the fact. Without them, the verifier can only find that
the files agree with themselves, as files rebuilt from end to end would too:
it then reports a "not anchored" result, never a successful verification.

If you did not note them in time, take the ones the consultation's page
shows. The check is still useful, but weaker: the values are then read at the
same time as the results.

## Downloading the verifier

The verifier is distributed already compiled, so no one needs to install a
development environment. Go to the project's releases page:

    https://github.com/rv1nc3nt/polls/releases

Open the most recent release and, in the list of attached files ("Assets"),
find the one matching your system — the graphical application if you are not
comfortable with a terminal, otherwise the command line:

| Your system | Graphical application | Command line |
|---|---|---|
| Windows | `polls-verifier-gui-windows-x86_64.exe` | `polls-verifier-windows-x86_64.exe` |
| macOS, recent Mac (Apple chip, "M1", "M2", "M3"…) | `polls-verifier-gui-macos-aarch64` | `polls-verifier-macos-aarch64` |
| macOS, older Mac (Intel chip) | `polls-verifier-gui-macos-x86_64` | `polls-verifier-macos-x86_64` |
| Linux | `polls-verifier-gui-linux-x86_64` | `polls-verifier-linux-x86_64` |

> **Not sure which chip your Mac has?** Apple menu (top left of the screen)
> → "About This Mac". The "Chip" or "Processor" line reads "Apple M…" (choose
> `aarch64`) or "Intel" (choose `x86_64`). If in doubt, the Intel build also
> runs on Apple Silicon Macs, just a little more slowly.

Put the downloaded file somewhere easy to find — next to the publication
document you already downloaded, for instance.

### Checking the download (optional)

A verifier is only worth anything if it is the right program. Every release
attaches, among its files, a `SHA256SUMS` list: the fingerprint of each
program. Compute the fingerprint of the file you downloaded and compare it with
the line bearing its name:

**Windows (PowerShell):**

    Get-FileHash .\polls-verifier-windows-x86_64.exe

**macOS:**

    shasum -a 256 polls-verifier-macos-aarch64

**Linux:**

    sha256sum polls-verifier-linux-x86_64

The two strings must be identical. If they differ, do not run the program:
download it again from the releases page.

To go further, every program also carries a provenance attestation, signed
when it was built, proving it was compiled from the project's public code by
its release procedure rather than on someone's computer. With GitHub's
command-line tool (`gh`):

    gh attestation verify polls-verifier-linux-x86_64 --repo rv1nc3nt/polls

Finally, you can build the verifier yourself from the release's source code
(the `verifier/` folder), with `rustup` and
`cargo build --release --manifest-path verifier/Cargo.toml`: the compiler used
is fixed in the repository's `rust-toolchain.toml` file.

## Using the graphical application (recommended)

### Windows

Double-click the downloaded file. Windows will probably show a blue
"Windows protected your PC" screen (SmartScreen): this is expected for a
program with few downloads, not a sign of danger in itself, but check that
you got it from `github.com/rv1nc3nt/polls`. Click "More info", then "Run
anyway". The application window opens.

### macOS

Double-click the downloaded file in Finder. If macOS refuses to launch it
("cannot be opened because the developer cannot be verified"), open Terminal
(Applications → Utilities → Terminal) and remove the quarantine flag:

    cd ~/Downloads
    chmod +x polls-verifier-gui-macos-aarch64
    xattr -d com.apple.quarantine polls-verifier-gui-macos-aarch64

(replace the file name with the one you downloaded). Double-click again; if
macOS still asks for confirmation, open System Settings → Privacy &
Security, scroll to the message about this file and click "Open Anyway".

### Linux

Make the file executable then double-click it in your file manager (or run
it from a terminal):

    cd ~/Downloads
    chmod +x polls-verifier-gui-linux-x86_64
    ./polls-verifier-gui-linux-x86_64

### Verifying

The "Independent verifier" window offers three steps:

1. **File** — click "Choose a file…" and select the downloaded publication
   document (JSON), or drop it directly onto the window.
2. **Noted values** — the **closure hash** and the **opening seed** you
   noted (see ["Before publication: note two
   values"](#before-publication-note-two-values)), whichever the file. With
   the CSV file only, add the values from the results page: the **tally
   method** (Schulze, majoritaire — plurality — or par assentiment —
   approval), the **option identifiers** separated by commas and the
   **announced winner**; the publication document already contains them.
   With no value to compare at all, the application still shows what it
   recomputed, but says so at the top of the result: "Nothing was compared".
   That is not a verification.
3. Click **Verify**.

The result opens with a summary line: "✓ VERIFIED: every compared value
matches" in green, or "✗ … do NOT match" in red. (The application is in
French: it reads « ✓ VÉRIFIÉ » or « ✗ … NE concordent PAS ».) If everything
matches but no closure hash was entered, the line is orange: « ⚠ … NON
ANCRÉ » (not anchored). The files agree with themselves, but nothing shows
they are the poll's: enter the closure hash and click again. If you change a
value in step 2 after clicking **Verify**, that result is cleared: click again
to check the new values.

With the publication document, it continues with a green "✓ …
matches" or red "✗ … does NOT match" line for each published value: number
of ballots, pairwise matrix, votes per option (plurality or approval poll),
tie-break if there was one, closure hash and winner. Then come the tally
method, as the document states it — compare it with the one the
consultation announced before it opened; it is the one value the verifier
cannot recompute — and the recomputed matrix and winner(s). This is the exact
equivalent of the `AGREES` / `DIFFERS` lines from the command-line version
below; see ["What to do in case of
disagreement"](#what-to-do-in-case-of-disagreement) if you get a mismatch.

## Using the command line

This section is for anyone who prefers a terminal — to script a check, or
automate several of them. The result is identical to the graphical
application's; both call the same verification code.

### Preparing the program, depending on your system

A program downloaded from the Internet is not immediately executable: your
system protects against this by default, and you have to grant permission
explicitly. This is normal, and only needs doing once.

#### Windows

1. Open the folder where you downloaded the file, in Explorer.
2. Double-click it. Windows will probably show a blue "Windows protected
   your PC" screen (SmartScreen): this is expected for a program with few
   downloads, not a sign of danger in itself, but check that you got it from
   `github.com/rv1nc3nt/polls`. Click "More info", then "Run anyway".
3. A black window (the command prompt) opens and closes immediately — this
   is normal, the program needs to be told which file to check (next step).
   It does not run on its own from a double-click.
4. Open a command prompt in that folder: in Explorer, hold Shift, right-click
   in the folder, "Open PowerShell window here" (or "Open in Terminal").

#### macOS

1. Open Terminal (Applications → Utilities → Terminal).
2. Make the file executable and remove the quarantine flag macOS puts on
   every downloaded file:

       cd ~/Downloads
       chmod +x polls-verifier-macos-aarch64
       xattr -d com.apple.quarantine polls-verifier-macos-aarch64

   (replace the file name with the one you downloaded, and `~/Downloads`
   with the folder it is in if different).
3. If macOS still refuses to launch it ("cannot be opened because the
   developer cannot be verified"), open System Settings → Privacy &
   Security, scroll to the message about this file and click "Open Anyway".

#### Linux

Open a terminal in the download folder and make the file executable:

    cd ~/Downloads
    chmod +x polls-verifier-linux-x86_64

### Running the check

From a terminal opened in the folder holding the program and the
publication document, type (adapting the file names to what you
downloaded):

**Windows (PowerShell):**

    .\polls-verifier-windows-x86_64.exe publication.json --closure-hash 87694cf0...

**macOS or Linux:**

    ./polls-verifier-macos-aarch64 publication.json --closure-hash 87694cf0...

`--closure-hash` is the closure hash you noted (see ["Before publication:
note two values"](#before-publication-note-two-values)); add `--opening-seed`
followed by the opening seed if you noted it too. The document contains the
other values. The program shows
the tally method the document states, the number of ballots read, the hash
it recomputed itself, the list of options, the pairwise matrix, each
option's vote count for a plurality or approval poll and the winner(s) —
then one line per published value it checked:

    closure hash    AGREES
    ballot count    AGREES
    matrix          AGREES
    winner          AGREES
    participation   AGREES
    hash at closure AGREES

`AGREES` means the value recomputed from the ballots alone is identical to
the one the site publishes; `DIFFERS` would mean the opposite (see below).
The `hash at closure` line compares the ballots with the hash you noted, and
`seed at opening` the seed. Without `--closure-hash`, the program ends with
`NOT ANCHORED` and a code that is not a success: the document agrees with
itself, as one rebuilt from end to end would.
A `derivation` line is added, recomputing the published reasoning; an
`orderings` line for the table of ballots per ranking order the results page
shows (a Schulze poll with at most four proposals); a `counts` line for a
plurality or approval poll; and a `tie-break` line if a tie-break took place. A last line, `participation`, checks that the
participation figures the site publishes add up: the online and paper ballots
must make the number of ballots in the list, and the registered electors must
be exactly those who voted, those whose paper ballot went uncounted, and those
who did not vote. The list cannot tell who registered, but a list with ballots
added and figures left untouched no longer adds up.

The tally method is the one value the verifier cannot recompute, since it is
what decides the winner: it shows it on its first line (`method`) so you can
compare it with the one the consultation announced before it opened.

#### With the CSV file

The CSV file holds the ballots only: the values to compare are copied from
the results page. Type (adapting the file names, and the hash to the one
shown on the results page):

**Windows (PowerShell):**

    .\polls-verifier-windows-x86_64.exe ballots.csv --closure-hash 87694cf0...

**macOS or Linux:**

    ./polls-verifier-macos-aarch64 ballots.csv --closure-hash 87694cf0...

The program shows the number of ballots read, the hash it recomputed itself,
the list of options, the pairwise matrix and the winner(s) — then, on the
last useful line:

    closure hash    AGREES

Without `--closure-hash` or `--winner` the program has nothing to compare:
it shows its recomputation, then `NOTHING COMPARED`, and ends with an error
code, never with success. With `--winner` alone it checks the winner, but
nothing shows the ballots are the poll's: it ends with `NOT ANCHORED`, again
not a success. A misspelt flag, or one given without a value, is
refused rather than ignored. Each flag can be written `--closure-hash
87694cf0...` or `--closure-hash=87694cf0...`.

`AGREES` means the hash you recomputed is identical to the one published on
the site: the CSV file has not been altered since the closure computation.
`DIFFERS` would mean the opposite (see below).

To also check the announced winner, add `--winner` followed by the
identifier of the retained option (shown in the matrix, in parentheses next
to the label on the results page), and `--method` followed by the tally
method the results page gives: `schulze`, `plurality` or `approval`:

    ./polls-verifier-macos-aarch64 ballots.csv --closure-hash 87694cf0... --method plurality --winner option-b

A `winner AGREES` line confirms that the verifier, starting from scratch
from the public file alone, finds exactly the winner announced by the site.

The CSV file does not say which method the poll used: you supply it.
Without `--method`, the verifier counts under the Schulze method, and its
first line (`method`) states which method it applied. A winner recomputed
under a different method from the poll's may differ without anything being
wrong. The hash check, on the other hand, holds whatever the method.

Nor does the CSV file say which options the poll offered: it knows only
those at least one ballot ranked. To get every row of the published matrix,
including that of an option nobody ranked, add `--options` followed by the
option identifiers, separated by commas (`--options
option-a,option-b,option-c`). An option a ballot ranks but the list omits is
reported as an error: the list or the file is not the poll's.

#### In case of a tie (tie-break)

With the publication document, there is nothing to add: the verifier itself
replays the computed tie-break from the opening seed the document contains,
and compares it with the published one (`tie-break` line). If the
consultation provided for a **physical drawing of lots**, held at the
mairie, no program can replay it: the verifier only checks that the
published draw covers exactly the tied options, and says so.

With the CSV file, the results page also publishes the **opening seed** — a
second hexadecimal string, distinct from the closure hash. Add it with
`--opening-seed` so the verifier replays the tie-break itself:

    ./polls-verifier-macos-aarch64 ballots.csv --closure-hash 87694cf0... --method schulze --opening-seed a1b2c3... --winner option-b

The opening seed is drawn when the consultation opens and shown from that
moment on its public page, under the calendar. If you noted it then, check
that the one in the publication document is exactly the same: a seed changed
afterwards could pick the outcome of a tie-break, and the recomputation would
still agree.

The tie-break uses no drawing of lots and no programming-language function:
it is entirely determined by the closure hash and the opening seed, which is
exactly what this command checks. See [Tally methods,
explained](methodes-de-depouillement-en.md#ties-and-the-tie-break) for the
detail of this computation.

## What to do in case of disagreement

The command line ends with a code that sums up the outcome, useful if you
automate the check:

| Code | Meaning | What to do |
|---|---|---|
| 0 | Every compared value matches. | Nothing: the published result is the one the ballots produce. |
| 1 | At least one value does not match (`DIFFERS`). | Follow the steps below. |
| 2 | The verifier could not work: unreadable or incomplete file, unknown flag or flag without a value, or an impossible ballot list (a repeated or malformed tracking code, an empty ranking, an option ranked twice, an option identifier the platform does not accept). | Correct the command, or download the file again. An impossible list in a file downloaded as-is from the results page is an anomaly to report like a disagreement. |
| 3 | Nothing was compared (a CSV file without `--closure-hash` or `--winner`). | Add the values to compare, copied from the results page. |
| 4 | Everything compared matches, but the ballots were not compared with the closure hash (`NOT ANCHORED`). | Run again with `--closure-hash`, the hash noted at closure. |

A code 2, 3 or 4 is never a success: nothing then shows the files are the
poll's.

If a line shows `DIFFERS`:

1. First check that the downloaded file is indeed complete (download it
   again from the results page if in doubt) and, with the CSV file, that you
   copied the hash (and, where relevant, the opening seed) **with no space
   and no missing character**.
2. If the disagreement persists, **do not keep it to yourself**: contact the
   mairie, stating the consultation concerned, the exact command you ran and
   its full output, and the verifier's version: `polls-verifier --version`
   prints it on the command line, and the graphical application shows it
   under its title. This is exactly the kind of anomaly this verifiability
   is meant to be able to catch.

## What the verifier does not prove

`AGREES` on every line proves one precise thing: the published ballots do
give the published result. It says nothing about how that list was put
together. In particular, the verifier cannot establish:

- **that each ballot comes from a registered elector, and from one only.** The
  published list is anonymous, by design: it does not say who voted. The
  verifier checks that the participation figures add up with the list, not
  that they match the actual registrations, which nobody outside the mairie
  can see.
- **that no ballot was removed or changed.** Only an elector who kept their
  tracking code can see that, by finding the code in the list with the
  ranking they chose (see the [voter's
  guide](guide-electeur-en.md#8-verify-after-closure)). The more electors do
  so, the harder any tampering would be to hide.
- **that nothing changed since closure, nor the seed since opening, unless
  you give it the values noted in advance.** Without them, it only checks
  that the document agrees with itself; a document rebuilt from end to end
  would too, and it reports "not anchored". With them, it checks this (see
  ["Before publication: note two
  values"](#before-publication-note-two-values)); it cannot know, however,
  whether you noted them in time. The closure hash is also
  what ties the CSV file to the publication document: the verifier reads one
  or the other, never both together, and they carry the same ballots if their
  closure hash is the same.
- **that the tally method is the one announced.** It decides the winner: the
  verifier displays it so you can compare it with the one the consultation
  announced before it opened.
- **that each ballot follows the consultation's rules.** It refuses a ranking
  no consultation accepts (empty, or an option ranked twice), but it does not
  know this one's own rules: whether ties were allowed, or whether every
  option had to be ranked.
- **that the published labels are the ones electors saw.** It counts on the
  option identifiers; their labels are only for display.
- **a physical draw**, which no program can replay (see above).
- **ballot secrecy.** That nobody can link a ballot to an elector depends on
  how the platform is built and how the mairie runs it, not on what is
  published: no outside program can observe it.

## Going further

The verifier's source code (`verifier/`) and the exact format of the files
it reads (`docs/publication-format.md` for the publication document,
`docs/canonical-serialisation.md` for the ballots and the hash) are public:
anyone can read exactly what this program does, or write their own version
in another language to verify things even more independently. To understand exactly
what the verifier recomputes — the Schulze, plurality or approval method,
and the tie-break — see [Tally methods,
explained](methodes-de-depouillement-en.md).
