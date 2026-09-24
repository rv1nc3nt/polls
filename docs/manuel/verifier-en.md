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
  server: it only reads the CSV file the public site publishes for everyone;
- it recomputes everything from scratch — the closure hash, the pairwise
  matrix, the winner and, where applicable, the tie-break — and tells you
  whether it finds exactly what the site announces.

If it finds the same result, you have proof, independent of the site, that
the tally is correct. If it does not, something is wrong, and it should be
reported (see ["What to do in case of disagreement"](#what-to-do-in-case-of-disagreement)
below) rather than trusting either of the two computations.

## What you need

Three things, all available from the consultation's results page (figure 20
of the [voter's guide](guide-electeur.md#8-verify-after-closure)):

1. the **CSV** file of the anonymised list of ballots — a "Anonymised list of
   ballots (CSV)" link on that page;
2. the **closure hash** shown on the same page (a string of hexadecimal
   characters, e.g. `87694cf0…`);
3. the **verifier**, a small program to download once — see below.

The verifier comes in two forms, built from the same verification code: a
**graphical application**, recommended for most people, and a **command
line**, for anyone comfortable with a terminal or who wants to automate
repeated checks. Both give exactly the same result; choose whichever suits
you.

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

Put the downloaded file somewhere easy to find — next to the CSV file you
already downloaded, for instance.

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

1. **Ballots CSV file** — click "Choose a file…" and select the downloaded
   CSV, or drop it directly onto the window.
2. **Values to compare** — choose the **tally method** the results page
   gives (Schulze, majoritaire — plurality — or par assentiment —
   approval), then paste the **expected closure hash** into the field of the
   same name. In case of a tie (see below), also paste the
   **opening seed**; to also check the announced winner, enter its
   identifier in **announced winner**. These three fields are optional —
   without them, the application still shows what it recomputed, simply
   without comparing anything.
3. Click **Verify**.

The result is shown below: the number of ballots read, the recomputed hash,
the pairwise matrix, each option's vote count for a plurality or approval
poll, the winner(s) under the chosen method, and — for each
value you filled in — a green "✓ … matches" or red "✗ … does NOT match"
line. This is the exact equivalent of the `AGREES` / `DIFFERS` lines from the
command-line version below; see ["What to do in case of
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

From a terminal opened in the folder holding the program and the CSV file,
type (adapting the file names to what you downloaded, and the hash to the
one shown on the results page):

**Windows (PowerShell):**

    .\polls-verifier-windows-x86_64.exe ballots.csv --closure-hash 87694cf0...

**macOS or Linux:**

    ./polls-verifier-macos-aarch64 ballots.csv --closure-hash 87694cf0...

The program shows the number of ballots read, the hash it recomputed itself,
the list of options, the pairwise matrix and the winner(s) — then, on the
last useful line:

    closure hash    AGREES

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

#### In case of a tie (tie-break)

If the results page states that a tie-break took place, it also publishes
the **opening seed** — a second hexadecimal string, distinct from the
closure hash. Add it with `--opening-seed` so the verifier replays the
tie-break itself:

    ./polls-verifier-macos-aarch64 ballots.csv --closure-hash 87694cf0... --method schulze --opening-seed a1b2c3... --winner option-b

The tie-break uses no drawing of lots and no programming-language function:
it is entirely determined by the closure hash and the opening seed, which is
exactly what this command checks. See [Tally methods,
explained](methodes-de-depouillement.md#ties-and-the-tie-break) for the
detail of this computation.

## What to do in case of disagreement

If a line shows `DIFFERS`:

1. First check that you copied the hash (and, where relevant, the opening
   seed) **with no space and no missing character**, and that the
   downloaded CSV file is indeed complete (download it again from the
   results page if in doubt).
2. If the disagreement persists, **do not keep it to yourself**: contact the
   mairie, stating the consultation concerned, the exact command you ran and
   its full output. This is exactly the kind of anomaly this verifiability
   is meant to be able to catch.

## Going further

The verifier's source code (`verifier/`) and the exact format of the CSV
file it reads (`docs/canonical-serialisation.md`) are public: anyone can
read exactly what this program does, or write their own version in another
language to verify things even more independently. To understand exactly
what the verifier recomputes — the Schulze, plurality or approval method,
and the tie-break — see [Tally methods,
explained](methodes-de-depouillement.md).
