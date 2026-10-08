# Real-time query flow

Target flow:

```text
completed bar
→ validation
→ active window update
→ normalization
→ feature extraction
→ regime classification
→ nearest-neighbour query
→ outcome distribution aggregation
→ dashboard/API response
```

The foundation does not implement real-time indexing yet. Interfaces are separated so workers can later update immutable historical windows incrementally.

