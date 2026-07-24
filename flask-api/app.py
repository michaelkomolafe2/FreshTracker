import os
from datetime import date
from pathlib import Path

import joblib
from flask import Flask, jsonify, request
from flask_sqlalchemy import SQLAlchemy


MODEL_PATH = Path(
    os.environ.get(
        "MODEL_PATH",
        Path(__file__).resolve().parent / "ml-brain" / "model.pkl",
    )
)
if not MODEL_PATH.exists():
    MODEL_PATH = Path(__file__).resolve().parent.parent / "ml-brain" / "model.pkl"

category_model = joblib.load(MODEL_PATH)

db = SQLAlchemy()

MAX_STACK_QUANTITY = 10.0


class InventoryItem(db.Model):
    __tablename__ = "inventory_items"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    category = db.Column(db.String(80), nullable=True)
    quantity = db.Column(db.Float, nullable=False)
    unit = db.Column(db.String(40), nullable=False)
    expiry_date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="active")

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "quantity": self.quantity,
            "unit": self.unit,
            "expiry_date": self.expiry_date.isoformat(),
            "status": self.status,
        }


def normalized_stack_key(name, unit, expiry_date):
    return (
        name.strip().casefold(),
        unit.strip().casefold(),
        expiry_date.isoformat(),
    )


def matching_active_stacks(name, unit, expiry_date):
    target_key = normalized_stack_key(name, unit, expiry_date)
    return [
        item
        for item in InventoryItem.query.filter_by(
            status="active",
            expiry_date=expiry_date,
        )
        .order_by(InventoryItem.id.asc())
        .all()
        if normalized_stack_key(item.name, item.unit, item.expiry_date) == target_key
    ]


def apply_item_stack(existing_stacks, name, category, unit, expiry_date, quantity):
    remaining = float(quantity)
    affected_items = []

    for stack in existing_stacks:
        if remaining <= 0:
            break

        available_space = max(MAX_STACK_QUANTITY - stack.quantity, 0)
        if available_space <= 0:
            continue

        added_quantity = min(available_space, remaining)
        stack.quantity += added_quantity
        if stack.category is None and category is not None:
            stack.category = category

        affected_items.append(stack)
        remaining -= added_quantity

    while remaining > 0:
        stack_quantity = min(MAX_STACK_QUANTITY, remaining)
        item = InventoryItem(
            name=name,
            category=category,
            quantity=stack_quantity,
            unit=unit,
            expiry_date=expiry_date,
        )
        db.session.add(item)
        affected_items.append(item)
        remaining -= stack_quantity

    return affected_items


def create_app(config=None):
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
        "DATABASE_URL",
        "postgresql://freshtracker:freshtracker@db:5432/freshtracker",
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    if config:
        app.config.update(config)

    db.init_app(app)

    @app.get("/health")
    def health():
        return jsonify({"status": "ok"})

    @app.post("/items")
    def create_item():
        data = request.get_json(silent=True) or {}
        error = validate_item_payload(data)
        if error:
            return jsonify({"error": error}), 400

        item_name = data["name"].strip()
        category = clean_optional_string(data.get("category"))
        if category is None:
            category = predict_category(item_name)
        unit = clean_optional_string(data.get("unit")) or "item"
        expiry_date = parse_expiry_date(data.get("expiry_date"))
        quantity = parse_quantity(data.get("quantity"))

        existing_stacks = matching_active_stacks(item_name, unit, expiry_date)
        if existing_stacks or quantity > 0:
            affected_items = apply_item_stack(
                existing_stacks,
                item_name,
                category,
                unit,
                expiry_date,
                quantity,
            )
            db.session.commit()
            primary_item = affected_items[0] if affected_items else existing_stacks[0]
        else:
            primary_item = InventoryItem(
                name=item_name,
                category=category,
                quantity=quantity,
                unit=unit,
                expiry_date=expiry_date,
            )
            db.session.add(primary_item)
            db.session.commit()
            affected_items = [primary_item]

        payload = {"item": primary_item.to_dict()}
        if len(affected_items) > 1:
            payload["stacked_items"] = [item.to_dict() for item in affected_items]

        return jsonify(payload), 201

    @app.get("/items")
    def list_items():
        items = (
            InventoryItem.query.filter_by(status="active")
            .order_by(InventoryItem.expiry_date.asc(), InventoryItem.id.asc())
            .all()
        )

        return jsonify({"items": [item.to_dict() for item in items]})

    @app.patch("/items/<int:item_id>")
    def update_item_status(item_id):
        data = request.get_json(silent=True) or {}
        status = data.get("status")

        if status not in {"used", "wasted"}:
            return jsonify({"error": "status must be either 'used' or 'wasted'"}), 400

        item = db.session.get(InventoryItem, item_id)
        if item is None:
            return jsonify({"error": "item not found"}), 404

        item.status = status
        db.session.commit()

        return jsonify({"item": item.to_dict()})

    return app


def validate_item_payload(data):
    required_fields = ["name"]
    missing_fields = [field for field in required_fields if field not in data]
    if missing_fields:
        return f"missing required field(s): {', '.join(missing_fields)}"

    if not isinstance(data["name"], str) or not data["name"].strip():
        return "name must be a non-empty string"

    if "unit" in data and data["unit"] is not None:
        if not isinstance(data["unit"], str) or not data["unit"].strip():
            return "unit must be a non-empty string"

    if "category" in data and data["category"] is not None:
        if not isinstance(data["category"], str):
            return "category must be a string or null"

    if "quantity" in data and data["quantity"] is not None:
        try:
            quantity = float(data["quantity"])
        except (TypeError, ValueError):
            return "quantity must be a number"

        if quantity < 0:
            return "quantity must be greater than or equal to 0"

    if "expiry_date" in data and data["expiry_date"] is not None:
        if not isinstance(data["expiry_date"], str):
            return "expiry_date must be an ISO date string"

        try:
            date.fromisoformat(data["expiry_date"])
        except ValueError:
            return "expiry_date must be an ISO date string"

    return None


def parse_quantity(value):
    if value is None:
        return 1.0

    return float(value)


def parse_expiry_date(value):
    if value is None:
        return date.today()

    return date.fromisoformat(value)


def clean_optional_string(value):
    if value is None:
        return None

    cleaned = value.strip()
    return cleaned or None


def predict_category(item_name):
    return category_model.predict([item_name])[0]


def initialize_database(app):
    with app.app_context():
        db.create_all()


app = create_app()


if __name__ == "__main__":
    initialize_database(app)
    app.run(host="0.0.0.0", port=5000)
