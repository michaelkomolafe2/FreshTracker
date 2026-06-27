import os
from datetime import date

from flask import Flask, jsonify, request
from flask_sqlalchemy import SQLAlchemy


db = SQLAlchemy()


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

        item = InventoryItem(
            name=data["name"].strip(),
            category=clean_optional_string(data.get("category")),
            quantity=float(data["quantity"]),
            unit=data["unit"].strip(),
            expiry_date=date.fromisoformat(data["expiry_date"]),
        )

        db.session.add(item)
        db.session.commit()

        return jsonify({"item": item.to_dict()}), 201

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
    required_fields = ["name", "quantity", "unit", "expiry_date"]
    missing_fields = [field for field in required_fields if field not in data]
    if missing_fields:
        return f"missing required field(s): {', '.join(missing_fields)}"

    if not isinstance(data["name"], str) or not data["name"].strip():
        return "name must be a non-empty string"

    if not isinstance(data["unit"], str) or not data["unit"].strip():
        return "unit must be a non-empty string"

    if "category" in data and data["category"] is not None:
        if not isinstance(data["category"], str):
            return "category must be a string or null"

    try:
        quantity = float(data["quantity"])
    except (TypeError, ValueError):
        return "quantity must be a number"

    if quantity < 0:
        return "quantity must be greater than or equal to 0"

    if not isinstance(data["expiry_date"], str):
        return "expiry_date must be an ISO date string"

    try:
        date.fromisoformat(data["expiry_date"])
    except ValueError:
        return "expiry_date must be an ISO date string"

    return None


def clean_optional_string(value):
    if value is None:
        return None

    cleaned = value.strip()
    return cleaned or None


def initialize_database(app):
    with app.app_context():
        db.create_all()


app = create_app()


if __name__ == "__main__":
    initialize_database(app)
    app.run(host="0.0.0.0", port=5000)
