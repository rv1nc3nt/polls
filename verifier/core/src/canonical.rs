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
        let (code, ranking) =
            split_row(line).ok_or_else(|| format!("line {}: expected two columns", lineno + 1))?;
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
        rest = group[end + 1..]
            .trim_start()
            .trim_start_matches(',')
            .trim_start();
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

/// The tracking-code alphabet and length (`docs/canonical-serialisation.md`,
/// "The document"): no `O`, `0`, `I` or `1`.
pub const TRACKING_CODE_ALPHABET: &str = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ";
pub const TRACKING_CODE_LENGTH: usize = 10;

/// Why a ballot list cannot be the live set of a poll, whatever its hash.
#[derive(Debug, PartialEq, Eq)]
pub enum BallotListError {
    /// A code outside the alphabet or of the wrong length. The canonical
    /// serialisation does not escape strings, so only codes from the fixed
    /// alphabet are guaranteed to serialise as the application does.
    MalformedTrackingCode(String),
    /// Two ballots share a code. The database refuses this (INV-11); a
    /// published list that has it could hide stuffed ballots behind codes
    /// real voters will still find.
    DuplicateTrackingCode(String),
}

/// Refuse a list no poll could have published: a malformed or repeated
/// tracking code.
pub fn check_tracking_codes(ballots: &[Ballot]) -> Result<(), BallotListError> {
    let mut seen = BTreeSet::new();
    for ballot in ballots {
        let code = &ballot.tracking_code;
        let well_formed = code.len() == TRACKING_CODE_LENGTH
            && code.chars().all(|c| TRACKING_CODE_ALPHABET.contains(c));
        if !well_formed {
            return Err(BallotListError::MalformedTrackingCode(code.clone()));
        }
        if !seen.insert(code.as_str()) {
            return Err(BallotListError::DuplicateTrackingCode(code.clone()));
        }
    }
    Ok(())
}

/// Every option id that appears on at least one ballot, sorted. The CSV
/// carries no option list, so an option no ballot ranks is absent here; a
/// caller who knows the poll's options passes them instead (`Expected::options`
/// in `report`), and the matrix then matches the published one row for row.
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

/// Decode a hexadecimal string (surrounding whitespace ignored); `None` on
/// odd length or any character that is not an ASCII hex digit.
///
/// Byte-wise on purpose: slicing the `str` two bytes at a time panicked when a
/// pasted value held a multi-byte character, and `u8::from_str_radix` accepts
/// a leading `+`, so `"+f"` decoded (review note L6).
pub fn parse_hex(text: &str) -> Option<Vec<u8>> {
    let digits = text.trim().as_bytes();
    if !digits.len().is_multiple_of(2) {
        return None;
    }
    let nibble = |b: u8| (b as char).to_digit(16).filter(|_| b.is_ascii_hexdigit());
    digits
        .chunks(2)
        .map(|pair| Some((nibble(pair[0])? * 16 + nibble(pair[1])?) as u8))
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::sha256::{hex, sha256};

    #[test]
    fn parse_hex_decodes_hex_and_refuses_everything_else() {
        assert_eq!(parse_hex(" 00ff7A "), Some(vec![0x00, 0xff, 0x7a]));
        assert_eq!(parse_hex(""), Some(vec![]));
        assert_eq!(parse_hex("abc"), None);
        assert_eq!(parse_hex("+f"), None);
        assert_eq!(parse_hex("zz"), None);
        assert_eq!(parse_hex("é"), None);
        // Four bytes whose first pair ends inside "é": used to panic.
        assert_eq!(parse_hex("aéb"), None);
    }

    fn ballot(code: &str) -> Ballot {
        Ballot {
            tracking_code: code.to_string(),
            ranking: vec![vec!["a".to_string()]],
        }
    }

    #[test]
    fn tracking_codes_must_be_well_formed_and_unique() {
        assert_eq!(
            check_tracking_codes(&[ballot("AAAAAAAAAA"), ballot("23456789ZZ")]),
            Ok(())
        );
        assert_eq!(check_tracking_codes(&[]), Ok(()));
        for bad in [
            "AAAAAAAAA",
            "AAAAAAAAAAA",
            "AAAAAAAAA0",
            "AAAAAAAAAI",
            "aaaaaaaaaa",
            "AAAA\"AAAAA",
        ] {
            assert_eq!(
                check_tracking_codes(&[ballot(bad)]),
                Err(BallotListError::MalformedTrackingCode(bad.to_string())),
                "{bad}"
            );
        }
        assert_eq!(
            check_tracking_codes(&[
                ballot("AAAAAAAAAA"),
                ballot("BBBBBBBBBB"),
                ballot("AAAAAAAAAA")
            ]),
            Err(BallotListError::DuplicateTrackingCode(
                "AAAAAAAAAA".to_string()
            ))
        );
    }

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
