// SPDX-License-Identifier: 0BSD
//! The shared vector corpus (`tests/vectors/`, review D-2), run against this
//! crate. pytest runs the same files against the application
//! (`tests/integration/test_vectors.py`), so both implementations answer to
//! one set of expectations rather than each to its own copy.
//!
//! `POLLS_EXTRA_VECTORS` names one more file of the same format: the seeded
//! random cases `tests/integration/test_differential.py` writes, with the
//! application's own results as expectations.

use std::path::{Path, PathBuf};

use polls_verifier_core::canonical::Ballot;
use polls_verifier_core::counted::Method;
use polls_verifier_core::json::{self, Value};
use polls_verifier_core::report::{verify_ballots, Expected, VerifyError};

fn corpus_files() -> Vec<PathBuf> {
    let dir = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../tests/vectors");
    let mut files: Vec<PathBuf> = std::fs::read_dir(&dir)
        .unwrap_or_else(|e| panic!("{}: {e}", dir.display()))
        .map(|entry| entry.expect("a directory entry").path())
        .filter(|path| path.extension().is_some_and(|ext| ext == "json"))
        .collect();
    files.sort();
    assert!(!files.is_empty(), "no vector file in {}", dir.display());
    if let Some(extra) = std::env::var_os("POLLS_EXTRA_VECTORS") {
        files.push(PathBuf::from(extra));
    }
    files
}

fn string(value: &Value, key: &str) -> String {
    value
        .get(key)
        .and_then(Value::as_str)
        .unwrap_or_else(|| panic!("missing string {key}"))
        .to_string()
}

fn strings(value: &Value) -> Vec<String> {
    value
        .as_array()
        .expect("a list")
        .iter()
        .map(|item| item.as_str().expect("a string").to_string())
        .collect()
}

fn ballots(case: &Value) -> Vec<Ballot> {
    case.get("ballots")
        .and_then(Value::as_array)
        .expect("ballots")
        .iter()
        .map(|ballot| Ballot {
            tracking_code: string(ballot, "tracking_code"),
            ranking: ballot
                .get("ranking")
                .and_then(Value::as_array)
                .expect("ranking")
                .iter()
                .map(strings)
                .collect(),
        })
        .collect()
}

fn sorted(mut items: Vec<String>) -> Vec<String> {
    items.sort();
    items
}

/// One case: `Ok(())`, or what differs, prefixed with the case's name.
fn run(case: &Value) -> Result<(), String> {
    let name = string(case, "name");
    let options = strings(case.get("options").expect("options"));
    let method = Method::parse(&string(case, "method")).expect("a method");
    let seed = case.get("opening_seed").and_then(Value::as_str);
    let expected = Expected {
        method,
        options: Some(&options),
        opening_seed: seed,
        ..Expected::default()
    };
    let outcome = verify_ballots(&ballots(case), &expected);

    if let Some(refuse) = case.get("refuse").and_then(Value::as_str) {
        let refused = matches!(
            (&outcome, refuse),
            (Err(VerifyError::MalformedTrackingCode(_)), "tracking_code")
                | (
                    Err(VerifyError::DuplicateTrackingCode(_)),
                    "duplicate_tracking_code"
                )
                | (
                    Err(VerifyError::MalformedRanking(..)),
                    "ranking" | "option_id"
                )
                | (Err(VerifyError::MalformedOptionId(_)), "listed_option_id")
        );
        return if refused {
            Ok(())
        } else {
            Err(format!(
                "{name}: expected a {refuse} refusal, got {:?}",
                outcome.err()
            ))
        };
    }

    let report = outcome.map_err(|e| format!("{name}: refused: {e:?}"))?;
    let expect = case.get("expect").expect("expect");
    let mut wrong = Vec::new();
    if report.closure_hash != string(expect, "closure_hash") {
        wrong.push(format!("closure hash {}", report.closure_hash));
    }
    let matrix = expect.get("matrix").expect("matrix");
    for (i, row) in report.options.iter().zip(&report.matrix) {
        for (j, n) in report.options.iter().zip(row) {
            if i == j {
                continue;
            }
            let want = matrix.get(i).and_then(|r| r.get(j)).and_then(Value::as_u64);
            if want != Some(u64::from(*n)) {
                wrong.push(format!("d[{i}][{j}] = {n}, expected {want:?}"));
            }
        }
    }
    let winners = strings(expect.get("winners").expect("winners"));
    if sorted(report.winners.clone()) != winners {
        wrong.push(format!(
            "winners {:?}, expected {winners:?}",
            report.winners
        ));
    }
    match (expect.get("counts"), &report.counts) {
        (Some(Value::Null) | None, None) => {}
        (Some(counts @ Value::Object(_)), Some(got)) => {
            for (option, n) in report.options.iter().zip(got) {
                if counts.get(option).and_then(Value::as_u64) != Some(u64::from(*n)) {
                    wrong.push(format!("count of {option} = {n}"));
                }
            }
        }
        (want, got) => wrong.push(format!("counts {got:?}, expected {want:?}")),
    }
    let order = match expect.get("tiebreak_order") {
        Some(Value::Null) | None => None,
        Some(list) => Some(strings(list)),
    };
    if report.tiebreak_order != order {
        wrong.push(format!(
            "tie-break order {:?}, expected {order:?}",
            report.tiebreak_order
        ));
    }
    if wrong.is_empty() {
        Ok(())
    } else {
        Err(format!("{name}: {}", wrong.join("; ")))
    }
}

#[test]
fn every_vector_agrees() {
    let mut failures = Vec::new();
    let mut count = 0;
    for path in corpus_files() {
        let text =
            std::fs::read_to_string(&path).unwrap_or_else(|e| panic!("{}: {e}", path.display()));
        let document = json::parse(&text).unwrap_or_else(|e| panic!("{}: {e}", path.display()));
        assert_eq!(document.get("format").and_then(Value::as_u64), Some(1));
        for case in document
            .get("cases")
            .and_then(Value::as_array)
            .expect("cases")
        {
            count += 1;
            if let Err(failure) = run(case) {
                failures.push(format!("{}: {failure}", path.display()));
            }
        }
    }
    assert!(count > 0);
    assert!(
        failures.is_empty(),
        "{} of {count} disagree:\n{}",
        failures.len(),
        failures.join("\n")
    );
}
