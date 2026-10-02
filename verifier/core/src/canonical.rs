// SPDX-License-Identifier: 0BSD
//! Parsing the published CSV and the canonical serialisation of the live
//! ballot set (`docs/canonical-serialisation.md`, §9). Shared by the CLI and
//! the GUI so there is exactly one Rust implementation of this grammar.

use std::collections::BTreeSet;

/// One row of the published CSV: a tracking code and a ranking.
pub struct Ballot {
    /// The ballot's tracking code, checked against [`TRACKING_CODE_ALPHABET`].
    pub tracking_code: String,
    /// Groups of option ids, outer order significant, inner order not.
    pub ranking: Vec<Vec<String>>,
}

/// The CSV's first line, exactly as the application writes it.
pub const CSV_HEADER: &str = "tracking_code,ranking";

/// Parse the two-column published CSV (§9): the header, then one row per
/// ballot — a bare tracking code, a comma, and the ranking as a quoted CSV
/// field holding the canonical JSON array of arrays.
///
/// Strict on purpose (review B-6): anything the application cannot write is
/// refused, with its line, rather than read leniently into a ballot no poll
/// cast. The cell is read by the same strict JSON reader as the publication
/// document; what makes a ranking admissible is `check_ranking`, applied to
/// both.
///
/// # Errors
///
/// A message naming the first line that is not what the application writes.
pub fn parse_csv(text: &str) -> Result<Vec<Ballot>, String> {
    let mut lines = text.lines().enumerate();
    match lines.next() {
        Some((_, header)) if header == CSV_HEADER => {}
        _ => return Err(format!("line 1: expected the header {CSV_HEADER}")),
    }
    let mut ballots = Vec::new();
    for (index, line) in lines {
        let number = index + 1;
        if line.is_empty() {
            continue;
        }
        let (code, cell) = split_row(line).ok_or_else(|| {
            format!("line {number}: expected a tracking code, a comma and a quoted ranking")
        })?;
        let ranking = crate::json::parse(&cell)
            .and_then(|value| ranking_from_json(&value))
            .map_err(|why| format!("line {number}: {why}"))?;
        ballots.push(Ballot {
            tracking_code: code.to_string(),
            ranking,
        });
    }
    Ok(ballots)
}

/// Split `code,"cell"`: the code bare, the cell a quoted CSV field in which
/// every quote is doubled — which is all a CSV writer ever produces for it.
fn split_row(line: &str) -> Option<(&str, String)> {
    let (code, rest) = line.split_once(',')?;
    let quoted = rest.strip_prefix('"')?.strip_suffix('"')?;
    if quoted.replace("\"\"", "").contains('"') {
        return None;
    }
    Some((code, quoted.replace("\"\"", "\"")))
}

/// A ranking from its JSON form: a list of groups, each a list of option ids.
///
/// # Errors
///
/// A message saying which level of the structure is not what it must be.
pub fn ranking_from_json(value: &crate::json::Value) -> Result<Vec<Vec<String>>, String> {
    let groups = value.as_array().ok_or("the ranking is not a list")?;
    groups
        .iter()
        .map(|group| {
            group
                .as_array()
                .ok_or("a group of the ranking is not a list")?
                .iter()
                .map(|option| {
                    option
                        .as_str()
                        .map(String::from)
                        .ok_or_else(|| "an option id is not a string".to_string())
                })
                .collect()
        })
        .collect()
}

/// Whether a ranking is one the application could have recorded: it places
/// at least one option, has no empty group and ranks no option twice — the
/// rules a ballot is refused under before it is ever stored
/// (`docs/canonical-serialisation.md`, "A ranking").
///
/// # Errors
///
/// The first rule it breaks, in words.
pub fn check_ranking(ranking: &[Vec<String>]) -> Result<(), String> {
    if ranking.iter().all(Vec::is_empty) {
        return Err("it places no option".to_string());
    }
    if ranking.iter().any(Vec::is_empty) {
        return Err("it has an empty group".to_string());
    }
    let mut seen = BTreeSet::new();
    for option in ranking.iter().flatten() {
        if option.is_empty() {
            return Err("an option id is empty".to_string());
        }
        if !seen.insert(option.as_str()) {
            return Err(format!("it ranks {option} twice"));
        }
    }
    Ok(())
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
/// Every tracking code is exactly this many characters of the alphabet.
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
///
/// # Errors
///
/// The first malformed code, or the first code seen twice.
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
    fn the_csv_is_read_strictly() {
        let ok = "tracking_code,ranking\nAAAAAAAAAA,\"[[\"\"a\"\"],[\"\"b\"\",\"\"c\"\"]]\"\n";
        let ballots = parse_csv(ok).expect("parses");
        assert_eq!(
            ballots[0].ranking,
            vec![vec!["a".to_string()], vec!["b".into(), "c".into()]]
        );
        assert_eq!(
            parse_csv("tracking_code,ranking\r\n").map(|b| b.len()),
            Ok(0)
        );
        for bad in [
            "",
            "AAAAAAAAAA,\"[[\"\"a\"\"]]\"\n", // no header
            "code,ranking\n",                 // wrong header
            "tracking_code,ranking\nAAAAAAAAAA,[[\"a\"]]\n", // cell not quoted
            "tracking_code,ranking\nAAAAAAAAAA,\"[[a]]\"\n", // unquoted id
            "tracking_code,ranking\nAAAAAAAAAA,\"[[\"\"a\"\",]]\"\n", // trailing comma
            "tracking_code,ranking\nAAAAAAAAAA,\"[[\"\"a\"\"]]\",x\n", // a third column
            "tracking_code,ranking\nAAAAAAAAAA,\"[[1]]\"\n", // id not a string
            "tracking_code,ranking\nAAAAAAAAAA,\"[\"\"a\"\"]\"\n", // group not a list
        ] {
            assert!(parse_csv(bad).is_err(), "accepted {bad:?}");
        }
    }

    #[test]
    fn a_ranking_must_be_one_the_application_could_record() {
        let r = |groups: &[&[&str]]| -> Vec<Vec<String>> {
            groups
                .iter()
                .map(|g| g.iter().map(|o| (*o).to_string()).collect())
                .collect()
        };
        assert_eq!(check_ranking(&r(&[&["a"], &["b", "c"]])), Ok(()));
        assert!(check_ranking(&r(&[])).is_err());
        assert!(check_ranking(&r(&[&[]])).is_err());
        assert!(check_ranking(&r(&[&["a"], &[]])).is_err());
        assert!(check_ranking(&r(&[&["a"], &["a"]])).is_err());
        assert!(check_ranking(&r(&[&["a", "a"]])).is_err());
        assert!(check_ranking(&r(&[&[""]])).is_err());
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
