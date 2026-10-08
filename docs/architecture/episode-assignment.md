# Episode assignment

`temporal_episode_v1` groups windows by instrument, timeframe, and temporal bucket. The gap is:

```text
max(source window length, maximum evaluated outcome horizon, configured minimum separation)
```

Episodes are stored as derived metadata and do not mutate `PatternWindow` records.

