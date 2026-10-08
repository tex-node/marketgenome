# Context confidence

Each dimension stores an independent confidence in `[0, 1]`.

Conflicting evidence lowers confidence. Missing dimensions lower completeness and usually add `PARTIAL_CONTEXT`. Composite confidence is the configured weighted average of dimension confidence values.

Confidence is descriptive. It is not an estimated probability of future profitability.
