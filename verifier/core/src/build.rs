// SPDX-License-Identifier: 0BSD
//! Which build of the verifier this is, for a bug report (review B-11).
//!
//! The crates' own version never changes; what identifies a binary is the
//! project release it was attached to and the commit it was built from. The
//! release workflow (`.github/workflows/verifier-release.yml`) sets both at
//! build time. A binary built anywhere else says it was built from source
//! rather than claim a version it cannot vouch for.

use crate::publication::SUPPORTED_FORMAT_VERSIONS;

/// The release tag this binary was built for, e.g. `v1.0.0b17`.
pub const RELEASE: Option<&str> = option_env!("POLLS_RELEASE");
/// The commit it was built from.
pub const COMMIT: Option<&str> = option_env!("POLLS_COMMIT");

/// One line naming this build, then the publication format versions it reads.
#[must_use]
pub fn describe() -> String {
    // Set but empty, as on a workflow run that is not a release, is unset.
    let given = |value: Option<&'static str>| value.filter(|v| !v.is_empty());
    let build = match (given(RELEASE), given(COMMIT)) {
        (Some(release), Some(commit)) => format!("{release} (commit {commit})"),
        (Some(release), None) => release.to_string(),
        (None, Some(commit)) => format!("built from source, commit {commit}"),
        (None, None) => "built from source, not a release".to_string(),
    };
    format!(
        "{build}\npublication format versions: {}",
        SUPPORTED_FORMAT_VERSIONS.join(", ")
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn names_the_build_and_the_formats_it_reads() {
        let text = describe();
        let first = text.lines().next().expect("a line");
        match RELEASE.filter(|v| !v.is_empty()) {
            Some(release) => assert!(first.starts_with(release)),
            None => assert!(first.starts_with("built from source")),
        }
        assert!(text.ends_with("publication format versions: 1"));
    }
}
