// SPDX-License-Identifier: 0BSD
//! The verification workflow shared by the CLI and the GUI: parse the
//! published CSV, recompute the closure hash and the result, and compare
//! against whatever the caller expects. Neither binary re-derives this logic;
//! both call [`verify`] and differ only in how they render the resulting
//! [`Report`].
//!
//! The published CSV does not say which method the poll used (R-10.3), so the
//! caller says, from the results page; Schulze when it does not. The winner
//! is only as meaningful as that choice, which the report therefore restates.
//! The closure-hash check is method-independent.

use crate::canonical::{canonical_serialisation, options_in, parse_csv, parse_hex};
use crate::counted::{self, Method};
use crate::schulze;
use crate::sha256::{hex, sha256};

/// What the caller already believes, typically read off the public results
/// page, to be checked against the recomputation.
#[derive(Default)]
pub struct Expected<'a> {
    /// The poll's tally method, as its results page states it.
    pub method: Method,
    /// The poll's option ids, from its results page. Without them the options
    /// are those some ballot ranks, so one nobody ranked is missing from the
    /// matrix and the counts (it cannot win: every ballot ranks something).
    pub options: Option<&'a [String]>,
    pub closure_hash: Option<&'a str>,
    pub opening_seed: Option<&'a str>,
    pub winner: Option<&'a str>,
}

/// Everything [`verify`] recomputed, plus the outcome of each comparison
/// the caller asked for.
pub struct Report {
    pub method: Method,
    pub ballot_count: usize,
    pub closure_hash: String,
    pub options: Vec<String>,
    pub matrix: Vec<Vec<u32>>,
    /// Votes per option, in `options` order; `None` under Schulze.
    pub counts: Option<Vec<u32>>,
    /// The method's winners, in `options` order; more than one is a tie.
    pub winners: Vec<String>,
    /// `Some` only once an opening seed resolved a tie (§8.3).
    pub tiebreak_order: Option<Vec<String>>,
    pub final_winner: Option<String>,
    /// `None` when the caller passed no expected value to compare against.
    pub closure_hash_agrees: Option<bool>,
    pub winner_agrees: Option<bool>,
}

/// Input the verifier cannot work from. Disagreement is not an error: it is
/// reported through the `*_agrees` fields of [`Report`].
pub enum VerifyError {
    /// The CSV did not parse; the message names the line.
    Csv(String),
    /// `Expected::opening_seed` was given but is not hexadecimal.
    OpeningSeedNotHex,
    /// A ballot ranks an option absent from `Expected::options`: the list or
    /// the file is not this poll's.
    UnknownOption(String),
}

/// Recompute the closure hash and the result under `expected.method` from the
/// published CSV alone, then compare them with whatever `expected` supplies.
/// The opening seed is only used when the winners are tied. Pure: no I/O.
pub fn verify(csv_text: &str, expected: &Expected) -> Result<Report, VerifyError> {
    let ballots = parse_csv(csv_text).map_err(VerifyError::Csv)?;
    let serialised = canonical_serialisation(&ballots);
    let hash = sha256(&serialised);
    let closure_hash = hex(&hash);
    let ranked = options_in(&ballots);
    let options = match expected.options {
        None => ranked,
        Some(listed) => {
            if let Some(unknown) = ranked.iter().find(|o| !listed.contains(o)) {
                return Err(VerifyError::UnknownOption(unknown.clone()));
            }
            listed.to_vec()
        }
    };
    let rankings: Vec<Vec<Vec<String>>> = ballots.iter().map(|b| b.ranking.clone()).collect();
    // The pairwise matrix is published for every method, so it is recomputed
    // for every method too.
    let matrix = schulze::pairwise(&rankings, &options);
    let (counts, winners) = match expected.method {
        Method::Schulze => {
            let paths = schulze::strongest_paths(&matrix, &options);
            (None, schulze::winners(&paths, &options))
        }
        method => {
            let counts = counted::counts(&rankings, &options, method);
            let winners = counted::winners(&counts, &options, ballots.len());
            (Some(counts), winners)
        }
    };

    // A tie with no opening seed has no resolved winner (§8.3): leaving
    // `final_winner` at an arbitrary tied option here would let a `winner`
    // comparison agree or disagree with it by chance, which is worse than
    // refusing to judge. `tiebreak_order.is_none()` alongside a multi-winner
    // `winners` is how callers present that — the CLI's "tie among N
    // options; pass --opening-seed to resolve".
    let mut final_winner =
        if winners.len() == 1 { winners.first().cloned() } else { None };
    let mut tiebreak_order = None;
    if winners.len() > 1 {
        if let Some(seed_hex) = expected.opening_seed {
            let seed = parse_hex(seed_hex).ok_or(VerifyError::OpeningSeedNotHex)?;
            let drawn = schulze::tiebreak(&winners, &seed, &hash);
            final_winner = drawn.first().cloned();
            tiebreak_order = Some(drawn);
        }
    }

    let closure_hash_agrees =
        expected.closure_hash.map(|expected| expected.trim().eq_ignore_ascii_case(&closure_hash));
    let winner_agrees = expected.winner.map(|expected| final_winner.as_deref() == Some(expected));

    Ok(Report {
        method: expected.method,
        ballot_count: ballots.len(),
        closure_hash,
        options,
        matrix,
        counts,
        winners,
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
        assert_eq!(report.winners.len(), 3);
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
            ..Default::default()
        };
        let report = verify(CYCLIC, &expected).ok().expect("parses");
        let drawn = report.tiebreak_order.expect("tie resolved");
        assert_eq!(report.final_winner.as_deref(), drawn.first().map(String::as_str));
    }

    /// Three `a > b > c`, two `b > c > a`, two `c > b > a`: plurality elects
    /// `a` (three first places), Schulze elects `b` (beats `a` 4–3 and `c`
    /// 5–2), and approval over complete rankings is a three-way tie.
    const DIVERGENT: &str = "tracking_code,ranking\n\
        AAAAAAAAAA,\"[[\"\"a\"\"],[\"\"b\"\"],[\"\"c\"\"]]\"\n\
        BBBBBBBBBB,\"[[\"\"a\"\"],[\"\"b\"\"],[\"\"c\"\"]]\"\n\
        CCCCCCCCCC,\"[[\"\"a\"\"],[\"\"b\"\"],[\"\"c\"\"]]\"\n\
        DDDDDDDDDD,\"[[\"\"b\"\"],[\"\"c\"\"],[\"\"a\"\"]]\"\n\
        EEEEEEEEEE,\"[[\"\"b\"\"],[\"\"c\"\"],[\"\"a\"\"]]\"\n\
        FFFFFFFFFF,\"[[\"\"c\"\"],[\"\"b\"\"],[\"\"a\"\"]]\"\n\
        GGGGGGGGGG,\"[[\"\"c\"\"],[\"\"b\"\"],[\"\"a\"\"]]\"\n";

    #[test]
    fn the_winner_is_checked_under_the_method_the_poll_used() {
        // Review note M2: an honest plurality result used to read DIFFERS,
        // because it was compared with the Schulze winner.
        let plurality = Expected { method: Method::Plurality, winner: Some("a"), ..Default::default() };
        let report = verify(DIVERGENT, &plurality).ok().expect("parses");
        assert_eq!(report.method, Method::Plurality);
        assert_eq!(report.counts, Some(vec![3, 2, 2]));
        assert_eq!(report.winner_agrees, Some(true));

        let schulze = Expected { winner: Some("a"), ..Default::default() };
        let report = verify(DIVERGENT, &schulze).ok().expect("parses");
        assert_eq!(report.method, Method::Schulze);
        assert_eq!(report.counts, None);
        assert_eq!(report.final_winner.as_deref(), Some("b"));
        assert_eq!(report.winner_agrees, Some(false));
    }

    #[test]
    fn an_approval_tie_goes_to_the_tie_break_like_any_other() {
        let seed = "00".repeat(32);
        let approval = Expected { method: Method::Approval, ..Default::default() };
        let report = verify(DIVERGENT, &approval).ok().expect("parses");
        assert_eq!(report.counts, Some(vec![7, 7, 7]));
        assert_eq!(report.winners.len(), 3);
        assert!(report.final_winner.is_none());

        let seeded = Expected { method: Method::Approval, opening_seed: Some(&seed), ..Default::default() };
        let report = verify(DIVERGENT, &seeded).ok().expect("parses");
        assert!(report.tiebreak_order.is_some());
        assert!(report.final_winner.is_some());
    }

    #[test]
    fn a_listed_option_nobody_ranked_is_in_the_matrix_and_the_counts() {
        // Review note L5: the CSV alone cannot show an unranked option.
        let listed: Vec<String> = ["a", "b", "c", "d"].iter().map(|s| s.to_string()).collect();
        let expected =
            Expected { method: Method::Plurality, options: Some(&listed), ..Default::default() };
        let report = verify(DIVERGENT, &expected).ok().expect("parses");
        assert_eq!(report.options, listed);
        assert_eq!(report.matrix.len(), 4);
        assert_eq!(report.counts, Some(vec![3, 2, 2, 0]));
        assert_eq!(report.winners, vec!["a".to_string()]);
    }

    #[test]
    fn a_ranked_option_missing_from_the_list_is_refused() {
        let listed: Vec<String> = ["a", "b"].iter().map(|s| s.to_string()).collect();
        let expected = Expected { options: Some(&listed), ..Default::default() };
        match verify(DIVERGENT, &expected) {
            Err(VerifyError::UnknownOption(option)) => assert_eq!(option, "c"),
            _ => panic!("expected UnknownOption"),
        }
    }
}
