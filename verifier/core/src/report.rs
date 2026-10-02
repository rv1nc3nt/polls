// SPDX-License-Identifier: 0BSD
//! The verification workflow shared by the CLI and the GUI. Neither binary
//! re-derives this logic; both call one of the two entry points below and
//! differ only in how they render the result.
//!
//! - [`verify_publication`] reads the publication document (`?format=json`,
//!   `docs/publication-format.md`), recomputes everything from its ballots,
//!   and checks every claim the document makes against the recomputation:
//!   closure hash, ballot count, matrix, counts, winner and tie-break. The one
//!   thing it cannot check is the tally method the document states, which
//!   decides what the winner should be; it restates it for the reader to
//!   compare with what the poll announced.
//! - [`verify`] reads the CSV ballot list, which carries neither the method
//!   (R-10.3) nor the option list, so the caller supplies what it wants
//!   compared ([`Expected`]); Schulze when it names no method.
//!
//! The closure-hash check is method-independent either way.

use crate::canonical::{
    canonical_serialisation, check_ranking, check_tracking_codes, is_option_id, options_in,
    parse_csv, parse_hex, Ballot, BallotListError,
};
use crate::counted::{self, Method};
use crate::publication::{parse_publication, Participation, Publication, TiebreakRule};
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
    /// The closure hash to compare with, from the results page.
    pub closure_hash: Option<&'a str>,
    /// The opening seed that settles a tie by the hash chain (§8.3).
    pub opening_seed: Option<&'a str>,
    /// The winner to compare with, from the results page.
    pub winner: Option<&'a str>,
}

/// Everything [`verify`] recomputed, plus the outcome of each comparison
/// the caller asked for.
pub struct Report {
    /// The method the winners were computed under.
    pub method: Method,
    /// Ballots read.
    pub ballot_count: usize,
    /// The closure hash recomputed from the ballots, lower-case hex.
    pub closure_hash: String,
    /// Option ids, in the order of the rows and columns of `matrix`.
    pub options: Vec<String>,
    /// `matrix[i][j]`: ballots ranking option `i` strictly above option `j`.
    pub matrix: Vec<Vec<u32>>,
    /// Votes per option, in `options` order; `None` under Schulze.
    pub counts: Option<Vec<u32>>,
    /// The method's winners, in `options` order; more than one is a tie.
    pub winners: Vec<String>,
    /// `Some` only once an opening seed resolved a tie (§8.3).
    pub tiebreak_order: Option<Vec<String>>,
    /// The single winner once any tie is settled; `None` while one is not.
    pub final_winner: Option<String>,
    /// `None` when the caller passed no expected value to compare against.
    pub closure_hash_agrees: Option<bool>,
    /// `None` when the caller passed no expected winner.
    pub winner_agrees: Option<bool>,
}

/// Input the verifier cannot work from. Disagreement is not an error: it is
/// reported through the `*_agrees` fields of [`Report`].
pub enum VerifyError {
    /// The CSV did not parse; the message names the line.
    Csv(String),
    /// The publication document did not parse or lacks a member it needs;
    /// the message says which.
    Publication(String),
    /// `Expected::opening_seed` was given but is not hexadecimal.
    OpeningSeedNotHex,
    /// A ballot ranks an option absent from `Expected::options`: the list or
    /// the file is not this poll's.
    UnknownOption(String),
    /// A tracking code outside the alphabet, or of the wrong length.
    MalformedTrackingCode(String),
    /// Two ballots carry the same tracking code (INV-11).
    DuplicateTrackingCode(String),
    /// A ballot's ranking is not one the application could record: the
    /// tracking code, then why (`canonical::check_ranking`).
    MalformedRanking(String, String),
    /// An option of `Expected::options` is not an id the application
    /// accepts (`canonical::is_option_id`).
    MalformedOptionId(String),
}

impl From<BallotListError> for VerifyError {
    fn from(err: BallotListError) -> Self {
        match err {
            BallotListError::MalformedTrackingCode(code) => {
                VerifyError::MalformedTrackingCode(code)
            }
            BallotListError::DuplicateTrackingCode(code) => {
                VerifyError::DuplicateTrackingCode(code)
            }
        }
    }
}

/// Recompute the closure hash and the result under `expected.method` from the
/// published CSV alone, then compare them with whatever `expected` supplies.
/// The opening seed is only used when the winners are tied. Pure: no I/O.
///
/// # Errors
///
/// [`VerifyError::Csv`] for a file that does not parse, and otherwise as
/// [`verify_ballots`].
pub fn verify(csv_text: &str, expected: &Expected) -> Result<Report, VerifyError> {
    let ballots = parse_csv(csv_text).map_err(VerifyError::Csv)?;
    verify_ballots(&ballots, expected)
}

/// [`verify`], from ballots already read.
///
/// # Errors
///
/// A list no poll could have published (a malformed or repeated tracking
/// code, a ranking the application never records), an option outside
/// `expected.options`, or an opening seed that is not hexadecimal. A value
/// that merely differs is not an error: it is reported in the [`Report`].
pub fn verify_ballots(ballots: &[Ballot], expected: &Expected) -> Result<Report, VerifyError> {
    check_tracking_codes(ballots)?;
    for ballot in ballots {
        check_ranking(&ballot.ranking)
            .map_err(|why| VerifyError::MalformedRanking(ballot.tracking_code.clone(), why))?;
    }
    let serialised = canonical_serialisation(ballots);
    let hash = sha256(&serialised);
    let closure_hash = hex(&hash);
    let ranked = options_in(ballots);
    let options = match expected.options {
        None => ranked,
        Some(listed) => {
            if let Some(malformed) = listed.iter().find(|o| !is_option_id(o)) {
                return Err(VerifyError::MalformedOptionId(malformed.clone()));
            }
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
        // No ballots, no result (T-39), as the application publishes it:
        // every strongest path is zero, which would otherwise make every
        // option a winner and demand a tie-break the document rightly omits.
        Method::Schulze if ballots.is_empty() => (None, Vec::new()),
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
    let mut final_winner = if winners.len() == 1 {
        winners.first().cloned()
    } else {
        None
    };
    let mut tiebreak_order = None;
    if winners.len() > 1 {
        if let Some(seed_hex) = expected.opening_seed {
            let seed = parse_hex(seed_hex).ok_or(VerifyError::OpeningSeedNotHex)?;
            let drawn = schulze::tiebreak(&winners, &seed, &hash);
            final_winner = drawn.first().cloned();
            tiebreak_order = Some(drawn);
        }
    }

    let closure_hash_agrees = expected
        .closure_hash
        .map(|expected| expected.trim().eq_ignore_ascii_case(&closure_hash));
    let winner_agrees = expected
        .winner
        .map(|expected| final_winner.as_deref() == Some(expected));

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

/// Everything [`verify_publication`] recomputed and checked. `report` holds
/// the recomputation and its hash and winner comparisons; the fields beside
/// it are the checks only the full document makes possible.
pub struct PublicationReport {
    /// The document's layout version.
    pub format_version: String,
    /// The poll's id.
    pub poll_id: String,
    /// The tally method version the document states.
    pub method_version: String,
    /// How the document says a tie was settled; `None` when there was none.
    pub tiebreak_rule: Option<TiebreakRule>,
    /// The recomputation, with its hash and winner compared to the document's.
    pub report: Report,
    /// Whether `ballot_count` equals the number of ballots listed.
    pub ballot_count_agrees: bool,
    /// Whether the published matrix equals the recomputed one, cell for cell.
    pub matrix_agrees: bool,
    /// `None` under Schulze, which publishes no counts.
    pub counts_agree: Option<bool>,
    /// `None` when neither the document nor the recomputation has a tie. For
    /// a physical draw this checks the order is a draw among exactly the
    /// tied options; the draw itself happened at the mairie and is not
    /// something a program can replay.
    pub tiebreak_agrees: Option<bool>,
    /// The participation counts the document states (`counts`).
    pub participation: Participation,
    /// Whether those counts add up (review B-8): the ballots by channel make
    /// the ballot list's count, and registered electors are exactly those who
    /// voted, those whose paper entry went uncounted, and those who did not.
    /// The ballot list cannot say who registered; it can say the counts are
    /// consistent with it, which a stuffed list with untouched counts is not.
    pub participation_agrees: bool,
}

/// The identities `counts` satisfies (`elections.closure.frozen_counts`),
/// checked without overflow: a sum that overflows does not add up.
fn participation_adds_up(counts: &Participation, ballot_count: usize) -> bool {
    let cast = counts.ballots_online.checked_add(counts.ballots_paper);
    let accounted = cast
        .and_then(|n| n.checked_add(counts.paper_uncountersigned))
        .and_then(|n| n.checked_add(counts.non_voters));
    cast == u64::try_from(ballot_count).ok() && accounted == Some(counts.registered)
}

impl PublicationReport {
    /// Every check passed.
    pub fn all_agree(&self) -> bool {
        self.report.closure_hash_agrees != Some(false)
            && self.report.winner_agrees != Some(false)
            && self.ballot_count_agrees
            && self.matrix_agrees
            && self.counts_agree != Some(false)
            && self.tiebreak_agrees != Some(false)
            && self.participation_agrees
    }
}

fn sorted(items: &[String]) -> Vec<String> {
    let mut items = items.to_vec();
    items.sort();
    items
}

/// Does the published `{row: {column: n}}` hold exactly the recomputed values,
/// with no row or cell more or fewer?
fn matrix_matches(publication: &Publication, report: &Report) -> bool {
    let options = &report.options;
    publication.matrix.len() == options.len()
        && options.iter().enumerate().all(|(i, row)| {
            let Some((_, cells)) = publication.matrix.iter().find(|(id, _)| id == row) else {
                return false;
            };
            cells.len() == options.len() - 1
                && options
                    .iter()
                    .enumerate()
                    .filter(|(j, _)| *j != i)
                    .all(|(j, column)| {
                        cells
                            .iter()
                            .any(|(id, n)| id == column && *n == u64::from(report.matrix[i][j]))
                    })
        })
}

/// Recompute everything from the ballots of a publication document, and check
/// every claim it makes. Pure: no I/O.
///
/// # Errors
///
/// [`VerifyError::Publication`] for a document that does not parse or lacks
/// a member, and otherwise as [`verify_ballots`]. A claim that disagrees is
/// not an error: it is reported in the [`PublicationReport`].
pub fn verify_publication(text: &str) -> Result<PublicationReport, VerifyError> {
    let publication = parse_publication(text).map_err(VerifyError::Publication)?;
    let rule = publication.tiebreak.as_ref().map(|t| &t.rule);
    let expected = Expected {
        method: publication.method,
        options: Some(&publication.options),
        closure_hash: Some(&publication.closure_hash),
        // A physical draw is not the hash chain: replaying the chain would
        // produce an order the mairie never drew.
        opening_seed: match rule {
            Some(TiebreakRule::Physical) => None,
            _ => Some(&publication.opening_seed),
        },
        winner: None,
    };
    let mut report = verify_ballots(&publication.ballots, &expected)?;
    let tied = report.winners.len() > 1;

    let tiebreak_agrees = match &publication.tiebreak {
        None => tied.then_some(false),
        Some(tiebreak) => Some(
            tied && sorted(&tiebreak.tied) == sorted(&report.winners)
                // The draw's own winner is its order's first entry; the
                // top-level `winner` is then compared with that, below.
                && tiebreak.winner.as_ref() == tiebreak.order.as_ref().and_then(|o| o.first())
                && match (&tiebreak.rule, &tiebreak.order) {
                    (TiebreakRule::Computed, Some(order)) => {
                        report.tiebreak_order.as_ref() == Some(order)
                    }
                    (TiebreakRule::Physical, Some(order)) => {
                        sorted(order) == sorted(&report.winners)
                    }
                    (_, None) => false,
                },
        ),
    };
    if let Some(tiebreak) = &publication.tiebreak {
        if tiebreak.rule == TiebreakRule::Physical && tiebreak_agrees == Some(true) {
            // The drawn order is the document's to state; checked above to be
            // a draw among exactly the tied options.
            report.final_winner = tiebreak.order.as_ref().and_then(|o| o.first().cloned());
            report.tiebreak_order = tiebreak.order.clone();
        }
    }
    report.winner_agrees = Some(report.final_winner == publication.winner);

    let counts_agree = report
        .counts
        .as_ref()
        .map(|counts| match &publication.counts {
            None => false,
            Some(published) => {
                published.len() == counts.len()
                    && report.options.iter().zip(counts).all(|(option, count)| {
                        published
                            .iter()
                            .any(|(id, n)| id == option && *n == u64::from(*count))
                    })
            }
        });

    Ok(PublicationReport {
        ballot_count_agrees: publication.ballot_count == report.ballot_count as u64,
        participation_agrees: participation_adds_up(
            &publication.participation,
            report.ballot_count,
        ),
        participation: publication.participation,
        matrix_agrees: matrix_matches(&publication, &report),
        counts_agree,
        tiebreak_agrees,
        tiebreak_rule: publication.tiebreak.map(|t| t.rule),
        format_version: publication.format_version,
        poll_id: publication.poll_id,
        method_version: publication.method_version,
        report,
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
        let report = verify(
            CYCLIC,
            &Expected {
                winner: Some("a"),
                ..Default::default()
            },
        )
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
        let closure_hash = verify(CYCLIC, &Expected::default())
            .ok()
            .expect("parses")
            .closure_hash;
        let expected = Expected {
            opening_seed: Some(&opening_seed),
            winner: None,
            closure_hash: Some(&closure_hash),
            ..Default::default()
        };
        let report = verify(CYCLIC, &expected).ok().expect("parses");
        let drawn = report.tiebreak_order.expect("tie resolved");
        assert_eq!(
            report.final_winner.as_deref(),
            drawn.first().map(String::as_str)
        );
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
        let plurality = Expected {
            method: Method::Plurality,
            winner: Some("a"),
            ..Default::default()
        };
        let report = verify(DIVERGENT, &plurality).ok().expect("parses");
        assert_eq!(report.method, Method::Plurality);
        assert_eq!(report.counts, Some(vec![3, 2, 2]));
        assert_eq!(report.winner_agrees, Some(true));

        let schulze = Expected {
            winner: Some("a"),
            ..Default::default()
        };
        let report = verify(DIVERGENT, &schulze).ok().expect("parses");
        assert_eq!(report.method, Method::Schulze);
        assert_eq!(report.counts, None);
        assert_eq!(report.final_winner.as_deref(), Some("b"));
        assert_eq!(report.winner_agrees, Some(false));
    }

    #[test]
    fn an_approval_tie_goes_to_the_tie_break_like_any_other() {
        let seed = "00".repeat(32);
        let approval = Expected {
            method: Method::Approval,
            ..Default::default()
        };
        let report = verify(DIVERGENT, &approval).ok().expect("parses");
        assert_eq!(report.counts, Some(vec![7, 7, 7]));
        assert_eq!(report.winners.len(), 3);
        assert!(report.final_winner.is_none());

        let seeded = Expected {
            method: Method::Approval,
            opening_seed: Some(&seed),
            ..Default::default()
        };
        let report = verify(DIVERGENT, &seeded).ok().expect("parses");
        assert!(report.tiebreak_order.is_some());
        assert!(report.final_winner.is_some());
    }

    #[test]
    fn a_listed_option_nobody_ranked_is_in_the_matrix_and_the_counts() {
        // Review note L5: the CSV alone cannot show an unranked option.
        let listed: Vec<String> = ["a", "b", "c", "d"].iter().map(|s| s.to_string()).collect();
        let expected = Expected {
            method: Method::Plurality,
            options: Some(&listed),
            ..Default::default()
        };
        let report = verify(DIVERGENT, &expected).ok().expect("parses");
        assert_eq!(report.options, listed);
        assert_eq!(report.matrix.len(), 4);
        assert_eq!(report.counts, Some(vec![3, 2, 2, 0]));
        assert_eq!(report.winners, vec!["a".to_string()]);
    }

    #[test]
    fn a_ranked_option_missing_from_the_list_is_refused() {
        let listed: Vec<String> = ["a", "b"].iter().map(|s| s.to_string()).collect();
        let expected = Expected {
            options: Some(&listed),
            ..Default::default()
        };
        match verify(DIVERGENT, &expected) {
            Err(VerifyError::UnknownOption(option)) => assert_eq!(option, "c"),
            _ => panic!("expected UnknownOption"),
        }
    }

    // --- the publication document -------------------------------------------

    const DIVERGENT_BALLOTS: &str = r#"[
        {"tracking_code": "AAAAAAAAAA", "ranking": [["a"], ["b"], ["c"]]},
        {"tracking_code": "BBBBBBBBBB", "ranking": [["a"], ["b"], ["c"]]},
        {"tracking_code": "CCCCCCCCCC", "ranking": [["a"], ["b"], ["c"]]},
        {"tracking_code": "DDDDDDDDDD", "ranking": [["b"], ["c"], ["a"]]},
        {"tracking_code": "EEEEEEEEEE", "ranking": [["b"], ["c"], ["a"]]},
        {"tracking_code": "FFFFFFFFFF", "ranking": [["c"], ["b"], ["a"]]},
        {"tracking_code": "GGGGGGGGGG", "ranking": [["c"], ["b"], ["a"]]}
    ]"#;

    /// DIVERGENT as a plurality poll's publication, with `winner` and `extra`
    /// substituted so each test can tamper with one thing.
    fn plurality_document(winner: &str, extra: &str) -> String {
        format!(
            r#"{{"format_version": "1", "poll_id": "p", "tally_method": "plurality",
                "tally_method_version": "1",
                "closure_hash": "b9ca92b23c01dffbb5ddbab33a964e10bdf8bcac3c269d5bae742289aaa0fe7a",
                "opening_seed": "{seed}", "options": {{"a": {{"fr": "A"}}, "b": {{"fr": "B"}},
                "c": {{"fr": "C"}}, "d": {{"fr": "D"}}}},
                "ballots": {DIVERGENT_BALLOTS}, "ballot_count": 7, "winner": {winner},
                "counts": {{"registered": 9, "ballots_online": 5, "ballots_paper": 2,
                            "paper_uncountersigned": 0, "non_voters": 2}},
                "matrix": {{"a": {{"b": 3, "c": 3, "d": 7}}, "b": {{"a": 4, "c": 5, "d": 7}},
                            "c": {{"a": 4, "b": 2, "d": 7}}, "d": {{"a": 0, "b": 0, "c": 0}}}},
                "derivation": {{"counts": {{"a": 3, "b": 2, "c": 2, "d": 0}},
                                "winners": ["a"]}}{extra}}}"#,
            seed = "00".repeat(32),
        )
    }

    #[test]
    fn a_consistent_publication_agrees_on_every_count() {
        let checked = verify_publication(&plurality_document("\"a\"", ""))
            .ok()
            .expect("reads");
        assert_eq!(checked.report.method, Method::Plurality);
        assert_eq!(checked.report.options, ["a", "b", "c", "d"]);
        assert_eq!(checked.report.closure_hash_agrees, Some(true));
        assert_eq!(checked.report.winner_agrees, Some(true));
        assert!(checked.ballot_count_agrees && checked.matrix_agrees);
        assert_eq!(checked.counts_agree, Some(true));
        assert_eq!(checked.tiebreak_agrees, None);
        assert!(checked.all_agree());
    }

    #[test]
    fn a_publication_claiming_another_winner_disagrees() {
        let checked = verify_publication(&plurality_document("\"b\"", ""))
            .ok()
            .expect("reads");
        assert_eq!(checked.report.winner_agrees, Some(false));
        assert!(!checked.all_agree());
    }

    #[test]
    fn a_publication_claiming_a_tie_that_is_not_there_disagrees() {
        let extra =
            r#", "tiebreak": {"rule": "physical", "tied": ["a", "b"], "order": ["a", "b"]}"#;
        let checked = verify_publication(&plurality_document("\"a\"", extra))
            .ok()
            .expect("reads");
        assert_eq!(checked.tiebreak_agrees, Some(false));
        assert!(!checked.all_agree());
    }

    #[test]
    fn a_schulze_poll_with_no_ballots_has_no_winner_and_no_tie() {
        // T-39: the application publishes "no result", winner null and no
        // tie-break; the verifier must agree rather than demand a draw.
        let document = format!(
            r#"{{"format_version": "1", "poll_id": "p", "tally_method": "schulze",
                "tally_method_version": "1",
                "closure_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                "opening_seed": "{seed}", "options": {{"a": {{"fr": "A"}}, "b": {{"fr": "B"}}}},
                "ballots": [], "ballot_count": 0, "winner": null,
                "counts": {{"registered": 4, "ballots_online": 0, "ballots_paper": 0,
                            "paper_uncountersigned": 0, "non_voters": 4}},
                "matrix": {{"a": {{"b": 0}}, "b": {{"a": 0}}}},
                "derivation": {{"pairwise": {{}}, "paths": {{}}, "winners": []}}}}"#,
            seed = "00".repeat(32),
        );
        let checked = verify_publication(&document).ok().expect("parses");
        assert!(checked.report.winners.is_empty());
        assert_eq!(checked.tiebreak_agrees, None);
        assert!(checked.all_agree());
    }

    #[test]
    fn a_repeated_or_malformed_tracking_code_is_refused() {
        let repeated = format!("{CYCLIC}AAAAAAAAAA,\"[[\"\"a\"\"]]\"\n");
        assert!(matches!(
            verify(&repeated, &Expected::default()),
            Err(VerifyError::DuplicateTrackingCode(code)) if code == "AAAAAAAAAA"
        ));
        let malformed = "tracking_code,ranking\nAAAAA-AAAA,\"[[\"\"a\"\"]]\"\n";
        assert!(matches!(
            verify(malformed, &Expected::default()),
            Err(VerifyError::MalformedTrackingCode(_))
        ));
    }

    #[test]
    fn participation_counts_must_add_up_to_the_ballot_list() {
        // Consistent: 5 online + 2 paper = the 7 ballots listed, and 9
        // registered = 7 voted + 0 uncounted + 2 who did not vote.
        let honest = plurality_document("\"a\"", "");
        assert!(
            verify_publication(&honest)
                .ok()
                .expect("parses")
                .participation_agrees
        );
        // Stuffed: ballots added to the list, counts left as they were.
        let inflated = honest.replace("\"ballots_online\": 5", "\"ballots_online\": 105");
        let checked = verify_publication(&inflated).ok().expect("parses");
        assert!(!checked.participation_agrees);
        assert!(!checked.all_agree());
        // Registered that do not account for every elector.
        let unaccounted = honest.replace("\"non_voters\": 2", "\"non_voters\": 3");
        assert!(
            !verify_publication(&unaccounted)
                .ok()
                .expect("parses")
                .participation_agrees
        );
        // Overflow is a disagreement, not a panic.
        let huge = honest.replace("\"non_voters\": 2", "\"non_voters\": 18446744073709551615");
        assert!(
            !verify_publication(&huge)
                .ok()
                .expect("parses")
                .participation_agrees
        );
    }

    #[test]
    fn a_publication_without_its_counts_is_refused() {
        let start = plurality_document("\"a\"", "");
        let cut = start.find("\"counts\"").expect("has counts");
        let end = start[cut..].find('}').expect("closes") + cut + 2;
        let without = format!("{}{}", &start[..cut], &start[end..]);
        assert!(matches!(
            verify_publication(&without),
            Err(VerifyError::Publication(_))
        ));
    }

    #[test]
    fn a_ranking_no_ballot_could_carry_is_refused_in_a_publication_too() {
        let document = plurality_document("\"a\"", "").replacen(
            "[[\"a\"], [\"b\"], [\"c\"]]",
            "[[\"a\"], [\"a\"]]",
            1,
        );
        assert!(matches!(
            verify_publication(&document),
            Err(VerifyError::MalformedRanking(_, why)) if why.contains("twice")
        ));
    }

    #[test]
    fn a_document_without_a_format_version_is_refused() {
        let document =
            plurality_document("\"a\"", "").replacen("\"format_version\": \"1\", ", "", 1);
        assert!(matches!(
            verify_publication(&document),
            Err(VerifyError::Publication(_))
        ));
    }

    fn cyclic_document(tiebreak: &str, winner: &str) -> String {
        format!(
            r#"{{"format_version": "1", "poll_id": "p", "tally_method": "schulze",
                "tally_method_version": "1",
                "closure_hash": "18b00454878dc9e9204cff5488d6c9c4ec2a4e12c5382c64d1569e42fa6a6edd",
                "opening_seed": "{seed}", "options": {{"a": {{}}, "b": {{}}, "c": {{}}}},
                "ballots": [
                    {{"tracking_code": "AAAAAAAAAA", "ranking": [["a"], ["b"], ["c"]]}},
                    {{"tracking_code": "BBBBBBBBBB", "ranking": [["b"], ["c"], ["a"]]}},
                    {{"tracking_code": "CCCCCCCCCC", "ranking": [["c"], ["a"], ["b"]]}}],
                "ballot_count": 3, "winner": {winner},
                "counts": {{"registered": 3, "ballots_online": 3, "ballots_paper": 0,
                            "paper_uncountersigned": 0, "non_voters": 0}},
                "matrix": {{"a": {{"b": 2, "c": 1}}, "b": {{"a": 1, "c": 2}},
                            "c": {{"a": 2, "b": 1}}}},
                "derivation": {{}}, "tiebreak": {tiebreak}}}"#,
            seed = "00".repeat(32),
        )
    }

    #[test]
    fn a_computed_tie_break_is_replayed_and_must_match() {
        // Draw the order the hash chain gives, then publish it — and a wrong one.
        let seed = "00".repeat(32);
        let hash = "18b00454878dc9e9204cff5488d6c9c4ec2a4e12c5382c64d1569e42fa6a6edd";
        let tied: Vec<String> = ["a", "b", "c"].iter().map(|s| s.to_string()).collect();
        let order = schulze::tiebreak(&tied, &parse_hex(&seed).unwrap(), &parse_hex(hash).unwrap());
        let entries: Vec<String> = order
            .iter()
            .map(|o| format!(r#"{{"option_id": "{o}", "draw": "00"}}"#))
            .collect();
        let tiebreak = format!(
            r#"{{"rule": "computed", "tied": ["a", "b", "c"], "order": [{}], "winner": "{}"}}"#,
            entries.join(", "),
            order[0]
        );
        let winner = format!("\"{}\"", order[0]);
        let checked = verify_publication(&cyclic_document(&tiebreak, &winner))
            .ok()
            .expect("reads");
        assert_eq!(checked.tiebreak_rule, Some(TiebreakRule::Computed));
        assert_eq!(checked.tiebreak_agrees, Some(true));
        assert!(checked.all_agree());

        let reversed: Vec<String> = entries.into_iter().rev().collect();
        let tampered = format!(
            r#"{{"rule": "computed", "tied": ["a", "b", "c"], "order": [{}], "winner": "{}"}}"#,
            reversed.join(", "),
            order[order.len() - 1]
        );
        let checked = verify_publication(&cyclic_document(&tampered, &winner))
            .ok()
            .expect("reads");
        assert_eq!(checked.tiebreak_agrees, Some(false));
    }

    #[test]
    fn a_physical_draw_must_be_among_exactly_the_tied_options() {
        let drawn = r#"{"rule": "physical", "tied": ["a", "b", "c"], "order": ["b", "c", "a"],
                        "winner": "b"}"#;
        let checked = verify_publication(&cyclic_document(drawn, "\"b\""))
            .ok()
            .expect("reads");
        assert_eq!(checked.tiebreak_rule, Some(TiebreakRule::Physical));
        assert_eq!(checked.tiebreak_agrees, Some(true));
        assert_eq!(checked.report.final_winner.as_deref(), Some("b"));
        assert!(checked.all_agree());

        let foreign = r#"{"rule": "physical", "tied": ["a", "b", "c"], "order": ["b", "c", "z"],
                          "winner": "b"}"#;
        let checked = verify_publication(&cyclic_document(foreign, "\"b\""))
            .ok()
            .expect("reads");
        assert_eq!(checked.tiebreak_agrees, Some(false));
        assert!(!checked.all_agree());
    }

    #[test]
    fn the_tie_break_winner_must_be_the_first_of_its_order() {
        // Review D-4: `tiebreak.winner` is published, so it is checked: the
        // first of the drawn order, and through it the top-level `winner`.
        for winner in [r#", "winner": "c""#, ""] {
            let drawn = format!(
                r#"{{"rule": "physical", "tied": ["a", "b", "c"], "order": ["b", "c", "a"]{winner}}}"#
            );
            let checked = verify_publication(&cyclic_document(&drawn, "\"b\""))
                .ok()
                .expect("reads");
            assert_eq!(checked.tiebreak_agrees, Some(false), "winner {winner:?}");
            assert!(!checked.all_agree());
        }
    }

    #[test]
    fn an_option_id_outside_the_alphabet_is_refused() {
        // Review B-7: the serialisation writes ids unescaped, so an id JSON
        // would escape cannot be hashed the way the application hashes it.
        for id in ["a\"b", "a b", "é", "", &"x".repeat(51)] {
            assert!(!is_option_id(id), "{id:?}");
            let ballots = [Ballot {
                tracking_code: "AAAAAAAAAA".into(),
                ranking: vec![vec![id.to_string()]],
            }];
            assert!(matches!(
                verify_ballots(&ballots, &Expected::default()),
                Err(VerifyError::MalformedRanking(..))
            ));
            let listed = vec!["a".to_string(), id.to_string()];
            let expected = Expected {
                options: Some(&listed),
                ..Expected::default()
            };
            let ballots = [Ballot {
                tracking_code: "AAAAAAAAAA".into(),
                ranking: vec![vec!["a".into()]],
            }];
            assert!(matches!(
                verify_ballots(&ballots, &expected),
                Err(VerifyError::MalformedOptionId(ref m)) if m == id
            ));
        }
        for id in ["a", "option-b", "Grille_3", &"x".repeat(50)] {
            assert!(is_option_id(id), "{id:?}");
        }
    }
}
