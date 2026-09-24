// SPDX-License-Identifier: 0BSD
//! Reading the publication document (`?format=json`), whose layout is
//! `docs/publication-format.md`. Only the members the verifier checks are
//! read; the rest (labels, participation counts, derivation beyond the counts)
//! is ignored, and a member it needs that is missing or of the wrong type is
//! an error naming it.

use crate::canonical::Ballot;
use crate::counted::Method;
use crate::json::{self, Value};

/// The layout versions this verifier reads.
pub const SUPPORTED_FORMAT_VERSIONS: &[&str] = &["1"];

/// How a tie among the winners was settled (§8.3).
#[derive(Debug, PartialEq)]
pub enum TiebreakRule {
    /// The hash chain anyone can replay from the opening seed.
    Computed,
    /// A public draw by lots, whose outcome was entered by hand.
    Physical,
}

pub struct Tiebreak {
    pub rule: TiebreakRule,
    pub tied: Vec<String>,
    /// The drawn order, first the winner; absent only for a physical draw not
    /// yet entered, which publication refuses.
    pub order: Option<Vec<String>>,
}

pub struct Publication {
    pub format_version: String,
    pub poll_id: String,
    pub method: Method,
    pub method_version: String,
    pub closure_hash: String,
    pub opening_seed: String,
    /// Option ids in the document's order.
    pub options: Vec<String>,
    pub ballots: Vec<Ballot>,
    pub ballot_count: u64,
    pub winner: Option<String>,
    /// `matrix[i][j]` as published, keyed by option id.
    pub matrix: Vec<(String, Vec<(String, u64)>)>,
    /// Votes per option (`derivation.counts`), for plurality and approval.
    pub counts: Option<Vec<(String, u64)>>,
    pub tiebreak: Option<Tiebreak>,
}

fn member<'a>(value: &'a Value, key: &str) -> Result<&'a Value, String> {
    value.get(key).ok_or_else(|| format!("publication: \"{key}\" is missing"))
}

fn string(value: &Value, key: &str) -> Result<String, String> {
    member(value, key)?
        .as_str()
        .map(String::from)
        .ok_or_else(|| format!("publication: \"{key}\" must be a string"))
}

fn strings(value: &Value, what: &str) -> Result<Vec<String>, String> {
    value
        .as_array()
        .ok_or_else(|| format!("publication: {what} must be a list"))?
        .iter()
        .map(|item| {
            item.as_str().map(String::from).ok_or_else(|| format!("publication: {what} must hold strings"))
        })
        .collect()
}

fn integers(value: &Value, what: &str) -> Result<Vec<(String, u64)>, String> {
    value
        .as_object()
        .ok_or_else(|| format!("publication: {what} must be an object"))?
        .iter()
        .map(|(key, item)| {
            item.as_u64()
                .map(|n| (key.clone(), n))
                .ok_or_else(|| format!("publication: {what} must hold whole numbers"))
        })
        .collect()
}

/// Parse and read a publication document.
pub fn parse_publication(text: &str) -> Result<Publication, String> {
    let document = json::parse(text)?;
    if document.as_object().is_none() {
        return Err("publication: the document must be a JSON object".to_string());
    }

    let format_version = match document.get("format_version").map(Value::as_str) {
        Some(Some(version)) => version.to_string(),
        _ => {
            return Err("publication: \"format_version\" is missing — this is not a \
                        publication document, or one older than this verifier reads"
                .to_string())
        }
    };
    if !SUPPORTED_FORMAT_VERSIONS.contains(&format_version.as_str()) {
        return Err(format!(
            "publication: format version {format_version} is not one this verifier reads \
             ({}); use a newer verifier",
            SUPPORTED_FORMAT_VERSIONS.join(", ")
        ));
    }

    let method_text = string(&document, "tally_method")?;
    let method = Method::parse(&method_text)
        .ok_or_else(|| format!("publication: unknown tally method \"{method_text}\""))?;

    let options: Vec<String> = member(&document, "options")?
        .as_object()
        .ok_or("publication: \"options\" must be an object")?
        .iter()
        .map(|(id, _label)| id.clone())
        .collect();

    let mut ballots = Vec::new();
    for (index, row) in member(&document, "ballots")?
        .as_array()
        .ok_or("publication: \"ballots\" must be a list")?
        .iter()
        .enumerate()
    {
        let what = format!("ballot {}", index + 1);
        let tracking_code = row
            .get("tracking_code")
            .and_then(Value::as_str)
            .ok_or_else(|| format!("publication: {what} has no tracking code"))?
            .to_string();
        let ranking = row
            .get("ranking")
            .and_then(Value::as_array)
            .ok_or_else(|| format!("publication: {what} has no ranking"))?
            .iter()
            .map(|group| strings(group, &format!("{what}'s ranking")))
            .collect::<Result<Vec<_>, _>>()?;
        ballots.push(Ballot { tracking_code, ranking });
    }

    let ballot_count = member(&document, "ballot_count")?
        .as_u64()
        .ok_or("publication: \"ballot_count\" must be a whole number")?;

    let winner = match member(&document, "winner")? {
        Value::Null => None,
        Value::String(id) => Some(id.clone()),
        _ => return Err("publication: \"winner\" must be a string or null".to_string()),
    };

    let matrix = member(&document, "matrix")?
        .as_object()
        .ok_or("publication: \"matrix\" must be an object")?
        .iter()
        .map(|(row, cells)| integers(cells, "a matrix row").map(|cells| (row.clone(), cells)))
        .collect::<Result<Vec<_>, _>>()?;

    let counts = match member(&document, "derivation")?.get("counts") {
        None => None,
        Some(value) => Some(integers(value, "\"derivation.counts\"")?),
    };

    let tiebreak = match document.get("tiebreak") {
        None => None,
        Some(value) => {
            let rule = match string(value, "rule")?.as_str() {
                "computed" => TiebreakRule::Computed,
                "physical" => TiebreakRule::Physical,
                other => return Err(format!("publication: unknown tie-break rule \"{other}\"")),
            };
            let tied = strings(member(value, "tied")?, "\"tiebreak.tied\"")?;
            let order = match value.get("order") {
                None => None,
                Some(order) => Some(match rule {
                    // Computed: [{"option_id": …, "draw": …}, …].
                    TiebreakRule::Computed => order
                        .as_array()
                        .ok_or("publication: \"tiebreak.order\" must be a list")?
                        .iter()
                        .map(|entry| {
                            entry
                                .get("option_id")
                                .and_then(Value::as_str)
                                .map(String::from)
                                .ok_or_else(|| {
                                    "publication: \"tiebreak.order\" entries need an option_id"
                                        .to_string()
                                })
                        })
                        .collect::<Result<Vec<_>, _>>()?,
                    // Physical: the ids in the order drawn.
                    TiebreakRule::Physical => strings(order, "\"tiebreak.order\"")?,
                }),
            };
            Some(Tiebreak { rule, tied, order })
        }
    };

    Ok(Publication {
        format_version,
        poll_id: string(&document, "poll_id")?,
        method,
        method_version: string(&document, "tally_method_version")?,
        closure_hash: string(&document, "closure_hash")?,
        opening_seed: string(&document, "opening_seed")?,
        options,
        ballots,
        ballot_count,
        winner,
        matrix,
        counts,
        tiebreak,
    })
}
