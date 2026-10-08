# Outcome definitions

Implemented `forward_outcomes_v1` observations:

- future simple return;
- future log return;
- maximum favourable excursion;
- maximum adverse excursion;
- time to MFE;
- time to MAE;
- realized future volatility;
- path efficiency;
- future maximum drawdown;
- future maximum runup;
- direction class;
- continuation/reversal class;
- first barrier hit;
- gain-before-drawdown and drawdown-before-gain sequencing;
- normalized forward path.

All calculations anchor to the source window final close and use only bars after `PatternWindow.end_timestamp`.

Outcome data must never enter retrieval features.

Step 9 consumes completed outcome observations as labels after retrieval. Metrics are segmented by horizon so 1-bar, 3-bar, and longer outcomes are not mixed into a single target.
