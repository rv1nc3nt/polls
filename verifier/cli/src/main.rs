// SPDX-License-Identifier: 0BSD
//! Independent verifier for the commune polling platform (§8, §9, §14).
//!
//! It reads only what the public site publishes, never the database, and
//! recomputes the canonical serialisation, the closure hash, the pairwise
//! matrix, the winner under the poll's tally method (Schulze, plurality or
//! approval) and the tie-break. It was written from
//! `docs/canonical-serialisation.md`, `docs/publication-format.md` and §8 of
//! the specification, and shares no code with the Python implementation — a
//! property the language boundary enforces structurally.
//!
//! When the two disagree, the resolution is to return to the specification and
//! determine which is wrong, never to adjust this binary until it matches.
//!
//! Usage:
//!
//! ```text
//! polls-verifier publication.json --closure-hash <hex> [--opening-seed <hex>]
//! polls-verifier ballots.csv [--method schulze|plurality|approval] \
//!     [--options <id,id,…>] [--closure-hash <hex>] [--opening-seed <hex>] \
//!     [--winner <option_id>]
//! ```
//!
//! The publication document (`?format=json` on the results page) carries the
//! method, the options and every published value, and each is checked against
//! its own ballots. That shows it agrees with itself, which a document rebuilt
//! from end to end would too (review B-1); `--closure-hash`, the value the
//! public page showed when the poll closed, is what ties it to the poll, and
//! `--opening-seed`, shown at opening, is compared as well when given. The
//! CSV carries ballots only, so the flags supply what is to be compared:
//! `--method` as the results page states it (its French label is accepted
//! too; Schulze without it), `--options` the poll's option ids so an option
//! no ballot ranked still gets its row.
//!
//! `--version` names the release and commit the binary was built from, and
//! the publication format versions it reads (`core::build`).
//!
//! Exit codes: 0 every compared value agrees, 1 at least one differs, 2 usage
//! or input error, 3 nothing was compared (a CSV given no value to check), 4
//! everything compared agrees but the ballots were not compared with the
//! closure hash noted at closure, so nothing ties them to the poll.
//! An unknown flag, a flag without a value or a repeated flag is a usage
//! error: silently ignoring one would let a mistyped check pass as done.
//!
//! This binary is presentation only: `polls-verifier-core` (`../core`) is
//! where the verification logic lives, shared with the GUI in `../gui`.

use std::process::ExitCode;

use polls_verifier_core::build;
use polls_verifier_core::counted::Method;
use polls_verifier_core::publication::TiebreakRule;
use polls_verifier_core::report::{
    verify, verify_publication, Anchors, Expected, PublicationReport, Report, Verdict, VerifyError,
};

const USAGE: &str =
    "usage: polls-verifier <publication.json> --closure-hash <hex> [--opening-seed <hex>]\n       \
    polls-verifier <ballots.csv> [--method schulze|plurality|approval] [--options <id,id,…>] \
    [--closure-hash <hex>] [--opening-seed <hex>] [--winner <option_id>]\n       \
    polls-verifier --help | --version";

const HELP: &str = "\
Recomputes a published poll result from the files its results page offers.

  polls-verifier publication.json --closure-hash <h> [--opening-seed <h>]
      The publication document (?format=json). It carries every value, and
      each is checked against its own ballots. That alone shows the document
      agrees with itself, as a rebuilt one would; give the values the poll's
      public page showed before the result was published:
        --closure-hash <h>  the closure hash, shown from the poll's closure
        --opening-seed <h>  the opening seed, shown from its opening

  polls-verifier ballots.csv [flags]
      The ballot list (?format=csv). It carries ballots only, so the flags
      supply the values to compare, copied from the results page:
        --method <m>        schulze (default), plurality or approval
        --options <ids>     the poll's option ids, comma-separated
        --closure-hash <h>  the published closure hash
        --opening-seed <h>  the published opening seed, to replay a tie-break
        --winner <id>       the announced winner
      Each flag takes its value as the next argument or after '='.

  polls-verifier --version
      The release and commit this binary was built from, and the publication
      format versions it reads: what a bug report should quote.

Exit codes:
  0  every compared value agrees
  1  at least one value differs
  2  usage or input error (unreadable file, unknown flag, malformed ballot list)
  3  nothing was compared: a CSV was given without --closure-hash or --winner
  4  everything compared agrees, but nothing was compared with the closure
     hash shown at closure: pass --closure-hash";

/// The flags a publication document takes: the values noted from the public
/// page before publication. The others are what the document already states.
const PUBLICATION_FLAGS: &[&str] = &["--closure-hash", "--opening-seed"];

const FLAGS: &[&str] = &[
    "--method",
    "--options",
    "--closure-hash",
    "--opening-seed",
    "--winner",
];

/// The command line, once every argument has been accounted for.
#[derive(Debug, Default, PartialEq)]
struct Args {
    help: bool,
    version: bool,
    path: Option<String>,
    /// `(flag, value)` in the order given, each flag at most once.
    flags: Vec<(String, String)>,
}

impl Args {
    fn get(&self, flag: &str) -> Option<&str> {
        self.flags
            .iter()
            .find(|(f, _)| f == flag)
            .map(|(_, v)| v.as_str())
    }
}

/// Parse strictly: every argument must be the one file, a known flag with its
/// value, `--help` or `--version`. Anything else is an error rather than
/// ignored.
fn parse_args(raw: &[String]) -> Result<Args, String> {
    let mut args = Args::default();
    let mut rest = raw.iter();
    while let Some(arg) = rest.next() {
        if arg == "--help" || arg == "-h" {
            args.help = true;
            continue;
        }
        if arg == "--version" || arg == "-V" {
            args.version = true;
            continue;
        }
        if !arg.starts_with('-') {
            if let Some(first) = &args.path {
                return Err(format!("one file at a time: got {first} and {arg}"));
            }
            args.path = Some(arg.clone());
            continue;
        }
        let (flag, inline) = match arg.split_once('=') {
            Some((flag, value)) => (flag, Some(value.to_string())),
            None => (arg.as_str(), None),
        };
        if !FLAGS.contains(&flag) {
            return Err(format!("unknown option {flag}"));
        }
        let value = match inline {
            Some(value) => value,
            None => match rest.next() {
                Some(value) if !value.starts_with("--") => value.clone(),
                _ => return Err(format!("{flag} needs a value")),
            },
        };
        if value.trim().is_empty() {
            return Err(format!("{flag} needs a value"));
        }
        if args.get(flag).is_some() {
            return Err(format!("{flag} given twice"));
        }
        args.flags.push((flag.to_string(), value));
    }
    Ok(args)
}

fn agreement(label: &str, agrees: bool) -> bool {
    println!("{label:<15} {}", if agrees { "AGREES" } else { "DIFFERS" });
    agrees
}

/// The recomputation, as both input kinds print it.
fn print_report(report: &Report) {
    println!("method         {}", report.method.id());
    println!("ballots        {}", report.ballot_count);
    println!("closure_hash   {}", report.closure_hash);
    println!("options        {}", report.options.join(", "));
    println!("pairwise matrix");
    for (i, row) in report.matrix.iter().enumerate() {
        println!("  {:>10} {:?}", report.options[i], row);
    }
    if let Some(counts) = &report.counts {
        println!("counts");
        for (option, count) in report.options.iter().zip(counts) {
            println!("  {option:>10} {count}");
        }
    }
    println!("winners         {}", report.winners.join(", "));
}

fn input_error(err: VerifyError) -> ExitCode {
    match err {
        VerifyError::Csv(message) | VerifyError::Publication(message) => eprintln!("{message}"),
        VerifyError::OpeningSeedNotHex => eprintln!("--opening-seed must be hex"),
        VerifyError::UnknownOption(option) => {
            eprintln!("a ballot ranks {option}, which the option list does not have");
        }
        VerifyError::MalformedTrackingCode(code) => {
            eprintln!("tracking code {code:?} is not one the platform issues: the file is not a ballot list it published");
        }
        VerifyError::MalformedRanking(code, why) => {
            eprintln!("ballot {code}: not a ranking the platform records ({why})");
        }
        VerifyError::DuplicateTrackingCode(code) => {
            eprintln!("tracking code {code} appears on more than one ballot: a published ballot list never repeats one");
        }
        VerifyError::MalformedOptionId(option) => {
            eprintln!("option {option:?} is not an id the platform accepts (A-Z, a-z, 0-9, _ and -, at most 50)");
        }
        VerifyError::DuplicateOption(option) => {
            eprintln!("--options lists {option} more than once");
        }
    }
    ExitCode::from(2)
}

fn check_publication(text: &str, args: &Args) -> ExitCode {
    let anchors = Anchors {
        closure_hash: args.get("--closure-hash"),
        opening_seed: args.get("--opening-seed"),
    };
    let checked: PublicationReport = match verify_publication(text, &anchors) {
        Ok(checked) => checked,
        Err(err) => return input_error(err),
    };
    let report = &checked.report;
    println!(
        "publication    format {}, poll {}",
        checked.format_version, checked.poll_id
    );
    print_report(report);
    println!(
        "  the method is the document's own statement, version {}: compare it with what \
         the poll announced",
        checked.method_version
    );

    agreement("closure hash", report.closure_hash_agrees == Some(true));
    agreement("ballot count", checked.ballot_count_agrees);
    agreement("matrix", checked.matrix_agrees);
    if let Some(agrees) = checked.counts_agree {
        agreement("counts", agrees);
    }
    if let Some(agrees) = checked.tiebreak_agrees {
        if checked.tiebreak_rule == Some(TiebreakRule::Physical) {
            println!(
                "tie-break      physical draw at the mairie; checked to be among exactly the \
                 tied options, not replayable"
            );
        }
        if let Some(order) = &report.tiebreak_order {
            println!("tie-break order {}", order.join(", "));
        }
        agreement("tie-break", agrees);
    }
    agreement("winner", report.winner_agrees == Some(true));
    let counts = &checked.participation;
    println!(
        "participation  registered {}, online {}, paper {}, paper uncounted {}, non-voters {}",
        counts.registered,
        counts.ballots_online,
        counts.ballots_paper,
        counts.paper_uncountersigned,
        counts.non_voters
    );
    agreement("participation", checked.participation_agrees);
    if let Some(agrees) = checked.closure_hash_anchor {
        agreement("hash at closure", agrees);
    }
    if let Some(agrees) = checked.opening_seed_anchor {
        agreement("seed at opening", agrees);
    }

    match checked.verdict() {
        Verdict::Verified => ExitCode::SUCCESS,
        Verdict::Differs => ExitCode::from(1),
        Verdict::NotAnchored => {
            // Every line above agrees; a document carefully rebuilt with other
            // ballots would agree as well.
            println!(
                "NOT ANCHORED: the document agrees with itself; pass --closure-hash, the value \
                 the results page showed when the poll closed, to check it is the poll's"
            );
            ExitCode::from(4)
        }
    }
}

fn check_csv(text: &str, args: &Args) -> ExitCode {
    let method = match args.get("--method") {
        None => Method::Schulze,
        Some(text) => {
            if let Some(method) = Method::parse(text) {
                method
            } else {
                eprintln!("--method must be schulze, plurality or approval");
                return ExitCode::from(2);
            }
        }
    };
    let options: Option<Vec<String>> = args.get("--options").map(|list| {
        list.split(',')
            .map(str::trim)
            .filter(|o| !o.is_empty())
            .map(String::from)
            .collect()
    });
    let expected = Expected {
        method,
        options: options.as_deref(),
        closure_hash: args.get("--closure-hash"),
        opening_seed: args.get("--opening-seed"),
        winner: args.get("--winner"),
    };

    let report = match verify(text, &expected) {
        Ok(report) => report,
        Err(err) => return input_error(err),
    };
    print_report(&report);

    let mut ok = true;
    if let Some(matched) = report.closure_hash_agrees {
        ok &= agreement("closure hash", matched);
    }
    if report.winners.len() > 1 {
        match &report.tiebreak_order {
            Some(drawn) => println!("tie-break order {}", drawn.join(", ")),
            None => println!(
                "tie among {} options; pass --opening-seed to resolve",
                report.winners.len()
            ),
        }
    }
    if let Some(matched) = report.winner_agrees {
        ok &= agreement("winner", matched);
    }

    if report.closure_hash_agrees.is_none() && report.winner_agrees.is_none() {
        // The recomputation above is not a verification: nothing published
        // was compared with it. Exit 0 here would read as "verified".
        println!(
            "NOTHING COMPARED: pass --closure-hash and/or --winner, copied from the results page"
        );
        return ExitCode::from(3);
    }
    if !ok {
        return ExitCode::from(1);
    }
    if report.closure_hash_agrees.is_none() {
        // A winner recomputed from ballots nothing ties to the poll: a list
        // rebuilt to match it would agree as well (review B-1).
        println!(
            "NOT ANCHORED: the winner agrees with these ballots; pass --closure-hash, the value \
             the results page showed when the poll closed, to check they are the poll's"
        );
        return ExitCode::from(4);
    }
    ExitCode::SUCCESS
}

fn main() -> ExitCode {
    let raw: Vec<String> = std::env::args().skip(1).collect();
    let args = match parse_args(&raw) {
        Ok(args) => args,
        Err(message) => {
            eprintln!("{message}\n{USAGE}");
            return ExitCode::from(2);
        }
    };
    if args.help {
        println!("{USAGE}\n\n{HELP}");
        return ExitCode::SUCCESS;
    }
    if args.version {
        println!("polls-verifier {}", build::describe());
        return ExitCode::SUCCESS;
    }
    let Some(path) = &args.path else {
        eprintln!("{USAGE}");
        return ExitCode::from(2);
    };

    let text = match std::fs::read_to_string(path) {
        Ok(text) => text,
        Err(err) => {
            eprintln!("cannot read {path}: {err}");
            return ExitCode::from(2);
        }
    };

    // By content, not extension: a browser may save the document under any
    // name. The CSV starts with its header, never with '{'.
    if text.trim_start().starts_with('{') {
        if let Some((flag, _)) = args
            .flags
            .iter()
            .find(|(flag, _)| !PUBLICATION_FLAGS.contains(&flag.as_str()))
        {
            eprintln!("{flag} does not apply to a publication document: it states that value");
            return ExitCode::from(2);
        }
        check_publication(&text, &args)
    } else {
        check_csv(&text, &args)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn parse(line: &str) -> Result<Args, String> {
        parse_args(
            &line
                .split_whitespace()
                .map(String::from)
                .collect::<Vec<_>>(),
        )
    }

    #[test]
    fn known_flags_take_their_value_either_way() {
        let args = parse("b.csv --closure-hash ab --winner=x").expect("parses");
        assert_eq!(args.path.as_deref(), Some("b.csv"));
        assert_eq!(args.get("--closure-hash"), Some("ab"));
        assert_eq!(args.get("--winner"), Some("x"));
        assert!(parse("--help").expect("parses").help);
        assert!(parse("--version").expect("parses").version);
        assert!(parse("-V").expect("parses").version);
    }

    #[test]
    fn anything_unrecognised_is_an_error_not_ignored() {
        for bad in [
            "b.csv --closure_hash ab",
            "b.csv --winner",
            "b.csv --winner --method schulze",
            "b.csv --winner=",
            "b.csv --winner a --winner b",
            "b.csv other.csv",
            "b.csv -x",
        ] {
            assert!(parse(bad).is_err(), "accepted {bad:?}");
        }
    }
}
