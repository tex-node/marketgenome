# Purging and embargo

Step 9 separates retrieval ranking from validation eligibility.

Eligibility rejects:

- same query window;
- future or contemporary candidate windows;
- candidate source windows overlapping query source windows;
- candidate outcomes overlapping query source or query outcome intervals;
- configured embargo/minimum temporal-distance violations;
- excluded same-instrument or cross-asset candidates when those controls are requested.

Embargo is approximated in bar units from the source-window duration because Phase 1 has no exchange-session calendar model.

