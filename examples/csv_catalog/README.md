# CSV catalog → Python objects

A small, standalone CSV adapter using only Python's standard library. It does not change or feed the main commerce pipeline.

## Source contract

`products.csv` contains **100 fictional stock records**, generated specifically for this example. It is not a real retailer's catalog or stock feed, and contains no personal data.

| Field | CSV representation | Object attribute |
|---|---|---|
| `name` | Nonempty text, e.g. `Demo Product 001` | `product.name` (string) |
| `stock_quantity` | Whole-number text, e.g. `7` | `product.stock_quantity` (integer) |

Generation rule: for `i` from 1 through 100, name is `Demo Product {i:03d}` and quantity is `(i * 7) % 31`. Zero stock is valid. The source is a complete snapshot, not stock movements or financial events.

## Run

Requires Python 3.9+; no packages or accounts needed. From the repository root:

```sh
python3 examples/csv_catalog/catalog.py
python3 -m unittest discover -s tests -p 'test_csv_catalog.py' -v
```

Expected console output:

```text
100
Demo Product 001
7
```

The code has English comments explaining the class, `self`, instance attributes, standalone function, file context manager, `DictReader`, integer conversion, loop, `append`, return and attribute access.

## Behavior and boundary

- One data row becomes one independent `Product` object; the list holds references to all objects.
- Loading twice produces two separate lists and new objects. This is not database ingestion or deduplication.
- A header-only CSV returns an empty list; the command avoids indexing it.
- Input must have the stated columns and valid integer quantities. This intentionally small example does not validate the complete schema, reject negative stock or blank names, quarantine bad rows, handle duplicate products, or persist records. Missing fields or invalid integers raise exceptions rather than being silently skipped.
- Loading all rows into a list is suitable for this 100-record sample, not a claim of large-file scalability.
