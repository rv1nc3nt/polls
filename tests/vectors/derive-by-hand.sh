#!/bin/sh
# SPDX-License-Identifier: 0BSD
#
# Two of the corpus's expectations, derived from the written contract alone
# (review D-1): docs/canonical-serialisation.md for the closure hash, spec §8.3
# for the tie-break, and nothing but printf, xxd and OpenSSL, none of which
# shares a line with the application or the verifier. If these agree with the
# corpus, the two implementations are not merely agreeing with each other.
#
# Prints three lines: the T-9 case's closure hash, its tie-break order, and
# the T-44 order. tests/integration/test_vectors.py runs this and compares.
set -eu

sha() { openssl dgst -sha256 -r | cut -d' ' -f1; }
unhex() { xxd -r -p; }

# tiebreak SEED_HEX CLOSURE_HASH_HEX OPTION...: the options by ascending draw.
tiebreak() {
    seed=$(printf '%s%s' "$1" "$2" | unhex | sha)
    shift 2
    for option in "$@"; do
        printf '%s %s\n' "$({ printf '%s' "$seed" | unhex; printf '%s' "$option"; } | sha)" "$option"
    done | sort | cut -d' ' -f2 | tr '\n' ' ' | sed 's/ $//'
    echo
}

# T-9 (schulze.json, "T-9 cyclic majority…"): three ballots, typed as the
# canonical serialisation prescribes, sorted by tracking code, one per line.
t9_hash=$(printf '%s\n' \
    '{"tracking_code":"AAAAAA2222","ranking":[["a"],["b"],["c"]]}' \
    '{"tracking_code":"AAAAAA2223","ranking":[["b"],["c"],["a"]]}' \
    '{"tracking_code":"AAAAAA2224","ranking":[["c"],["a"],["b"]]}' | sha)
echo "$t9_hash"
tiebreak "$(printf '%064d' 0)" "$t9_hash" a b c

# T-44: opening seed bytes 0..31, closure hash bytes 32..63.
tiebreak "$(printf '%02x' $(seq 0 31) | tr -d '\n')" "$(printf '%02x' $(seq 32 63) | tr -d '\n')" a b c
