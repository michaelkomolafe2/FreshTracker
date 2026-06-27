import pytest

from app import create_app, db


@pytest.fixture()
def app():
    test_app = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        }
    )

    with test_app.app_context():
        db.create_all()
        yield test_app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


def test_health_returns_ok_status(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def test_create_item_returns_created_item(client):
    response = client.post(
        "/items",
        json={
            "name": "Milk",
            "category": "Dairy",
            "quantity": 1.5,
            "unit": "liters",
            "expiry_date": "2026-07-01",
        },
    )

    assert response.status_code == 201
    assert response.get_json()["item"] == {
        "id": 1,
        "name": "Milk",
        "category": "Dairy",
        "quantity": 1.5,
        "unit": "liters",
        "expiry_date": "2026-07-01",
        "status": "active",
    }


def test_create_item_rejects_missing_required_fields(client):
    response = client.post("/items", json={"name": "Milk"})

    assert response.status_code == 400
    assert response.get_json() == {
        "error": "missing required field(s): quantity, unit, expiry_date"
    }


def test_create_item_rejects_invalid_expiry_date(client):
    response = client.post(
        "/items",
        json={
            "name": "Milk",
            "quantity": 1,
            "unit": "bottle",
            "expiry_date": "tomorrow",
        },
    )

    assert response.status_code == 400
    assert response.get_json() == {"error": "expiry_date must be an ISO date string"}


def test_list_items_only_returns_active_items(client):
    client.post(
        "/items",
        json={
            "name": "Spinach",
            "quantity": 1,
            "unit": "bag",
            "expiry_date": "2026-07-02",
        },
    )
    created = client.post(
        "/items",
        json={
            "name": "Yogurt",
            "quantity": 2,
            "unit": "cups",
            "expiry_date": "2026-07-01",
        },
    ).get_json()["item"]
    client.patch(f"/items/{created['id']}", json={"status": "used"})

    response = client.get("/items")

    assert response.status_code == 200
    assert response.get_json()["items"] == [
        {
            "id": 1,
            "name": "Spinach",
            "category": None,
            "quantity": 1.0,
            "unit": "bag",
            "expiry_date": "2026-07-02",
            "status": "active",
        }
    ]


def test_patch_item_updates_status(client):
    item = client.post(
        "/items",
        json={
            "name": "Bread",
            "quantity": 1,
            "unit": "loaf",
            "expiry_date": "2026-07-03",
        },
    ).get_json()["item"]

    response = client.patch(f"/items/{item['id']}", json={"status": "wasted"})

    assert response.status_code == 200
    assert response.get_json()["item"]["status"] == "wasted"


def test_patch_item_rejects_invalid_status(client):
    response = client.patch("/items/1", json={"status": "active"})

    assert response.status_code == 400
    assert response.get_json() == {"error": "status must be either 'used' or 'wasted'"}


def test_patch_item_returns_not_found(client):
    response = client.patch("/items/999", json={"status": "used"})

    assert response.status_code == 404
    assert response.get_json() == {"error": "item not found"}
