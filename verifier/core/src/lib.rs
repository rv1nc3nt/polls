// SPDX-License-Identifier: 0BSD
//! Core verification logic for the commune polling platform (§8, §9): the
//! canonical serialisation, the closure hash, the pairwise matrix, the three
//! tally methods (Schulze, plurality, approval) and the tie-break. Written from
//! `docs/canonical-serialisation.md` and §8 of the specification, and shares
//! no code with the Python implementation — a property the language boundary
//! enforces structurally.
//!
//! Deliberately free of external dependencies: this is the part a sceptic is
//! actually auditing, so there is nothing here to read but this code. The CLI
//! and GUI binaries are separate crates that depend on this one and may take
//! on dependencies of their own for presentation, without touching this rule.

pub mod canonical;
pub mod counted;
pub mod json;
pub mod publication;
pub mod report;
pub mod schulze;
pub mod sha256;
