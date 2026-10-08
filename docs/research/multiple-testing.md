# Multiple testing

Step 9 includes Benjamini-Hochberg and Holm adjustment helpers for parameter-sweep families. Experiment definitions include a `multiple_testing_family` field so future sweeps can group related comparisons.

The initial persisted metric path records raw metrics and bootstrap intervals. Multiple-testing adjusted p-values are available as helpers and can be expanded into persisted pairwise comparisons in the next phase.

