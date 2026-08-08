# MergeLife upstream conformance vectors

`vectors.txt` is copied verbatim from
[github.com/jeffheaton/mergelife](https://github.com/jeffheaton/mergelife)
(`conformance/vectors.txt`) — the cross-engine contract that repo's Python, JavaScript,
Java, and C engines all satisfy. heaton-life's MergeLife implementation replays these in
`python/tests/test_mergelife.py`, so it is byte-identical with the reference engines.

Format per line: `rule rows cols seed steps fnv1a64`. The initial lattice comes from the
upstream 32-bit LCG (`state = state * 1664525 + 1013904223`, byte = `state >> 24`,
row-major, RGB channels innermost); the digest is FNV-1a 64 over the final lattice bytes.
See the upstream `conformance/README.md` for the full contract.

Do not edit or regenerate here — this file tracks upstream.
