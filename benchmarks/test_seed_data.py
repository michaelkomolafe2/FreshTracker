from datetime import date, timedelta

from seed_data import (
    ITEM_COUNT,
    InventoryItem,
    User,
    build_inventory_items,
    create_app,
    db,
    seed_database,
)


def test_build_inventory_items_creates_repeatable_active_dataset():
    items = build_inventory_items(user_id=42, today=date(2026, 8, 21))

    assert len(items) == ITEM_COUNT
    assert all(item.user_id == 42 for item in items)
    assert all(item.status == "active" for item in items)
    assert all(item.quantity == 1.0 for item in items)
    assert len({item.stack_key for item in items}) == ITEM_COUNT
    assert items[0].expiry_date == date(2026, 8, 21)
    assert items[-1].expiry_date == date(2026, 8, 21) + timedelta(days=9)


def test_seed_database_bulk_inserts_user_and_inventory(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'benchmark.db'}"
    app = create_app({"SQLALCHEMY_DATABASE_URI": database_url})
    with app.app_context():
        db.create_all()

    result = seed_database(
        database_url,
        email="BENCHMARK@example.com",
        password="Benchmark-Password-1234",
    )

    assert result == {
        "email": "benchmark@example.com",
        "inventory_items": ITEM_COUNT,
    }
    with app.app_context():
        assert User.query.one().email == "benchmark@example.com"
        assert InventoryItem.query.count() == ITEM_COUNT
        assert InventoryItem.query.filter_by(status="active").count() == ITEM_COUNT
