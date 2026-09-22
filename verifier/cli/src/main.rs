// SPDX-License-Identifier: 0BSD
//! Independent verifier for the commune polling platform (§8, §9, §14).
//!
//! It reads only the published CSV, never the database, and recomputes the
//! canonical serialisation, the closure hash, the pairwise matrix, the Schulze
//! winner and the tie-break. It was written from
//! `docs/canonical-serialisation.md` and §8 of the specification, and shares
//! no code with the Python implementation — a property the language boundary
//! enforces structurally.
//!
//! When the two disagree, the resolution is to return to the specification and
//! determine which is wrong, never to adjust this binary until it matches.
//!
//! Usage:
//!
//! ```text
//! polls-verifier ballots.csv \
//!     [--closure-hash <hex>] [--opening-seed <hex>] [--winner <option_id>]
//! ```
//!
//! Exit codes: 0 agreement, 1 disagreement, 2 usage or input error.
//!
//! This binary is presentation only: `polls-verifier-core` (`../core`) is
//! where the verification logic lives, shared with the GUI in `../gui`.

use std::process::ExitCode;

use polls_verifier_core::report::{verify, Expected, VerifyError};

fn arg_value(args: &[String], flag: &str) -> Option<String> {
    args.iter().position(|a| a == flag).and_then(|i| args.get(i + 1)).cloned()
}

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let Some(path) = args.first().filter(|a| !a.starts_with("--")) else {
        eprintln!("usage: polls-verifier <ballots.csv> [--closure-hash <hex>] [--opening-seed <hex>] [--winner <option_id>]");
        return ExitCode::from(2);
    };

    let text = match std::fs::read_to_string(path) {
        Ok(text) => text,
        Err(err) => {
            eprintln!("cannot read {path}: {err}");
            return ExitCode::from(2);
        }
    };

    let closure_hash = arg_value(&args, "--closure-hash");
    let opening_seed = arg_value(&args, "--opening-seed");
    let winner = arg_value(&args, "--winner");
    let expected = Expected {
        closure_hash: closure_hash.as_deref(),
        opening_seed: opening_seed.as_deref(),
        winner: winner.as_deref(),
    };

    let report = match verify(&text, &expected) {
        Ok(report) => report,
        Err(VerifyError::Csv(err)) => {
            eprintln!("{err}");
            return ExitCode::from(2);
        }
        Err(VerifyError::OpeningSeedNotHex) => {
            eprintln!("--opening-seed must be hex");
            return ExitCode::from(2);
        }
    };

    println!("ballots        {}", report.ballot_count);
    println!("closure_hash   {}", report.closure_hash);
    println!("options        {}", report.options.join(", "));
    println!("pairwise matrix");
    for (i, row) in report.matrix.iter().enumerate() {
        println!("  {:>10} {:?}", report.options[i], row);
    }
    println!("schulze winners {}", report.schulze_winners.join(", "));

    let mut ok = true;

    if let Some(matched) = report.closure_hash_agrees {
        println!("closure hash    {}", if matched { "AGREES" } else { "DIFFERS" });
        ok &= matched;
    }

    if report.schulze_winners.len() > 1 {
        match &report.tiebreak_order {
            Some(drawn) => println!("tie-break order {}", drawn.join(", ")),
            None => println!(
                "tie among {} options; pass --opening-seed to resolve",
                report.schulze_winners.len()
            ),
        }
    }

    if let Some(matched) = report.winner_agrees {
        println!("winner          {}", if matched { "AGREES" } else { "DIFFERS" });
        ok &= matched;
    }

    if ok {
        ExitCode::SUCCESS
    } else {
        ExitCode::from(1)
    }
}
