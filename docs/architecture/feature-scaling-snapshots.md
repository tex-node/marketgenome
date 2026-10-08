# Feature scaling snapshots

Feature scaling snapshots store reference statistics for Market DNA features:

- scope;
- feature set;
- date bounds;
- historical mode;
- record count;
- feature statistics;
- feature availability;
- configuration hash;
- snapshot hash.

Supported scaling methods:

- `none_v1`;
- `zscore_reference_v1`;
- `robust_median_mad_v1`;
- `robust_iqr_v1`;
- `winsorized_zscore_v1`;
- `group_balanced_robust_v1`.

Formal validation should use historical-as-of fold snapshots. The initial diagnostic runner also supports descriptive full-sample snapshots, labelled `DESCRIPTIVE_FULL_SAMPLE`.

