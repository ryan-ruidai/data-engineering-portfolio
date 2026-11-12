# Architecture and operating contract

## Layers
CSV bytes → SHA256 source identity → immutable `raw_rows` → contract validation → `clean_events` / `rejected_rows` → latest payment snapshot → successful snapshot → order mart → HTML + JSON report.

- Raw grain: unique source file hash + CSV record number. A replay does not duplicate raw rows. Every completed ingestion batch has its own `runs` record. Failed transactions roll back without a durable record.
- Clean grain: unique immutable event ID. Exact repeated business values are duplicates. Changed values for an existing ID are quarantined, never silently overwritten. When conflicting IDs occur in separate files the first accepted event wins; operator investigation is needed, not automatic reconciliation.
- Payment grain: one latest accepted event per payment. Business timestamp controls state, not arrival time. Event ID descending is an explicit synthetic tie-break contract.
- Mart grain: order; multiple successful payments are summed. Zero amounts remain valid.
- The quarantined latest event can mean that the snapshot reflects the last **accepted** state, not complete source truth. Do not publish business decisions without examining quality exceptions.

## Data contract
CSV header is exactly `event_id,payment_id,order_id,amount,status,updated_at`, UTF-8. Identifiers positive integers up to 15 digits; payment keys 1–32 ASCII letters/digits/underscore/hyphen; status is pending/succeeded/voided; CAD amount nonnegative up to eight integer digits and two fractional digits. Timestamp must be canonical `YYYY-MM-DD HH:MM:SS`, interpreted as UTC. Whitespace is trimmed. No implicit date, currency or status conversions.

The operational SQLite pipeline stores integer cents, avoiding binary floating arithmetic. The MySQL-oriented reference SQL remains separate and uses DECIMAL. These are different execution paths and must not be described as a validated MySQL ingestion service.

## Reliability
Each accepted batch is one SQLite transaction with `BEGIN IMMEDIATE`, foreign keys and a 10-second lock timeout. Rejected business records commit with their reason; infrastructure exceptions roll back the entire batch. A crashed/failed transaction has no durable run record (CLI exits nonzero); production monitoring would require an independent failure log. Invalid header or encoding fails before ingestion. Reports are generated after commit, so report failure does not lose ingested events; rerun is safe. Report writes are not atomic and concurrent report writers are unsupported.

A full snapshot recomputation via views handles late older/newer events without an arrival watermark. This is correct for the small batch workload, not a scalable CDC architecture. Raw records retain payload + source hash/row provenance; source CSV files remain unchanged. Single currency, no refunds, settlements, source order dimension or financial recognition. No external reconciliation ledger is included. Internal count and amount balances are consistency checks only.

## Interview demonstration
1. Run tests, then ingest the seed: 11 accepted → 7 latest → 5 successful → 4 orders, CAD 245.00.
2. Run ingestion again: zero insertions, 11 duplicates, unchanged business state.
3. Tests prove late old events do not rewind state and late newer voids do remove success.
4. Tests reject malformed amounts/status and conflicting event IDs; show the early-status-filter negative control.
5. Explain where MySQL integration, external reconciliation and production operations remain unverified.
