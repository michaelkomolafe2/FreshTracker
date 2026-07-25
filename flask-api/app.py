import os
import hashlib
from datetime import datetime, timedelta, timezone
from datetime import date
from functools import wraps
from secrets import token_urlsafe
from pathlib import Path

import joblib
from flask import Flask, current_app, g, jsonify, request
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash


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
SESSION_COOKIE_NAME = "freshtracker_session"
CSRF_COOKIE_NAME = "freshtracker_csrf"
CSRF_HEADER_NAME = "X-CSRF-Token"
SESSION_IDLE_MINUTES = 30
SESSION_ABSOLUTE_HOURS = 24
ALLOWED_ORIGINS = {
    origin.strip()
    for origin in os.environ.get(
        "ALLOWED_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    ).split(",")
    if origin.strip()
}


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


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(254), nullable=False, unique=True, index=True)
    password_hash = db.Column(db.String(255), nullable=False)

    def to_dict(self):
        return {
            "id": self.id,
            "email": self.email,
        }


class Session(db.Model):
    __tablename__ = "sessions"

    id = db.Column(db.Integer, primary_key=True)
    token_hash = db.Column(db.String(255), nullable=False, unique=True, index=True)
    csrf_hash = db.Column(db.String(255), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    user = db.relationship("User")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False)
    last_seen_at = db.Column(db.DateTime(timezone=True), nullable=False)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)
    revoked_at = db.Column(db.DateTime(timezone=True), nullable=True)
    rotated_from_id = db.Column(db.Integer, db.ForeignKey("sessions.id"), nullable=True)
    rotated_from = db.relationship("Session", remote_side=[id], uselist=False)

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "expires_at": self.expires_at.isoformat(),
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

    @app.after_request
    def add_security_headers(response):
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "base-uri 'self'; "
            "connect-src 'self' http://localhost:5000 http://127.0.0.1:5000; "
            "img-src 'self' data:; "
            "font-src 'self' https://fonts.gstatic.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "script-src 'self'; "
            "form-action 'self'; "
            "frame-ancestors 'none';"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        return response

    @app.before_request
    def load_active_session():
        if request.method == "OPTIONS":
            return None
        if request.path in {
            "/health",
            "/auth/register",
            "/auth/login",
            "/auth/me",
        }:
            return None
        session = current_session()
        g.active_session = session
        g.current_user = session.user if session is not None else None
        if request.path.startswith("/items") and session is None:
            return jsonify({"error": "authentication required"}), 401
        if request.method in {"POST", "PATCH", "PUT", "DELETE"} and request.path.startswith("/auth/") is False:
            if session is None:
                return jsonify({"error": "authentication required"}), 401
            csrf_error = validate_csrf(session)
            if csrf_error:
                return jsonify({"error": csrf_error}), 403
        return None

    @app.after_request
    def refresh_session(response):
        session = current_session()
        if session is not None and session.revoked_at is None:
            session.last_seen_at = now_utc()
            db.session.commit()
        return response

    @app.get("/health")
    def health():
        return jsonify({"status": "ok"})

    @app.get("/auth/me")
    def auth_me():
        user = get_current_user()
        if user is None:
            return jsonify({"authenticated": False, "user": None})
        return jsonify({"authenticated": True, "user": user.to_dict()})

    @app.post("/auth/register")
    def auth_register():
        data = request.get_json(silent=True) or {}
        error = validate_auth_payload(data)
        if error:
            return jsonify({"error": error}), 400

        email = normalize_email(data["email"])
        password = data["password"]

        if User.query.filter_by(email=email).first() is not None:
            return jsonify({"error": "That email is already registered."}), 409

        user = User(email=email, password_hash=generate_password_hash(password))
        db.session.add(user)
        db.session.flush()
        session, token, csrf_token = issue_session(user)
        db.session.commit()
        response = jsonify({"user": user.to_dict()})
        set_session_cookie(response, token, csrf_token)
        return response, 201

    @app.post("/auth/login")
    def auth_login():
        data = request.get_json(silent=True) or {}
        error = validate_auth_payload(data)
        if error:
            return jsonify({"error": error}), 400

        email = normalize_email(data["email"])
        password = data["password"]
        user = User.query.filter_by(email=email).first()
        if user is None or not check_password_hash(user.password_hash, password):
            return jsonify({"error": "Invalid email or password."}), 401

        revoke_user_sessions(user.id)
        session, token, csrf_token = issue_session(user)
        db.session.commit()
        response = jsonify({"user": user.to_dict()})
        set_session_cookie(response, token, csrf_token)
        return response

    @app.post("/auth/logout")
    def auth_logout():
        session = current_session()
        if session is not None:
            session.revoked_at = now_utc()
            db.session.commit()

        response = jsonify({"ok": True})
        response.delete_cookie(SESSION_COOKIE_NAME, path="/")
        response.delete_cookie(CSRF_COOKIE_NAME, path="/")
        return response

    @app.post("/items")
    @require_authentication
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
    @require_authentication
    def list_items():
        items = (
            InventoryItem.query.filter_by(status="active")
            .order_by(InventoryItem.expiry_date.asc(), InventoryItem.id.asc())
            .all()
        )

        return jsonify({"items": [item.to_dict() for item in items]})

    @app.patch("/items/<int:item_id>")
    @require_authentication
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


def normalize_email(email):
    return email.strip().casefold()


def validate_auth_payload(data):
    if "email" not in data or "password" not in data:
        return "missing required field(s): email, password"

    if not isinstance(data["email"], str) or not data["email"].strip():
        return "email must be a non-empty string"

    if not isinstance(data["password"], str) or len(data["password"]) < 8:
        return "password must be at least 8 characters"

    return None


def current_session():
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        return None

    token_hash = hash_session_token(token)
    session = Session.query.filter_by(token_hash=token_hash).first()
    if session is None or session.revoked_at is not None:
        return None

    now = now_utc()
    if session.expires_at <= now:
        session.revoked_at = now
        db.session.commit()
        return None

    if now - session.last_seen_at > timedelta(minutes=SESSION_IDLE_MINUTES):
        session.revoked_at = now
        db.session.commit()
        return None

    return session


def get_current_user():
    session = current_session()
    return session.user if session is not None else None


def require_authentication(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = get_current_user()
        if user is None:
            return jsonify({"error": "authentication required"}), 401
        return view(*args, **kwargs)

    return wrapped


def issue_session(user):
    token = token_urlsafe(32)
    csrf_token = token_urlsafe(24)
    session = Session(
        token_hash=hash_session_token(token),
        csrf_hash=hash_session_token(csrf_token),
        user=user,
        created_at=now_utc(),
        last_seen_at=now_utc(),
        expires_at=now_utc() + timedelta(hours=SESSION_ABSOLUTE_HOURS),
    )
    db.session.add(session)
    db.session.flush()
    return session, token, csrf_token


def hash_session_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def now_utc():
    return datetime.now(timezone.utc)


def validate_csrf(session):
    origin = request.headers.get("Origin")
    if origin and origin not in ALLOWED_ORIGINS:
        return "invalid origin"
    if (
        not origin
        and not current_app.testing
        and request.host
        and request.host_url.rstrip("/") not in ALLOWED_ORIGINS
    ):
        return "invalid origin"

    submitted = request.headers.get(CSRF_HEADER_NAME)
    if not submitted:
        return "missing CSRF token"

    if hash_session_token(submitted) != session.csrf_hash:
        return "invalid CSRF token"

    csrf_cookie = request.cookies.get(CSRF_COOKIE_NAME)
    if not csrf_cookie or csrf_cookie != submitted:
        return "invalid CSRF token"

    return None


def revoke_user_sessions(user_id):
    now = now_utc()
    Session.query.filter_by(user_id=user_id, revoked_at=None).update(
        {"revoked_at": now}
    )


def set_session_cookie(response, token, csrf_token):
    secure_cookie = os.environ.get("SESSION_COOKIE_SECURE", "false").lower() == "true"
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        httponly=True,
        samesite="Lax",
        secure=secure_cookie,
        path="/",
        max_age=60 * 60 * 24,
    )
    response.set_cookie(
        CSRF_COOKIE_NAME,
        csrf_token,
        httponly=False,
        samesite="Lax",
        secure=secure_cookie,
        path="/",
        max_age=60 * 60 * 24,
    )
    return response


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
