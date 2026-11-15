# Reporting metric contract

This catalog describes the implemented local snapshot, not a deployed semantic layer or accounting policy. All monetary fields are integer CAD cents. Base grain is **one order** in `gold_order_reconciliation`; aggregate each child source before joining.

| Metric | Definition | Business question / limit |
|---|---|---|
| Original order value | Net line values + order tax + shipping | Original contractual value, including cancelled orders; not revenue |
| Collectible | Original value except cancelled orders = 0 | Expected capture under this demonstration policy |
| Captured | Latest succeeded state per payment, summed per order | Current capture basis, not a sum of event history |
| Refunded | Latest succeeded state per refund, summed through its payment to order | Includes partial refunds; not silently capped |
| Net payment | Captured minus refunded | Current net basis; not profit, recognized revenue or settled cash |
| Capture variance | Captured minus collectible | Positive = over-capture; negative = under-capture; refunds excluded |
| Regional order count | Count of order-grain rows | Includes cancelled and zero-value orders; not paying customers |

## Time and dimension semantics

- No as-of cutoff: latest **accepted** event by UTC updated_at, then event_id descending. Rejected newer data can leave an older accepted state visible and must be investigated.
- Report generated_at is execution time, not business transaction time. ordered_at is order creation time, not capture/refund time. Grouping current balances by either does not produce daily cashflow.
- Region comes from the **current** full customer snapshot. Changing a customer's region reclassifies existing orders on the next refresh; there is no historical/SCD2 region. Previously persisted run reports remain their original snapshot.
- Snapshot amounts can be summed across disjoint orders or regions within one report. **Do not sum them across runs or days**; that double-counts balances.
- Region totals reconcile to report totals for collectible, captured, refunded and net amounts. Regional order counts reconcile to the number of order rows.

## Worked distinction

Order 501: collectible 100 CAD, capture 100, refund 10, net 90, variance 0. Another 5 CAD successful refund changes refund to 15 and net to 85, but collectible/capture remain 100 and variance remains 0. Calling this order underpaid by 15 would mix refund and capture reconciliation policies.

## Verification and decision boundary

`tests/test_commerce.py` tests all regional measures after late arrivals, region reclassification without monetary changes, and refund isolation from order value/capture variance, alongside the golden fixture and fanout tests. A committed run with passing conservation checks can still contain business exceptions; conservation is not an external bank reconciliation.

Before extending this to AI question answering, use this catalog to reject ambiguous requests such as “daily revenue” rather than silently relabel net payment. A future semantic layer needs separately tested time grains and business-approved definitions; none is claimed here.
