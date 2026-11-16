"""Load a small fictional stock catalog into Python objects."""

import csv
from pathlib import Path


class Product:
    # Initialize a new Product object with its own attribute values.
    def __init__(self, name, stock_quantity):
        # self refers to this object, not to the incoming values.
        self.name = name
        self.stock_quantity = stock_quantity


def load_products(file_path):
    # This standalone function does not belong to a Product instance.
    # Create a new list each time the function is called.
    products = []

    # Open the CSV as text; close it automatically when this block ends.
    with open(file_path, encoding="utf-8-sig", newline="") as file:
        # Use the first CSV row as column names.
        reader = csv.DictReader(file)
        for row in reader:
            # CSV fields are strings. Convert the quantity to an integer.
            # Each loop creates a separate Product object.
            product = Product(row["name"], int(row["stock_quantity"]))
            # Keep a reference to each object in the list.
            products.append(product)

    # Return only after all data rows have been processed.
    return products


if __name__ == "__main__":
    # Find the input beside this script, regardless of the current folder.
    source = Path(__file__).with_name("products.csv")
    products = load_products(source)
    print(len(products))
    # A header-only CSV produces an empty list, so check before indexing.
    if products:
        print(products[0].name)
        print(products[0].stock_quantity)
