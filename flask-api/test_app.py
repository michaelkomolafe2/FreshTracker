from datetime import date, timedelta

import pytest
import requests
from sqlalchemy.exc import StatementError

from app import (
    InventoryItem,
    Session,
    User,
    WasteLog,
    build_stack_key,
    classify_expiry_date,
    create_app,
    db,
    mail,
    now_utc,
    recipe_ingredients_cache_key,
    send_expiry_alerts,
)


def expected_expiry_fields(expiry_date):
    days_until_expiry = (date.fromisoformat(expiry_date) - date.today()).days
    if days_until_expiry < 0:
        expiry_status = "expired"
    elif days_until_expiry <= 7:
        expiry_status = "expiring_soon"
    else:
        expiry_status = "active"

    return {
        "days_until_expiry": days_until_expiry,
        "expiry_status": expiry_status,
    }


@pytest.fixture()
def app():
    test_app = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "MAIL_ENABLED": False,
            "MAIL_SUPPRESS_SEND": True,
            "SPOONACULAR_API_KEY": "test-spoonacular-key",
        }
    )

    with test_app.app_context():
        db.create_all()

    yield test_app

    with test_app.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


def register_user(client, email="tester@example.com", password="Password-1234"):
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


class StubSpoonacularResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code
        self.ok = 200 <= status_code < 300

    def json(self):
        return self.payload


def test_health_returns_ok_status(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}
    assert response.headers["Content-Security-Policy"] == (
        "default-src 'none'; base-uri 'none'; form-action 'none'; "
        "frame-ancestors 'none';"
    )


def test_recipe_suggestions_require_authentication(client):
    response = client.post(
        "/recipe-suggestions",
        json={"ingredients": ["milk"]},
    )

    assert response.status_code == 401
    assert response.get_json() == {"error": "authentication required"}


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({}, "missing required field(s): ingredients"),
        ({"ingredients": "milk"}, "ingredients must be a list"),
        ({"ingredients": []}, "ingredients must contain at least one item"),
        (
            {"ingredients": ["milk", ""]},
            "each ingredient must be a non-empty string",
        ),
        (
            {"ingredients": ["tomatoes, chopped"]},
            "ingredients must not contain commas",
        ),
        (
            {"ingredients": [f"ingredient-{index}" for index in range(26)]},
            "ingredients must contain at most 25 items",
        ),
    ],
)
def test_recipe_suggestions_reject_invalid_ingredients(
    client,
    payload,
    message,
):
    register_user(client)

    response = client.post(
        "/recipe-suggestions",
        headers=csrf_headers(client),
        json=payload,
    )

    assert response.status_code == 400
    assert response.get_json() == {"error": message}


def test_recipe_suggestions_call_spoonacular_with_normalized_ingredients(
    client,
    monkeypatch,
):
    calls = []
    recipes = [
        {
            "id": 123,
            "title": "Tomato Spinach Pasta",
            "usedIngredientCount": 2,
            "missedIngredientCount": 1,
        }
    ]

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return StubSpoonacularResponse(recipes)

    monkeypatch.setattr("app.requests.get", fake_get)
    register_user(client)

    response = client.post(
        "/recipe-suggestions",
        headers=csrf_headers(client),
        json={"ingredients": [" Spinach ", "TOMATO", "spinach"]},
    )

    assert response.status_code == 200
    assert response.get_json() == {
        "ingredients": ["spinach", "tomato"],
        "recipes": recipes,
        "source": "spoonacular",
    }
    assert len(calls) == 1
    url, kwargs = calls[0]
    assert url == "https://api.spoonacular.com/recipes/findByIngredients"
    assert kwargs["headers"] == {"x-api-key": "test-spoonacular-key"}
    assert kwargs["params"] == {
        "ingredients": "spinach,tomato",
        "number": 10,
        "ranking": 1,
        "ignorePantry": "true",
    }
    assert kwargs["timeout"] == 8


def test_equivalent_recipe_requests_share_cache(client, monkeypatch):
    calls = []
    recipes = [{"id": 456, "title": "Tomato Omelette"}]

    def fake_get(*_args, **_kwargs):
        calls.append(True)
        return StubSpoonacularResponse(recipes)

    monkeypatch.setattr("app.requests.get", fake_get)
    register_user(client)
    headers = csrf_headers(client)

    first_response = client.post(
        "/recipe-suggestions",
        headers=headers,
        json={"ingredients": ["Egg", "tomato"]},
    )
    second_response = client.post(
        "/recipe-suggestions",
        headers=headers,
        json={"ingredients": [" TOMATO ", "egg", "EGG"]},
    )

    assert first_response.get_json()["source"] == "spoonacular"
    assert second_response.status_code == 200
    assert second_response.get_json() == {
        "ingredients": ["egg", "tomato"],
        "recipes": recipes,
        "source": "cache",
    }
    assert len(calls) == 1


def test_recipe_suggestions_serve_stale_cache_on_rate_limit(
    app,
    client,
    monkeypatch,
):
    recipes = [{"id": 789, "title": "Spinach Soup"}]
    responses = [
        StubSpoonacularResponse(recipes),
        StubSpoonacularResponse({"message": "rate limited"}, status_code=429),
    ]
    monkeypatch.setattr(
        "app.requests.get",
        lambda *_args, **_kwargs: responses.pop(0),
    )
    register_user(client)
    headers = csrf_headers(client)
    payload = {"ingredients": ["spinach"]}

    first_response = client.post(
        "/recipe-suggestions",
        headers=headers,
        json=payload,
    )
    cache_key = recipe_ingredients_cache_key(("spinach",))
    cache = app.extensions["recipe_suggestion_cache"]
    with cache.lock:
        cache.fresh.pop(cache_key)

    stale_response = client.post(
        "/recipe-suggestions",
        headers=headers,
        json=payload,
    )

    assert first_response.status_code == 200
    assert stale_response.status_code == 200
    assert stale_response.get_json() == {
        "ingredients": ["spinach"],
        "recipes": recipes,
        "source": "stale-cache",
    }


@pytest.mark.parametrize(
    ("status_code", "expected_status", "message"),
    [
        (402, 503, "recipe provider rate limit reached"),
        (429, 503, "recipe provider rate limit reached"),
        (500, 502, "recipe provider temporarily unavailable"),
    ],
)
def test_recipe_suggestions_return_clean_provider_errors(
    client,
    monkeypatch,
    status_code,
    expected_status,
    message,
):
    monkeypatch.setattr(
        "app.requests.get",
        lambda *_args, **_kwargs: StubSpoonacularResponse(
            {"message": "upstream details"},
            status_code=status_code,
        ),
    )
    register_user(client)

    response = client.post(
        "/recipe-suggestions",
        headers=csrf_headers(client),
        json={"ingredients": ["milk"]},
    )

    assert response.status_code == expected_status
    assert response.get_json() == {"error": message}


def test_recipe_suggestions_return_clean_timeout_error(client, monkeypatch):
    def raise_timeout(*_args, **_kwargs):
        raise requests.Timeout("upstream timed out")

    monkeypatch.setattr("app.requests.get", raise_timeout)
    register_user(client)

    response = client.post(
        "/recipe-suggestions",
        headers=csrf_headers(client),
        json={"ingredients": ["milk"]},
    )

    assert response.status_code == 503
    assert response.get_json() == {
        "error": "recipe provider temporarily unavailable"
    }


def test_recipe_suggestions_reject_invalid_provider_json(
    client,
    monkeypatch,
):
    monkeypatch.setattr(
        "app.requests.get",
        lambda *_args, **_kwargs: StubSpoonacularResponse(
            {"recipes": []},
        ),
    )
    register_user(client)

    response = client.post(
        "/recipe-suggestions",
        headers=csrf_headers(client),
        json={"ingredients": ["milk"]},
    )

    assert response.status_code == 502
    assert response.get_json() == {
        "error": "recipe provider returned an invalid response"
    }


def test_recipe_suggestions_return_clean_error_when_api_key_is_missing(
    app,
    client,
):
    app.config["SPOONACULAR_API_KEY"] = ""
    register_user(client)

    response = client.post(
        "/recipe-suggestions",
        headers=csrf_headers(client),
        json={"ingredients": ["milk"]},
    )

    assert response.status_code == 503
    assert response.get_json() == {
        "error": "recipe suggestions are not configured"
    }


def test_unknown_api_route_returns_json_error(client):
    response = client.get("/does-not-exist")

    assert response.status_code == 404
    assert response.is_json


def test_register_login_and_logout_flow(client):
    response = client.post(
        "/auth/register",
        json={"email": "tester@example.com", "password": "Password-1234"},
    )

    assert response.status_code == 201
    assert response.get_json()["user"] == {
        "id": 1,
        "email": "tester@example.com",
    }
    set_cookie_headers = response.headers.getlist("Set-Cookie")
    assert any("freshtracker_session=" in header for header in set_cookie_headers)
    assert any("freshtracker_csrf=" in header for header in set_cookie_headers)

    client.post("/auth/logout", headers=csrf_headers(client))

    response = client.post(
        "/auth/login",
        json={"email": "tester@example.com", "password": "Password-1234"},
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
        **expected_expiry_fields("2026-07-01"),
        "status": "active",
    }


@pytest.mark.parametrize(
    ("days_until_expiry", "expected_status"),
    [
        (-1, "expired"),
        (0, "expiring_soon"),
        (7, "expiring_soon"),
        (8, "active"),
    ],
)
def test_classify_expiry_date_uses_strict_boundaries(
    days_until_expiry,
    expected_status,
):
    today = date(2026, 7, 30)

    assert classify_expiry_date(
        today + timedelta(days=days_until_expiry),
        today=today,
    ) == expected_status


def test_new_inventory_item_defaults_alert_sent_to_false(app, client):
    register_user(client)
    client.post(
        "/items",
        headers=csrf_headers(client),
        json={"name": "Milk"},
    )

    with app.app_context():
        assert InventoryItem.query.one().alert_sent is False


def test_expiry_alert_job_emails_each_item_only_once(app):
    today = date(2026, 7, 30)

    with app.app_context():
        user = User(
            email="alerts@example.com",
            password_hash="not-used-by-this-test",
        )
        db.session.add(user)
        db.session.flush()

        items = [
            InventoryItem(
                user_id=user.id,
                name="Milk",
                stack_key=build_stack_key("Milk", "bottle", today),
                quantity=1,
                unit="bottle",
                expiry_date=today,
                status="active",
            ),
            InventoryItem(
                user_id=user.id,
                name="Yogurt",
                stack_key=build_stack_key(
                    "Yogurt",
                    "pot",
                    today + timedelta(days=3),
                ),
                quantity=2,
                unit="pot",
                expiry_date=today + timedelta(days=3),
                status="active",
            ),
            InventoryItem(
                user_id=user.id,
                name="Cheese",
                stack_key=build_stack_key(
                    "Cheese",
                    "block",
                    today + timedelta(days=4),
                ),
                quantity=1,
                unit="block",
                expiry_date=today + timedelta(days=4),
                status="active",
            ),
            InventoryItem(
                user_id=user.id,
                name="Bread",
                stack_key=build_stack_key("Bread", "loaf", today),
                quantity=1,
                unit="loaf",
                expiry_date=today,
                status="used",
            ),
        ]
        db.session.add_all(items)
        db.session.commit()
        app.config["MAIL_ENABLED"] = True

        with mail.record_messages() as delivered_messages:
            first_result = send_expiry_alerts(today=today)
            second_result = send_expiry_alerts(today=today)

        assert first_result == {"claimed": 2, "sent": 2, "failed": 0}
        assert second_result == {"claimed": 0, "sent": 0, "failed": 0}
        assert len(delivered_messages) == 2
        assert {
            message.subject for message in delivered_messages
        } == {
            "FreshTracker: Milk expires soon",
            "FreshTracker: Yogurt expires soon",
        }
        assert all(
            message.recipients == ["alerts@example.com"]
            for message in delivered_messages
        )
        alert_states = {
            item.name: item.alert_sent
            for item in InventoryItem.query.order_by(InventoryItem.id).all()
        }
        assert alert_states == {
            "Milk": True,
            "Yogurt": True,
            "Cheese": False,
            "Bread": False,
        }


def test_expiry_alert_dry_run_does_not_claim_or_email_items(app):
    today = date(2026, 7, 30)

    with app.app_context():
        user = User(
            email="dry-run@example.com",
            password_hash="not-used-by-this-test",
        )
        db.session.add(user)
        db.session.flush()
        item = InventoryItem(
            user_id=user.id,
            name="Milk",
            stack_key=build_stack_key("Milk", "bottle", today),
            quantity=1,
            unit="bottle",
            expiry_date=today,
            status="active",
        )
        db.session.add(item)
        db.session.commit()

        with mail.record_messages() as delivered_messages:
            result = send_expiry_alerts(today=today)

        assert result == {
            "claimed": 0,
            "sent": 0,
            "failed": 0,
            "previewed": 1,
        }
        assert delivered_messages == []
        assert InventoryItem.query.one().alert_sent is False


def test_waste_log_records_supported_action_and_timestamp(app, client):
    register_user(client)
    client.post(
        "/items",
        headers=csrf_headers(client),
        json={"name": "Milk", "category": "Dairy"},
    )

    with app.app_context():
        item = InventoryItem.query.one()
        user = User.query.one()
        log = WasteLog(
            item_id=item.id,
            user_id=user.id,
            action="wasted",
            category=item.category,
        )
        db.session.add(log)
        db.session.commit()
        db.session.refresh(log)

        assert log.action == "wasted"
        assert log.category == "Dairy"
        assert log.logged_at is not None


def test_waste_log_rejects_unsupported_action(app, client):
    register_user(client)
    client.post(
        "/items",
        headers=csrf_headers(client),
        json={"name": "Milk"},
    )

    with app.app_context():
        log = WasteLog(
            item_id=InventoryItem.query.one().id,
            user_id=User.query.one().id,
            action="donated",
        )
        db.session.add(log)

        with pytest.raises(StatementError):
            db.session.commit()
        db.session.rollback()


def test_waste_log_category_summary_requires_authentication(client):
    response = client.get("/waste-logs/category-summary")

    assert response.status_code == 401
    assert response.get_json() == {"error": "authentication required"}


def test_waste_log_category_summary_returns_empty_categories(client):
    register_user(client)

    response = client.get("/waste-logs/category-summary")

    assert response.status_code == 200
    assert response.get_json() == {"categories": []}


def test_waste_log_category_summary_groups_actions_and_scopes_to_user(app, client):
    register_user(client)

    with app.app_context():
        current_user = User.query.filter_by(email="tester@example.com").one()
        other_user = User(
            email="other@example.com",
            password_hash="not-used-by-this-test",
        )
        db.session.add(other_user)
        db.session.flush()

        log_specs = [
            (current_user, "Milk", "Dairy", "used"),
            (current_user, "Yogurt", "Dairy", "used"),
            (current_user, "Cheese", "Dairy", "wasted"),
            (current_user, "Bread", "Bakery", "wasted"),
            (current_user, "Mystery item", None, "used"),
            (other_user, "Other milk", "Dairy", "wasted"),
        ]
        for user, name, category, action in log_specs:
            item = InventoryItem(
                user_id=user.id,
                name=name,
                stack_key=build_stack_key(name, "item", date.today()),
                category=category,
                quantity=1,
                unit="item",
                expiry_date=date.today(),
                status=action,
            )
            db.session.add(item)
            db.session.flush()
            db.session.add(
                WasteLog(
                    item_id=item.id,
                    user_id=user.id,
                    action=action,
                    category=category,
                )
            )
        db.session.commit()

    response = client.get("/waste-logs/category-summary")

    assert response.status_code == 200
    assert response.get_json() == {
        "categories": [
            {
                "category": None,
                "used": 1,
                "wasted": 0,
            },
            {
                "category": "Bakery",
                "used": 0,
                "wasted": 1,
            },
            {
                "category": "Dairy",
                "used": 2,
                "wasted": 1,
            },
        ]
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
        "days_until_expiry": 0,
        "expiry_status": "expiring_soon",
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
        **expected_expiry_fields("2026-07-02"),
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
            **expected_expiry_fields("2026-07-02"),
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
        **expected_expiry_fields("2026-07-02"),
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
            **expected_expiry_fields("2026-07-02"),
            "status": "active",
        },
        {
            "id": 2,
            "name": "Tomatoes",
            "category": "Produce",
            "quantity": 3.0,
            "unit": "box",
            "expiry_date": "2026-07-02",
            **expected_expiry_fields("2026-07-02"),
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
            **expected_expiry_fields("2026-07-02"),
            "status": "active",
        },
        {
            "id": 2,
            "name": "Tomatoes",
            "category": "Produce",
            "quantity": 3.0,
            "unit": "box",
            "expiry_date": "2026-07-02",
            **expected_expiry_fields("2026-07-02"),
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
    client.patch(
        f"/items/{created['id']}",
        headers=csrf_headers(client),
        json={"status": "used"},
    )

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
            **expected_expiry_fields("2026-07-02"),
            "status": "active",
        }
    ]


@pytest.mark.parametrize("status", ["used", "wasted"])
def test_patch_item_updates_status_and_creates_waste_log(app, client, status):
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
        json={"status": status},
    )

    assert response.status_code == 200
    assert response.get_json()["item"]["status"] == status
    with app.app_context():
        log = WasteLog.query.one()
        assert log.item_id == item["id"]
        assert log.user_id == User.query.one().id
        assert log.action == status
        assert log.category == InventoryItem.query.one().category
        assert log.logged_at is not None


def test_patch_item_rolls_back_status_when_waste_log_creation_fails(
    app,
    client,
    monkeypatch,
):
    register_user(client)
    item = client.post(
        "/items",
        headers=csrf_headers(client),
        json={"name": "Bread", "category": "Bakery"},
    ).get_json()["item"]

    def fail_waste_log_creation(**_kwargs):
        raise RuntimeError("forced waste log failure")

    monkeypatch.setattr("app.WasteLog", fail_waste_log_creation)

    with pytest.raises(RuntimeError, match="forced waste log failure"):
        client.patch(
            f"/items/{item['id']}",
            headers=csrf_headers(client),
            json={"status": "used"},
        )

    with app.app_context():
        db.session.expire_all()
        assert InventoryItem.query.one().status == "active"
        assert WasteLog.query.count() == 0


def test_patch_item_rejects_a_second_transition(app, client):
    register_user(client)
    item = client.post(
        "/items",
        headers=csrf_headers(client),
        json={"name": "Bread"},
    ).get_json()["item"]
    headers = csrf_headers(client)

    first_response = client.patch(
        f"/items/{item['id']}",
        headers=headers,
        json={"status": "used"},
    )
    second_response = client.patch(
        f"/items/{item['id']}",
        headers=headers,
        json={"status": "wasted"},
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 409
    assert second_response.get_json() == {"error": "item is no longer active"}
    with app.app_context():
        assert InventoryItem.query.one().status == "used"
        assert WasteLog.query.count() == 1


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


def test_authenticated_writes_require_a_matching_csrf_token(client):
    register_user(client)

    response = client.post("/items", json={"name": "Milk"})

    assert response.status_code == 403
    assert response.get_json() == {"error": "missing CSRF token"}


def test_patch_item_requires_a_matching_csrf_token(client):
    register_user(client)
    item = client.post(
        "/items",
        headers=csrf_headers(client),
        json={"name": "Milk"},
    ).get_json()["item"]

    response = client.patch(
        f"/items/{item['id']}",
        json={"status": "used"},
    )

    assert response.status_code == 403
    assert response.get_json() == {"error": "missing CSRF token"}


def test_logout_requires_csrf_protection(client):
    register_user(client)

    response = client.post("/auth/logout", json={})

    assert response.status_code == 403
    assert response.get_json() == {"error": "missing CSRF token"}


def test_write_rejects_an_untrusted_origin(client):
    register_user(client)
    headers = {**csrf_headers(client), "Origin": "https://malicious.example"}

    response = client.post("/items", headers=headers, json={"name": "Milk"})

    assert response.status_code == 403
    assert response.get_json() == {"error": "invalid origin"}


def test_inventory_is_private_to_its_owner(app):
    first_client = app.test_client()
    second_client = app.test_client()
    register_user(first_client, email="first@example.com")

    item = first_client.post(
        "/items",
        headers=csrf_headers(first_client),
        json={"name": "Milk", "expiry_date": "2026-07-01"},
    ).get_json()["item"]

    register_user(second_client, email="second@example.com")

    assert second_client.get("/items").get_json() == {"items": []}
    response = second_client.patch(
        f"/items/{item['id']}",
        headers=csrf_headers(second_client),
        json={"status": "wasted"},
    )

    assert response.status_code == 404
    assert first_client.get("/items").get_json()["items"][0]["status"] == "active"


def test_session_idle_expiry_blocks_inventory_access(app, client):
    register_user(client)

    with app.app_context():
        session = Session.query.one()
        session.last_seen_at = now_utc() - timedelta(minutes=31)
        db.session.commit()

    response = client.get("/auth/me")

    assert response.status_code == 200
    assert response.get_json() == {
        "authenticated": False,
        "session_expired": True,
        "user": None,
    }

    response = client.get("/items")

    assert response.status_code == 401
    assert response.get_json() == {"error": "authentication required"}


def test_new_login_revokes_an_existing_session(app):
    original_client = app.test_client()
    new_client = app.test_client()
    register_user(original_client)

    response = new_client.post(
        "/auth/login",
        json={"email": "tester@example.com", "password": "Password-1234"},
    )

    assert response.status_code == 200
    assert original_client.get("/items").status_code == 401
    assert new_client.get("/items").status_code == 200


def test_create_item_rejects_zero_or_non_finite_quantity(client):
    register_user(client)

    zero_response = client.post(
        "/items",
        headers=csrf_headers(client),
        json={"name": "Milk", "quantity": 0},
    )
    nan_response = client.post(
        "/items",
        headers=csrf_headers(client),
        json={"name": "Milk", "quantity": "NaN"},
    )

    assert zero_response.get_json() == {"error": "quantity must be greater than 0"}
    assert nan_response.get_json() == {"error": "quantity must be greater than 0"}
