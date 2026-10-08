# Multi-resolution context

`transparent_context_v1` links local, intermediate, and macro window lengths using the same instrument, timeframe, and window end timestamp.

Default lengths are 16, 64, and 256. Missing scales produce `UNAVAILABLE` multi-resolution state and partial context. Different timestamps are not treated as aligned.
