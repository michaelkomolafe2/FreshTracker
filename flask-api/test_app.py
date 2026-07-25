from datetime import date

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


def register_user(client, email="tester@example.com", password="password123"):
    response = client.post(
        "/auth/register",
        json={"email": email, "password": password},
    )
    assert response.status_code == 201
    return response


def csrf_headers(client):
    csrf_cookie = client.get_cookie("freshtracker_csrf")
    assert csrf_cookie is not None
    return {"X-CSRF-Token": csrf_cookie.value}


def test_health_returns_ok_status(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def test_register_login_and_logout_flow(client):
    response = client.post(
        "/auth/register",
        json={"email": "tester@example.com", "password": "password123"},
    )

    assert response.status_code == 201
    assert response.get_json()["user"] == {
        "id": 1,
        "email": "tester@example.com",
    }
    assert "freshtracker_session=" in response.headers.get("Set-Cookie", "")
    assert "freshtracker_csrf=" in response.headers.get("Set-Cookie", "")

    client.post("/auth/logout", headers=csrf_headers(client))

    response = client.post(
        "/auth/login",
        json={"email": "tester@example.com", "password": "password123"},
    )

    assert response.status_code == 200
    assert response.get_json()["user"] == {
        "id": 1,
        "email": "tester@example.com",
    }


def test_create_item_returns_created_item(client):
    register_user(client)

    response = client.post(
        "/items",
        headers=csrf_headers(client),
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


def test_create_item_predicts_missing_category(monkeypatch, client):
    monkeypatch.setattr("app.predict_category", lambda item_name: "Produce")
    register_user(client)

    response = client.post(
        "/items",
        headers=csrf_headers(client),
        json={"name": "Spinach"},
    )

    assert response.status_code == 201
    assert response.get_json()["item"] == {
        "id": 1,
        "name": "Spinach",
        "category": "Produce",
        "quantity": 1.0,
        "unit": "item",
        "expiry_date": date.today().isoformat(),
        "status": "active",
    }


def test_create_item_stacks_matching_items(monkeypatch, client):
    monkeypatch.setattr("app.predict_category", lambda item_name: "Produce")
    register_user(client)

    first_response = client.post(
        "/items",
        headers=csrf_headers(client),
        json={
            "name": "Spinach",
            "quantity": 2,
            "unit": "bag",
            "expiry_date": "2026-07-02",
        },
    )
    assert first_response.status_code == 201

    second_response = client.post(
        "/items",
        headers=csrf_headers(client),
        json={
            "name": "Spinach",
            "quantity": 3,
            "unit": "bag",
            "expiry_date": "2026-07-02",
        },
    )

    assert second_response.status_code == 201
    assert second_response.get_json()["item"] == {
        "id": 1,
        "name": "Spinach",
        "category": "Produce",
        "quantity": 5.0,
        "unit": "bag",
        "expiry_date": "2026-07-02",
        "status": "active",
    }

    response = client.get("/items")

    assert response.status_code == 200
    assert response.get_json()["items"] == [
        {
            "id": 1,
            "name": "Spinach",
            "category": "Produce",
            "quantity": 5.0,
            "unit": "bag",
            "expiry_date": "2026-07-02",
            "status": "active",
        }
    ]


def test_create_item_spills_overflow_into_new_stack(monkeypatch, client):
    monkeypatch.setattr("app.predict_category", lambda item_name: "Produce")
    register_user(client)

    first_response = client.post(
        "/items",
        headers=csrf_headers(client),
        json={
            "name": "Tomatoes",
            "quantity": 8,
            "unit": "box",
            "expiry_date": "2026-07-02",
        },
    )
    assert first_response.status_code == 201

    second_response = client.post(
        "/items",
        headers=csrf_headers(client),
        json={
            "name": "Tomatoes",
            "quantity": 5,
            "unit": "box",
            "expiry_date": "2026-07-02",
        },
    )

    assert second_response.status_code == 201
    assert second_response.get_json()["item"] == {
        "id": 1,
        "name": "Tomatoes",
        "category": "Produce",
        "quantity": 10.0,
        "unit": "box",
        "expiry_date": "2026-07-02",
        "status": "active",
    }
    assert second_response.get_json()["stacked_items"] == [
        {
            "id": 1,
            "name": "Tomatoes",
            "category": "Produce",
            "quantity": 10.0,
            "unit": "box",
            "expiry_date": "2026-07-02",
            "status": "active",
        },
        {
            "id": 2,
            "name": "Tomatoes",
            "category": "Produce",
            "quantity": 3.0,
            "unit": "box",
            "expiry_date": "2026-07-02",
            "status": "active",
        },
    ]

    response = client.get("/items")

    assert response.status_code == 200
    assert response.get_json()["items"] == [
        {
            "id": 1,
            "name": "Tomatoes",
            "category": "Produce",
            "quantity": 10.0,
            "unit": "box",
            "expiry_date": "2026-07-02",
            "status": "active",
        },
        {
            "id": 2,
            "name": "Tomatoes",
            "category": "Produce",
            "quantity": 3.0,
            "unit": "box",
            "expiry_date": "2026-07-02",
            "status": "active",
        },
    ]


def test_create_item_rejects_missing_name(client):
    register_user(client)
    response = client.post("/items", headers=csrf_headers(client), json={"quantity": 1})

    assert response.status_code == 400
    assert response.get_json() == {"error": "missing required field(s): name"}


def test_create_item_rejects_invalid_expiry_date(client):
    register_user(client)
    response = client.post(
        "/items",
        headers=csrf_headers(client),
        json={
            "name": "Milk",
            "quantity": 1,
            "unit": "bottle",
            "expiry_date": "tomorrow",
        },
    )

    assert response.status_code == 400
    assert response.get_json() == {"error": "expiry_date must be an ISO date string"}


def test_list_items_only_returns_active_items(monkeypatch, client):
    monkeypatch.setattr("app.predict_category", lambda item_name: "Produce")
    register_user(client)

    client.post(
        "/items",
        headers=csrf_headers(client),
        json={
            "name": "Spinach",
            "quantity": 1,
            "unit": "bag",
            "expiry_date": "2026-07-02",
        },
    )
    created = client.post(
        "/items",
        headers=csrf_headers(client),
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
            "category": "Produce",
            "quantity": 1.0,
            "unit": "bag",
            "expiry_date": "2026-07-02",
            "status": "active",
        }
    ]


def test_patch_item_updates_status(client):
    register_user(client)
    item = client.post(
        "/items",
        headers=csrf_headers(client),
        json={
            "name": "Bread",
            "quantity": 1,
            "unit": "loaf",
            "expiry_date": "2026-07-03",
        },
    ).get_json()["item"]

    response = client.patch(
        f"/items/{item['id']}",
        headers=csrf_headers(client),
        json={"status": "wasted"},
    )

    assert response.status_code == 200
    assert response.get_json()["item"]["status"] == "wasted"


def test_patch_item_rejects_invalid_status(client):
    register_user(client)
    response = client.patch("/items/1", headers=csrf_headers(client), json={"status": "active"})

    assert response.status_code == 400
    assert response.get_json() == {"error": "status must be either 'used' or 'wasted'"}


def test_patch_item_returns_not_found(client):
    register_user(client)
    response = client.patch("/items/999", headers=csrf_headers(client), json={"status": "used"})

    assert response.status_code == 404
    assert response.get_json() == {"error": "item not found"}
