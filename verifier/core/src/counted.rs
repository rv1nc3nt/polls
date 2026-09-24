// SPDX-License-Identifier: 0BSD
//! The two counted methods of §8.2 (R-10.3), plurality and approval, and the
//! choice between them and Schulze.
//!
//! The published CSV does not say which method a poll used; the results page
//! does, and the person verifying passes it in. Each ballot is a ranking, as
//! for Schulze: plurality counts the options of its first group — several
//! only where the poll allows ties, each counting once — and approval counts
//! every option it ranks. The winners are the options with the highest count.

/// A tally method, as the results page and the publication name it.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum Method {
    #[default]
    Schulze,
    Plurality,
    Approval,
}

impl Method {
    /// Accepts the identifier the publication uses (`schulze`, `plurality`,
    /// `approval`) and the French label the results page shows
    /// (`majoritaire`, `par assentiment`), in any case.
    pub fn parse(text: &str) -> Option<Method> {
        let lowered = text.trim().to_lowercase();
        match lowered.strip_prefix("par ").unwrap_or(&lowered).trim() {
            "schulze" => Some(Method::Schulze),
            "plurality" | "majoritaire" => Some(Method::Plurality),
            "approval" | "assentiment" => Some(Method::Approval),
            _ => None,
        }
    }

    /// The publication's identifier for this method.
    pub fn id(self) -> &'static str {
        match self {
            Method::Schulze => "schulze",
            Method::Plurality => "plurality",
            Method::Approval => "approval",
        }
    }
}

/// Votes per option, in `options` order. `method` must be `Plurality` or
/// `Approval`; Schulze is not a count.
pub fn counts(ballots: &[Vec<Vec<String>>], options: &[String], method: Method) -> Vec<u32> {
    let mut counts = vec![0u32; options.len()];
    for ranking in ballots {
        let chosen: Vec<&String> = match method {
            Method::Plurality => ranking.first().map(|g| g.iter().collect()).unwrap_or_default(),
            Method::Approval => ranking.iter().flatten().collect(),
            Method::Schulze => Vec::new(),
        };
        for option in chosen {
            if let Some(index) = options.iter().position(|o| o == option) {
                counts[index] += 1;
            }
        }
    }
    counts
}

/// The options with the highest count, in `options` order; none without
/// ballots. More than one means a tie for the §8.3 tie-break.
pub fn winners(counts: &[u32], options: &[String], ballot_count: usize) -> Vec<String> {
    if ballot_count == 0 {
        return Vec::new();
    }
    let best = counts.iter().copied().max().unwrap_or(0);
    options.iter().zip(counts).filter(|(_, &c)| c == best).map(|(o, _)| o.clone()).collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn ids(list: &[&str]) -> Vec<String> {
        list.iter().map(|s| s.to_string()).collect()
    }

    fn ranking(groups: &[&[&str]]) -> Vec<Vec<String>> {
        groups.iter().map(|g| ids(g)).collect()
    }

    #[test]
    fn parse_accepts_ids_and_the_french_labels() {
        assert_eq!(Method::parse("schulze"), Some(Method::Schulze));
        assert_eq!(Method::parse("Plurality"), Some(Method::Plurality));
        assert_eq!(Method::parse("majoritaire"), Some(Method::Plurality));
        assert_eq!(Method::parse(" par assentiment "), Some(Method::Approval));
        assert_eq!(Method::parse("approval"), Some(Method::Approval));
        assert_eq!(Method::parse("borda"), None);
    }

    #[test]
    fn plurality_counts_the_first_group_and_each_tied_option_in_it() {
        let options = ids(&["a", "b", "c"]);
        let ballots = vec![
            ranking(&[&["a"], &["b"]]),
            ranking(&[&["b", "c"], &["a"]]),
            ranking(&[&["a"], &["c"]]),
        ];
        assert_eq!(counts(&ballots, &options, Method::Plurality), vec![2, 1, 1]);
    }

    #[test]
    fn approval_counts_every_ranked_option() {
        let options = ids(&["a", "b", "c"]);
        let ballots = vec![ranking(&[&["a"], &["b"]]), ranking(&[&["b", "c"]]), ranking(&[&["b"]])];
        assert_eq!(counts(&ballots, &options, Method::Approval), vec![1, 3, 1]);
    }

    #[test]
    fn winners_are_every_option_at_the_top_count() {
        let options = ids(&["a", "b", "c"]);
        assert_eq!(winners(&[2, 2, 1], &options, 5), ids(&["a", "b"]));
        assert_eq!(winners(&[1, 3, 1], &options, 3), ids(&["b"]));
        assert!(winners(&[0, 0, 0], &options, 0).is_empty());
    }
}
