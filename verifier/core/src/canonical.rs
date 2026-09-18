// SPDX-License-Identifier: 0BSD
//! Parsing the published CSV and the canonical serialisation of the live
//! ballot set (`docs/canonical-serialisation.md`, §9). Shared by the CLI and
//! the GUI so there is exactly one Rust implementation of this grammar.

use std::collections::BTreeSet;

/// One row of the published CSV: a tracking code and a ranking.
pub struct Ballot {
    pub tracking_code: String,
    /// Groups of option ids, outer order significant, inner order not.
    pub ranking: Vec<Vec<String>>,
}

/// Parse the two-column published CSV (§9). The header is `tracking_code,ranking`
/// and the ranking cell is the canonical JSON array of arrays.
pub fn parse_csv(text: &str) -> Result<Vec<Ballot>, String> {
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

pub fn options_in(ballots: &[Ballot]) -> Vec<String> {
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

pub fn parse_hex(text: &str) -> Option<Vec<u8>> {
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
    use crate::sha256::{hex, sha256};

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
