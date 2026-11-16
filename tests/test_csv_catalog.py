import tempfile
import unittest
from pathlib import Path

from examples.csv_catalog.catalog import Product, load_products


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.source = Path(self.tmp.name) / "products.csv"

    def write_source(self, text):
        self.source.write_text(text, encoding="utf-8")
        return self.source

    def test_shipped_fixture_has_100_typed_rows(self):
        source = Path(__file__).resolve().parents[1] / "examples/csv_catalog/products.csv"
        products = load_products(source)
        self.assertEqual(len(products), 100)
        for i, product in enumerate(products, 1):
            self.assertIsInstance(product, Product)
            self.assertEqual(product.name, f"Demo Product {i:03d}")
            self.assertEqual(product.stock_quantity, (i * 7) % 31)
            self.assertIsInstance(product.stock_quantity, int)
        self.assertEqual(len({id(p) for p in products}), 100)

    def test_bom_quoted_comma_and_zero(self):
        source = self.write_source('\ufeffname,stock_quantity\n"Demo, Special",0\n')
        products = load_products(source)
        self.assertEqual(products[0].name, "Demo, Special")
        self.assertEqual(products[0].stock_quantity, 0)

    def test_header_only_is_empty(self):
        self.assertEqual(load_products(self.write_source("name,stock_quantity\n")), [])

    def test_objects_and_loads_are_independent(self):
        source = self.write_source("name,stock_quantity\nA,1\nB,2\n")
        first, second = load_products(source), load_products(source)
        first[0].stock_quantity = 99
        self.assertEqual(first[1].stock_quantity, 2)
        self.assertEqual(second[0].stock_quantity, 1)
        self.assertIsNot(first, second)

    def test_invalid_integer_is_not_silently_skipped(self):
        with self.assertRaises(ValueError):
            load_products(self.write_source("name,stock_quantity\nA,unknown\n"))


if __name__ == "__main__":
    unittest.main()
