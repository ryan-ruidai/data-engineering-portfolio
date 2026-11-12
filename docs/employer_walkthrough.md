# Three-minute interviewer walkthrough

1. **Business definition:** current successful payment snapshot, not revenue. State the CAD-only and UTC boundaries.
2. **Model:** event → latest payment → order mart. Show how one order can have multiple payments and why the latest void removes earlier success.
3. **Evidence:** run `python3 -m unittest discover -s tests -v`, then run `python3 -m pipeline.run` twice. The second run inserts zero events.
4. **Output:** open `build/report.html`, explain 11/7/5/4 counts and 245.00 amount. Quality exceptions are separate, and internal reconciliation is not a bank match.
5. **Trade-offs:** SQLite integer cents for an easy reproducible demo, full-view snapshot for late events, first accepted event ID immutable. Identify real production gaps instead of claiming a deployed platform.
