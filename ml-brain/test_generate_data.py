import csv
import importlib.util
from pathlib import Path


SCRIPT_PATH = Path(__file__).with_name("generate_data.py")


def load_generate_data_module():
    spec = importlib.util.spec_from_file_location("generate_data", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_grocery_items_are_valid_training_rows():
    generate_data = load_generate_data_module()

    generate_data.validate_items(generate_data.GROCERY_ITEMS)

    assert len(generate_data.GROCERY_ITEMS) == 150
    assert {
        category for _, category in generate_data.GROCERY_ITEMS
    } == generate_data.CATEGORIES


def test_write_grocery_csv_creates_expected_columns(tmp_path):
    generate_data = load_generate_data_module()
    output_path = tmp_path / "grocery_data.csv"

    generate_data.write_grocery_csv(generate_data.GROCERY_ITEMS, output_path)

    with output_path.open(newline="", encoding="utf-8") as csv_file:
        rows = list(csv.DictReader(csv_file))

    assert csv_file.closed
    assert rows[0] == {"ingredient_name": "milk", "category": "Dairy"}
    assert len(rows) == 150
    assert set(rows[0].keys()) == {"ingredient_name", "category"}
