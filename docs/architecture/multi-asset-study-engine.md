# Multi-asset study engine

Step 10A.1 adds a study layer for real multi-asset diagnostic work. It does not import paid data, create signals, or run trading logic.

The engine stores:

- `StudyManifest`: versioned study configuration, dataset hash, status, decision, and final-test lock.
- `StudyDatasetEntry`: one instrument/timeframe dataset with coverage, bars, windows, episodes, outcome completeness, and inclusion status.
- `StudyEpisode`: derived `temporal_episode_v1` metadata.
- `StudyPreflight`: explicit readiness gate results.
- `StudyArm`: bounded pilot, validation, and final-test arm summaries.

It reuses existing immutable source, window, DNA, context, outcome, diagnostic, and validation records.

