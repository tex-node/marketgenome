# Barrier Outcomes

Barrier outcomes check whether future bars touch configured upside and downside return thresholds from the anchor close.

`forward_outcomes_v1` includes symmetric barriers at 0.5%, 1%, and 2%. If both upside and downside barriers are touched inside the same bar, the state is `SAME_BAR_BOTH`.

Sequencing fields separately record whether a 1% gain occurred before a 1% drawdown, or vice versa.
