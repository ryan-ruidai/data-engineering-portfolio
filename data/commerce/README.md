# Synthetic processor exports

Every identifier and value is fictional. `commerce/fixtures.py` is the canonical reproducible generator for these CSVs and a four-table SQLite retail source. No binary source database is published. Running `python3 -m commerce.run` materializes the source database under ignored build/commerce/inputs without overwriting an existing input DB.

Base: payments.csv + refunds.csv. Next batch: payments_late.csv + refunds_late.csv. The late files are deltas, not replacements of previously accepted event history. Existing event history is required for the full late-batch result.
