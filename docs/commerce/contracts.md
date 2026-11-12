# Business and quality contracts

## Source retail snapshot

- Four required tables, with exact columns defined in `commerce/fixtures.py`.
- Positive integer entity IDs; one or more valid lines per order; all customer/product/order references resolvable.
- Currency CAD only. Order status: pending, fulfilled, cancelled.
- Line value = `quantity * unit_price_cents - discount_cents`. Discount is a **line total**, not a per-unit amount. Quantity is positive; negative prices/discounts and discount above gross line value are invalid.
- Original order total = sum(line value) + **order-level** tax_cents + shipping_cents.
- Collectible value = original total, except cancelled orders are zero. This is a demo contract, not a universal retail policy.
- Product catalog does not override historical line prices. A source schema/relationship violation fails the snapshot rather than creating partial hidden orders.

## Payment and refund event contracts

Event IDs are immutable and unique **within each entity stream**. A payment_id has one immutable order_id; a refund_id has one immutable payment_id. Events are authoritative snapshots, not additive transactions. Ties use numeric event_id descending. The latest accepted event wins regardless of arrival order.

Payment states: pending / succeeded / voided. Refund states: pending / succeeded / failed. Payment zero is valid; refund must be positive. Amounts use nonnegative integer cents, not floating point. Timestamps are strict `YYYY-MM-DD HH:MM:SS` UTC. Unsupported currencies, malformed data, conflicting IDs and unresolved parents are recorded with reasons in `raw_event_rows`.

A duplicate row contributes to the batch input count but not to financial history again. A conflict never overwrites the first accepted immutable event. Unresolved references can be retried by replaying the source file after the parent arrives; quarantined rows do not reserve their event IDs. There is no automatic retry queue or hidden repair of source data.

## Reconciliation

- **Current captured amount:** sum of latest succeeded payments, after latest-state selection across all statuses.
- **Current refunded amount:** sum of latest succeeded refunds, including multiple partial refunds, mapped to the payment's immutable order.
- **Net payment snapshot:** captured minus refunded. Not revenue/profit/bank-settled cash.
- **Capture variance:** captured minus collectible order value. Refunds are deliberately excluded from this comparison. A partially refunded paid order is not incorrectly reported as underpaid.
- **Refund exposure:** successful refunds exceed the latest captured payment basis, or the parent payment no longer has a succeeded state. Amounts remain visible; they are never silently capped at zero.
- Refund exposure, quarantine and variance are investigation alerts. A succeeded run means the pipeline committed; it does **not** certify there are no business issues.

Batch counts satisfy input = accepted + duplicates + rejected. These are arrival metrics, not unique customer/order counts. Coverage and capture/refund/net conservation guard against transform loss/fanout; they are not independent bank controls. The order source and processor event source are independent synthetic systems, but no settlement file is supplied.

## Hand-calculated golden scenario

| Order | Original | Collectible | Base capture | Base refund | Base net | Late capture | Late refund |
|---|---:|---:|---:|---:|---:|---:|---:|
| 501 | 100.00 | 100.00 | 100.00 | 10.00 | 90.00 | 100.00 | 10.00 |
| 502 | 80.00 | 80.00 | 80.00 | 0.00 | 80.00 | 80.00 | 20.00 |
| 503 | 50.00 | 50.00 | 20.00 | 0.00 | 20.00 | 50.00 | 0.00 |
| 504 | 30.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| 505 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| 506 | 60.00 | 60.00 | 70.00 | 0.00 | 70.00 | 60.00 | 0.00 |

Amounts CAD. Order 501 has two lines and two payments, guarding against fanout. Order 504 demonstrates a later void. Order 505 has a zero-valued successful payment. The late batch includes an older pending event for P3 that must not replace its newer success.
