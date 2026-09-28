# Gate fields prune, graded fields score

Criteria fields split into two kinds. Amount and Date are **gate fields**: a candidate pair outside their tolerance is rejected outright. Reference and Counterparty are **graded fields**: they produce a 0..1 similarity that feeds a match score used to rank and choose among the survivors.

We chose blocking-then-scoring over scoring every field uniformly because the gates cheaply collapse an O(left × right) comparison to a small candidate set, which also bounds the 1:many (split-match) search. The trade-off, and the reason a reader might be surprised: a pair with a perfect reference string but an amount one cent outside tolerance never matches — Amount is a gate, not a weight. That is deliberate; money mismatches are not negotiable by string similarity.
