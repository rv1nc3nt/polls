// SPDX-License-Identifier: 0BSD
//! The verification workflow shared by the CLI and the GUI: parse the
//! published CSV, recompute the closure hash and the Schulze result, and
//! compare against whatever the caller expects. Neither binary re-derives
//! this logic; both call [`verify`] and differ only in how they render the
//! resulting [`Report`].

use crate::canonical::{canonical_serialisation, options_in, parse_csv, parse_hex};
use crate::schulze;
use crate::sha256::{hex, sha256};

/// What the caller already believes, typically read off the public results
/// page, to be checked against the recomputation.
#[derive(Default)]
pub struct Expected<'a> {
    pub closure_hash: Option<&'a str>,
    pub opening_seed: Option<&'a str>,
    pub winner: Option<&'a str>,
}

pub struct Report {
    pub ballot_count: usize,
    pub closure_hash: String,
    pub options: Vec<String>,
    pub matrix: Vec<Vec<u32>>,
    pub schulze_winners: Vec<String>,
    /// `Some` only once an opening seed resolved a tie (§8.3).
    pub tiebreak_order: Option<Vec<String>>,
    pub final_winner: Option<String>,
    /// `None` when the caller passed no expected value to compare against.
    pub closure_hash_agrees: Option<bool>,
    pub winner_agrees: Option<bool>,
}

pub enum VerifyError {
    Csv(String),
    OpeningSeedNotHex,
}

pub fn verify(csv_text: &str, expected: &Expected) -> Result<Report, VerifyError> {
    let ballots = parse_csv(csv_text).map_err(VerifyError::Csv)?;
    let serialised = canonical_serialisation(&ballots);
    let hash = sha256(&serialised);
    let closure_hash = hex(&hash);
    let options = options_in(&ballots);
    let rankings: Vec<Vec<Vec<String>>> = ballots.iter().map(|b| b.ranking.clone()).collect();
    let matrix = schulze::pairwise(&rankings, &options);
    let paths = schulze::strongest_paths(&matrix, &options);
    let schulze_winners = schulze::winners(&paths, &options);

    // A tie with no opening seed has no resolved winner (§8.3): leaving
    // `final_winner` at an arbitrary tied option here would let a `winner`
    // comparison agree or disagree with it by chance, which is worse than
    // refusing to judge. `tiebreak_order.is_none()` alongside a multi-winner
    // `schulze_winners` is how callers present that — the CLI's "tie among N
    // options; pass --opening-seed to resolve".
    let mut final_winner =
        if schulze_winners.len() == 1 { schulze_winners.first().cloned() } else { None };
    let mut tiebreak_order = None;
    if schulze_winners.len() > 1 {
        if let Some(seed_hex) = expected.opening_seed {
            let seed = parse_hex(seed_hex).ok_or(VerifyError::OpeningSeedNotHex)?;
            let drawn = schulze::tiebreak(&schulze_winners, &seed, &hash);
            final_winner = drawn.first().cloned();
            tiebreak_order = Some(drawn);
        }
    }

    let closure_hash_agrees =
        expected.closure_hash.map(|expected| expected.trim().eq_ignore_ascii_case(&closure_hash));
    let winner_agrees = expected.winner.map(|expected| final_winner.as_deref() == Some(expected));

    Ok(Report {
        ballot_count: ballots.len(),
        closure_hash,
        options,
        matrix,
        schulze_winners,
        tiebreak_order,
        final_winner,
        closure_hash_agrees,
        winner_agrees,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    const CYCLIC: &str = "tracking_code,ranking\n\
        AAAAAAAAAA,\"[[\"\"a\"\"],[\"\"b\"\"],[\"\"c\"\"]]\"\n\
        BBBBBBBBBB,\"[[\"\"b\"\"],[\"\"c\"\"],[\"\"a\"\"]]\"\n\
        CCCCCCCCCC,\"[[\"\"c\"\"],[\"\"a\"\"],[\"\"b\"\"]]\"\n";

    #[test]
    fn unresolved_tie_never_agrees_with_a_winner_by_chance() {
        // A winner comparison against an unresolved tie must always refuse,
        // not agree or disagree depending on which tied option happened to
        // sort first — that was the bug this module was extracted to fix.
        let report = verify(CYCLIC, &Expected { winner: Some("a"), ..Default::default() })
            .ok()
            .expect("parses");
        assert_eq!(report.schulze_winners.len(), 3);
        assert!(report.tiebreak_order.is_none());
        assert!(report.final_winner.is_none());
        assert_eq!(report.winner_agrees, Some(false));
    }

    #[test]
    fn opening_seed_resolves_the_tie_and_then_a_winner_can_agree() {
        let opening_seed = "00".repeat(32);
        let closure_hash = verify(CYCLIC, &Expected::default()).ok().expect("parses").closure_hash;
        let expected = Expected {
            opening_seed: Some(&opening_seed),
            winner: None,
            closure_hash: Some(&closure_hash),
        };
        let report = verify(CYCLIC, &expected).ok().expect("parses");
        let drawn = report.tiebreak_order.expect("tie resolved");
        assert_eq!(report.final_winner.as_deref(), drawn.first().map(String::as_str));
    }
}
