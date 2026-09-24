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
//! polls-verifier publication.json
//! polls-verifier ballots.csv [--method schulze|plurality|approval] \
//!     [--options <id,id,…>] [--closure-hash <hex>] [--opening-seed <hex>] \
//!     [--winner <option_id>]
//! ```
//!
//! The publication document (`?format=json` on the results page) carries the
//! method, the options and every published value, and each is checked; no
//! flag applies to it. The CSV carries ballots only, so the flags supply what
//! is to be compared: `--method` as the results page states it (its French
//! label is accepted too; Schulze without it), `--options` the poll's option
//! ids so an option no ballot ranked still gets its row.
//!
//! Exit codes: 0 agreement, 1 disagreement, 2 usage or input error.
//!
//! This binary is presentation only: `polls-verifier-core` (`../core`) is
//! where the verification logic lives, shared with the GUI in `../gui`.

use std::process::ExitCode;

use polls_verifier_core::counted::Method;
use polls_verifier_core::publication::TiebreakRule;
use polls_verifier_core::report::{
    verify, verify_publication, Expected, PublicationReport, Report, VerifyError,
};

const USAGE: &str = "usage: polls-verifier <publication.json>\n       \
    polls-verifier <ballots.csv> [--method schulze|plurality|approval] [--options <id,id,…>] \
    [--closure-hash <hex>] [--opening-seed <hex>] [--winner <option_id>]";

const FLAGS: &[&str] = &["--method", "--options", "--closure-hash", "--opening-seed", "--winner"];

fn arg_value(args: &[String], flag: &str) -> Option<String> {
    args.iter().position(|a| a == flag).and_then(|i| args.get(i + 1)).cloned()
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
            eprintln!("a ballot ranks {option}, which the option list does not have")
        }
    }
    ExitCode::from(2)
}

fn check_publication(text: &str) -> ExitCode {
    let checked: PublicationReport = match verify_publication(text) {
        Ok(checked) => checked,
        Err(err) => return input_error(err),
    };
    let report = &checked.report;
    println!("publication    format {}, poll {}", checked.format_version, checked.poll_id);
    print_report(report);
    println!(
        "  the method is the document's own statement, version {}: compare it with what \
         the poll announced",
        checked.method_version
    );

    let mut ok = true;
    ok &= agreement("closure hash", report.closure_hash_agrees == Some(true));
    ok &= agreement("ballot count", checked.ballot_count_agrees);
    ok &= agreement("matrix", checked.matrix_agrees);
    if let Some(agrees) = checked.counts_agree {
        ok &= agreement("counts", agrees);
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
        ok &= agreement("tie-break", agrees);
    }
    ok &= agreement("winner", report.winner_agrees == Some(true));

    if ok {
        ExitCode::SUCCESS
    } else {
        ExitCode::from(1)
    }
}

fn check_csv(text: &str, args: &[String]) -> ExitCode {
    let method = match arg_value(args, "--method") {
        None => Method::Schulze,
        Some(text) => match Method::parse(&text) {
            Some(method) => method,
            None => {
                eprintln!("--method must be schulze, plurality or approval");
                return ExitCode::from(2);
            }
        },
    };
    let options: Option<Vec<String>> = arg_value(args, "--options").map(|list| {
        list.split(',').map(str::trim).filter(|o| !o.is_empty()).map(String::from).collect()
    });
    let closure_hash = arg_value(args, "--closure-hash");
    let opening_seed = arg_value(args, "--opening-seed");
    let winner = arg_value(args, "--winner");
    let expected = Expected {
        method,
        options: options.as_deref(),
        closure_hash: closure_hash.as_deref(),
        opening_seed: opening_seed.as_deref(),
        winner: winner.as_deref(),
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

    if ok {
        ExitCode::SUCCESS
    } else {
        ExitCode::from(1)
    }
}

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let Some(path) = args.first().filter(|a| !a.starts_with("--")) else {
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
        if let Some(flag) = args.iter().find(|a| FLAGS.contains(&a.as_str())) {
            eprintln!("{flag} does not apply to a publication document: it carries every value");
            return ExitCode::from(2);
        }
        check_publication(&text)
    } else {
        check_csv(&text, &args)
    }
}
