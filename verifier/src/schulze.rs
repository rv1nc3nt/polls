// SPDX-License-Identifier: 0BSD
//! The Schulze method and the tie-break, from §8 of the specification.

use crate::sha256::sha256;

/// `d[i][j]`: ballots ranking `i` strictly above `j`. Options a ballot does not
/// rank are equal-last (R-10.4).
pub fn pairwise(ballots: &[Vec<Vec<String>>], options: &[String]) -> Vec<Vec<u32>> {
    let n = options.len();
    let mut d = vec![vec![0u32; n]; n];
    for ranking in ballots {
        let mut rank = vec![ranking.len(); n];
        for (position, group) in ranking.iter().enumerate() {
            for option in group {
                if let Some(index) = options.iter().position(|o| o == option) {
                    rank[index] = position;
                }
            }
        }
        for i in 0..n {
            for j in 0..n {
                if i != j && rank[i] < rank[j] {
                    d[i][j] += 1;
                }
            }
        }
    }
    d
}

/// The strongest-path strengths, exactly the loop of §8.1.
pub fn strongest_paths(d: &[Vec<u32>], options: &[String]) -> Vec<Vec<u32>> {
    let n = options.len();
    let mut p = vec![vec![0u32; n]; n];
    for i in 0..n {
        for j in 0..n {
            if i != j && d[i][j] > d[j][i] {
                p[i][j] = d[i][j];
            }
        }
    }
    for i in 0..n {
        for j in 0..n {
            if j == i {
                continue;
            }
            for k in 0..n {
                if k == i || k == j {
                    continue;
                }
                p[j][k] = p[j][k].max(p[j][i].min(p[i][k]));
            }
        }
    }
    p
}

pub fn winners(p: &[Vec<u32>], options: &[String]) -> Vec<String> {
    let n = options.len();
    (0..n)
        .filter(|&i| (0..n).all(|j| j == i || p[i][j] >= p[j][i]))
        .map(|i| options[i].clone())
        .collect()
}

/// §8.3: order tied options by ascending `SHA256(seed || option_id)`, where
/// `seed = SHA256(opening_seed || closure_hash)`. No PRNG, no seeded sort.
pub fn tiebreak(tied: &[String], opening_seed: &[u8], closure_hash: &[u8]) -> Vec<String> {
    let mut input = opening_seed.to_vec();
    input.extend_from_slice(closure_hash);
    let seed = sha256(&input);

    let mut drawn: Vec<(String, [u8; 32])> = tied
        .iter()
        .map(|option| {
            let mut buffer = seed.to_vec();
            buffer.extend_from_slice(option.as_bytes());
            (option.clone(), sha256(&buffer))
        })
        .collect();
    drawn.sort_by(|a, b| a.1.cmp(&b.1));
    drawn.into_iter().map(|(option, _)| option).collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn strict(order: &[&str]) -> Vec<Vec<String>> {
        order.iter().map(|o| vec![o.to_string()]).collect()
    }

    #[test]
    fn cyclic_majority_is_a_three_way_tie() {
        let options: Vec<String> = ["a", "b", "c"].iter().map(|s| s.to_string()).collect();
        let ballots = vec![
            strict(&["a", "b", "c"]),
            strict(&["b", "c", "a"]),
            strict(&["c", "a", "b"]),
        ];
        let d = pairwise(&ballots, &options);
        let p = strongest_paths(&d, &options);
        assert_eq!(winners(&p, &options).len(), 3);
    }

    #[test]
    fn tiebreak_matches_the_python_vector() {
        let options: Vec<String> = ["a", "b", "c"].iter().map(|s| s.to_string()).collect();
        let opening_seed: Vec<u8> = (0u8..32).collect();
        let closure_hash: Vec<u8> = (32u8..64).collect();
        assert_eq!(
            tiebreak(&options, &opening_seed, &closure_hash),
            vec!["c".to_string(), "a".to_string(), "b".to_string()]
        );
    }
}
