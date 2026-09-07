// SPDX-License-Identifier: 0BSD
//! Independent verifier for the commune polling platform (§8, §9, §14).
//!
//! It reads only the published CSV, never the database, and recomputes the
//! canonical serialisation, the closure hash, the pairwise matrix, the Schulze
//! winner and the tie-break. It was written from
//! `docs/canonical-serialisation.md` and §8 of the specification, and shares no
//! code with the Python implementation — a property the language boundary
//! enforces structurally.
//!
//! When the two disagree, the resolution is to return to the specification and
//! determine which is wrong, never to adjust this binary until it matches.
//!
//! Usage:
//!
//!     polls-verifier ballots.csv \
//!         [--closure-hash <hex>] [--opening-seed <hex>] [--winner <option_id>]
//!
//! Exit codes: 0 agreement, 1 disagreement, 2 usage or input error.

mod schulze;
mod sha256;

use std::collections::BTreeSet;
use std::process::ExitCode;

use sha256::{hex, sha256};

/// One row of the published CSV: a tracking code and a ranking.
pub struct Ballot {
    pub tracking_code: String,
    /// Groups of option ids, outer order significant, inner order not.
    pub ranking: Vec<Vec<String>>,
}

/// Parse the two-column published CSV (§9). The header is `tracking_code,ranking`
/// and the ranking cell is the canonical JSON array of arrays.
fn parse_csv(text: &str) -> Result<Vec<Ballot>, String> {
    let mut ballots = Vec::new();
    for (lineno, line) in text.lines().enumerate() {
        if line.trim().is_empty() {
            continue;
        }
        if lineno == 0 && line.starts_with("tracking_code") {
            continue;
        }
        let (code, ranking) = split_row(line)
            .ok_or_else(|| format!("line {}: expected two columns", lineno + 1))?;
        ballots.push(Ballot {
            tracking_code: code,
            ranking: parse_ranking(&ranking)
                .ok_or_else(|| format!("line {}: malformed ranking", lineno + 1))?,
        });
    }
    Ok(ballots)
}

/// Split `code,ranking`, honouring the doubled-quote escaping a CSV writer uses
/// for the JSON cell.
fn split_row(line: &str) -> Option<(String, String)> {
    let comma = line.find(',')?;
    let (code, rest) = line.split_at(comma);
    let rest = &rest[1..];
    let ranking = if let Some(stripped) = rest.strip_prefix('"') {
        stripped.strip_suffix('"')?.replace("\"\"", "\"")
    } else {
        rest.to_string()
    };
    Some((code.trim().to_string(), ranking))
}

/// Read `[["a"],["b","c"]]` without a JSON library: the grammar is fixed by
/// the canonical serialisation and nothing else may appear in the cell.
fn parse_ranking(cell: &str) -> Option<Vec<Vec<String>>> {
    let inner = cell.trim().strip_prefix('[')?.strip_suffix(']')?;
    let mut groups = Vec::new();
    let mut rest = inner.trim();
    while !rest.is_empty() {
        let group = rest.strip_prefix('[')?;
        let end = group.find(']')?;
        let items: Vec<String> = group[..end]
            .split(',')
            .filter(|s| !s.trim().is_empty())
            .map(|s| s.trim().trim_matches('"').to_string())
            .collect();
        groups.push(items);
        rest = group[end + 1..].trim_start().trim_start_matches(',').trim_start();
    }
    Some(groups)
}

/// The canonical serialisation of the live set, byte for byte
/// (`docs/canonical-serialisation.md`).
pub fn canonical_serialisation(ballots: &[Ballot]) -> Vec<u8> {
    let mut records: Vec<Vec<u8>> = ballots
        .iter()
        .map(|b| {
            let mut groups: Vec<String> = Vec::new();
            for group in &b.ranking {
                let mut sorted: Vec<&String> = group.iter().collect();
                sorted.sort();
                let items: Vec<String> = sorted.iter().map(|o| format!("\"{o}\"")).collect();
                groups.push(format!("[{}]", items.join(",")));
            }
            format!(
                "{{\"tracking_code\":\"{}\",\"ranking\":[{}]}}",
                b.tracking_code,
                groups.join(",")
            )
            .into_bytes()
        })
        .collect();
    // Sorted by tracking code, comparing UTF-8 bytes; the record starts with a
    // fixed prefix, so sorting the rendered lines is the same ordering.
    records.sort();
    let mut out = Vec::new();
    for record in records {
        out.extend_from_slice(&record);
        out.push(b'\n');
    }
    out
}

fn options_in(ballots: &[Ballot]) -> Vec<String> {
    let mut set = BTreeSet::new();
    for ballot in ballots {
        for group in &ballot.ranking {
            for option in group {
                set.insert(option.clone());
            }
        }
    }
    set.into_iter().collect()
}

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
    let ballots = match parse_csv(&text) {
        Ok(ballots) => ballots,
        Err(err) => {
            eprintln!("{err}");
            return ExitCode::from(2);
        }
    };

    let serialised = canonical_serialisation(&ballots);
    let hash = sha256(&serialised);
    let options = options_in(&ballots);
    let rankings: Vec<Vec<Vec<String>>> = ballots.iter().map(|b| b.ranking.clone()).collect();
    let matrix = schulze::pairwise(&rankings, &options);
    let paths = schulze::strongest_paths(&matrix, &options);
    let winners = schulze::winners(&paths, &options);

    println!("ballots        {}", ballots.len());
    println!("closure_hash   {}", hex(&hash));
    println!("options        {}", options.join(", "));
    println!("pairwise matrix");
    for (i, row) in matrix.iter().enumerate() {
        println!("  {:>10} {:?}", options[i], row);
    }
    println!("schulze winners {}", winners.join(", "));

    let mut ok = true;

    if let Some(expected) = arg_value(&args, "--closure-hash") {
        let matched = expected.trim().eq_ignore_ascii_case(&hex(&hash));
        println!("closure hash    {}", if matched { "AGREES" } else { "DIFFERS" });
        ok &= matched;
    }

    let mut final_winner = winners.first().cloned();
    if winners.len() > 1 {
        match arg_value(&args, "--opening-seed") {
            Some(seed_hex) => match parse_hex(&seed_hex) {
                Some(seed) => {
                    let drawn = schulze::tiebreak(&winners, &seed, &hash);
                    println!("tie-break order {}", drawn.join(", "));
                    final_winner = drawn.first().cloned();
                }
                None => {
                    eprintln!("--opening-seed must be hex");
                    return ExitCode::from(2);
                }
            },
            None => println!("tie among {} options; pass --opening-seed to resolve", winners.len()),
        }
    }

    if let Some(expected) = arg_value(&args, "--winner") {
        let matched = final_winner.as_deref() == Some(expected.as_str());
        println!("winner          {}", if matched { "AGREES" } else { "DIFFERS" });
        ok &= matched;
    }

    if ok {
        ExitCode::SUCCESS
    } else {
        ExitCode::from(1)
    }
}

fn parse_hex(text: &str) -> Option<Vec<u8>> {
    let text = text.trim();
    if text.len() % 2 != 0 {
        return None;
    }
    (0..text.len())
        .step_by(2)
        .map(|i| u8::from_str_radix(&text[i..i + 2], 16).ok())
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn worked_vector_from_the_documentation() {
        let ballots = parse_csv(
            "tracking_code,ranking\n\
             AAAAAAAAAA,\"[[\"\"a\"\"],[\"\"b\"\"],[\"\"c\"\"]]\"\n\
             BBBBBBBBBB,\"[[\"\"c\"\"],[\"\"b\"\"],[\"\"a\"\"]]\"\n",
        )
        .expect("parses");
        assert_eq!(ballots.len(), 2);
        assert_eq!(
            String::from_utf8(canonical_serialisation(&ballots)).unwrap(),
            "{\"tracking_code\":\"AAAAAAAAAA\",\"ranking\":[[\"a\"],[\"b\"],[\"c\"]]}\n\
             {\"tracking_code\":\"BBBBBBBBBB\",\"ranking\":[[\"c\"],[\"b\"],[\"a\"]]}\n"
        );
        assert_eq!(
            hex(&sha256(&canonical_serialisation(&ballots))),
            "87694cf068ba44eca50e15bd4b7c1195fc4a1fae9ad3b0ba640deec22f7948e6"
        );
    }
}
