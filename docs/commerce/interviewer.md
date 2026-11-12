# Ten-minute project walkthrough

1. **Problem and sources:** retail order database plus processor event exports. Explain why payment state is not revenue.
2. **Model:** identify the grain and primary/foreign relationships for six entities. Distinguish order items from payments and refunds.
3. **Correctness:** demonstrate the order with two lines/two payments. Show separate aggregation prevents duplicate money.
4. **State changes:** replay the base batch, then late batch. Explain why a late older pending event cannot undo a newer successful event.
5. **Quality:** introduce a conflicting event or invalid parent in an isolated fixture and inspect the quarantine reason. Repair the parent and replay.
6. **Recovery:** run the injected-failure test. Show the prior mart survives and failed run remains auditable.
7. **Report:** compare base and late report. Under/over capture exceptions resolve; refunds change separately; conservation is not bank reconciliation.
8. **Trade-offs:** local SQLite/full snapshots are reproducible, not scalable CDC. Discuss the integration/operational evidence required before moving to cloud/Spark.

## Questions the code should answer

- Why does filtering `status='succeeded'` before row_number produce the wrong answer?
- What does `event_id` break ties on, and what would change if the source supplied a version number?
- Why is a refund a separate identity instead of marking a captured payment refunded and dropping its principal?
- How would late dimension arrivals differ from deleting an order already referenced by financial history?
- What does idempotent mean for business facts versus run audit rows?
- What happens when database commit succeeds but HTML export fails?
- How do you distinguish a technical success from a financially clean batch?
- Why is grouping by order date not a daily cashflow report?
- What new controls would an independent settlement feed make possible?

The repository demonstrates an implemented local batch workflow. Explain deployment and scale boundaries as design choices rather than inventing production experience.
