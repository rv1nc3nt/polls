// SPDX-License-Identifier: 0BSD
//! The shared publication-document vectors (`tests/vectors/documents/`,
//! review D-1), run against this crate. Each case is a base document worked
//! out by hand, one edit to it, the values a reader noted, and the verdict
//! the verifier must reach, with exactly which checks disagree. pytest runs
//! the same file: the application's writer must produce each base document,
//! and the command line must end on each case's exit code
//! (`tests/integration/test_vectors.py`, `test_verifier_agreement.py`).

use std::fmt::Write as _;
use std::path::Path;

use polls_verifier_core::json::{self, Value};
use polls_verifier_core::report::{verify_publication, Anchors, PublicationReport, Verdict};

fn corpus() -> Value {
    let path = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../../tests/vectors/documents/publications.json");
    let text = std::fs::read_to_string(&path).unwrap_or_else(|e| panic!("{}: {e}", path.display()));
    json::parse(&text).unwrap_or_else(|e| panic!("{}: {e}", path.display()))
}

/// The core's `Value` is read-only; a case edits a copy of its base.
fn copy(value: &Value) -> Value {
    match value {
        Value::Null => Value::Null,
        Value::Bool(b) => Value::Bool(*b),
        Value::Number(n) => Value::Number(n.clone()),
        Value::String(s) => Value::String(s.clone()),
        Value::Array(items) => Value::Array(items.iter().map(copy).collect()),
        Value::Object(members) => {
            Value::Object(members.iter().map(|(k, v)| (k.clone(), copy(v))).collect())
        }
    }
}

/// The member or item a path step names, for writing.
fn step<'a>(value: &'a mut Value, key: &Value) -> &'a mut Value {
    match (value, key) {
        (Value::Object(members), Value::String(name)) => {
            if !members.iter().any(|(k, _)| k == name) {
                members.push((name.clone(), Value::Null));
            }
            &mut members
                .iter_mut()
                .find(|(k, _)| k == name)
                .expect("just ensured")
                .1
        }
        (Value::Array(items), Value::Number(_)) => {
            let index = usize::try_from(key.as_u64().expect("an index")).expect("an index");
            &mut items[index]
        }
        (_, key) => panic!("no step {key:?} into this value"),
    }
}

fn apply(document: &mut Value, edit: &Value) {
    if let Some(path) = edit.get("set").and_then(Value::as_array) {
        let mut target = document;
        for key in path {
            target = step(target, key);
        }
        *target = copy(edit.get("value").expect("a value"));
    } else if let Some(path) = edit.get("remove").and_then(Value::as_array) {
        let (last, parents) = path.split_last().expect("a non-empty path");
        let mut target = document;
        for key in parents {
            target = step(target, key);
        }
        let (Value::Object(members), Some(name)) = (target, last.as_str()) else {
            panic!("only an object member can be removed");
        };
        members.retain(|(k, _)| k != name);
    } else if let Some(name) = edit.get("append_member").and_then(Value::as_str) {
        // A key the document already has: the one edit a parser must refuse.
        let Value::Object(members) = document else {
            panic!("the document is an object");
        };
        members.push((name.to_string(), copy(edit.get("value").expect("a value"))));
    } else {
        panic!("unknown edit {edit:?}");
    }
}

fn write(value: &Value, out: &mut String) {
    match value {
        Value::Null => out.push_str("null"),
        Value::Bool(b) => out.push_str(if *b { "true" } else { "false" }),
        Value::Number(n) => out.push_str(n),
        Value::String(s) => {
            out.push('"');
            for c in s.chars() {
                match c {
                    '"' => out.push_str("\\\""),
                    '\\' => out.push_str("\\\\"),
                    c if u32::from(c) < 0x20 => {
                        write!(out, "\\u{:04x}", u32::from(c)).expect("a String");
                    }
                    c => out.push(c),
                }
            }
            out.push('"');
        }
        Value::Array(items) => {
            out.push('[');
            for (i, item) in items.iter().enumerate() {
                if i > 0 {
                    out.push(',');
                }
                write(item, out);
            }
            out.push(']');
        }
        Value::Object(members) => {
            out.push('{');
            for (i, (key, item)) in members.iter().enumerate() {
                if i > 0 {
                    out.push(',');
                }
                write(&Value::String(key.clone()), out);
                out.push(':');
                write(item, out);
            }
            out.push('}');
        }
    }
}

/// The checks that disagree, by the corpus's names for them.
fn differing(report: &PublicationReport) -> Vec<&'static str> {
    let checks = [
        ("closure_hash", report.report.closure_hash_agrees),
        ("ballot_count", Some(report.ballot_count_agrees)),
        ("matrix", Some(report.matrix_agrees)),
        ("derivation", report.derivation_agrees),
        ("orderings", report.orderings_agree),
        ("counts", report.counts_agree),
        ("tiebreak", report.tiebreak_agrees),
        ("winner", report.report.winner_agrees),
        ("participation", Some(report.participation_agrees)),
        ("hash_at_closure", report.closure_hash_anchor),
        ("seed_at_opening", report.opening_seed_anchor),
    ];
    let mut names: Vec<&str> = checks
        .into_iter()
        .filter(|(_, agrees)| *agrees == Some(false))
        .map(|(name, _)| name)
        .collect();
    names.sort_unstable();
    names
}

fn run(corpus: &Value, case: &Value) -> Result<(), String> {
    let name = case.get("name").and_then(Value::as_str).expect("a name");
    let base = case.get("base").and_then(Value::as_str).expect("a base");
    let mut document = copy(
        corpus
            .get("bases")
            .and_then(|bases| bases.get(base))
            .and_then(|b| b.get("document"))
            .unwrap_or_else(|| panic!("{name}: no base {base}")),
    );
    for edit in case.get("edits").and_then(Value::as_array).expect("edits") {
        apply(&mut document, edit);
    }
    let mut text = String::new();
    write(&document, &mut text);

    let anchors = case.get("anchors").expect("anchors");
    let anchors = Anchors {
        closure_hash: anchors.get("closure_hash").and_then(Value::as_str),
        opening_seed: anchors.get("opening_seed").and_then(Value::as_str),
    };
    let expected = case
        .get("verdict")
        .and_then(Value::as_str)
        .expect("a verdict");
    let (verdict, differs) = match verify_publication(&text, &anchors) {
        Err(_) => ("refused", Vec::new()),
        Ok(report) => {
            let verdict = match report.verdict() {
                Verdict::Verified => "verified",
                Verdict::NotAnchored => "not_anchored",
                Verdict::Differs => "differs",
            };
            (verdict, differing(&report))
        }
    };
    let expected_differs: Vec<String> = case
        .get("differs")
        .and_then(Value::as_array)
        .map(|items| {
            items
                .iter()
                .map(|i| i.as_str().expect("a check").to_string())
                .collect()
        })
        .unwrap_or_default();
    if verdict == expected && differs == expected_differs {
        Ok(())
    } else {
        Err(format!(
            "{name}: expected {expected} {expected_differs:?}, got {verdict} {differs:?}"
        ))
    }
}

#[test]
fn every_document_vector_reaches_its_verdict() {
    let corpus = corpus();
    assert_eq!(corpus.get("format").and_then(Value::as_u64), Some(1));
    let cases = corpus
        .get("cases")
        .and_then(Value::as_array)
        .expect("cases");
    assert!(!cases.is_empty());
    let failures: Vec<String> = cases
        .iter()
        .filter_map(|case| run(&corpus, case).err())
        .collect();
    assert!(
        failures.is_empty(),
        "{} of {} disagree:\n{}",
        failures.len(),
        cases.len(),
        failures.join("\n")
    );
}
