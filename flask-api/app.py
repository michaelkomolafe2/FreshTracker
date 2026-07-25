import os
import hashlib
import hmac
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from functools import wraps
from secrets import token_urlsafe
from pathlib import Path

import joblib
from flask import Flask, current_app, g, jsonify, request
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from werkzeug.exceptions import HTTPException
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
migrate = Migrate()

MAX_STACK_QUANTITY = Decimal("10")
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
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    user = db.relationship("User", back_populates="inventory_items")
    name = db.Column(db.String(120), nullable=False)
    stack_key = db.Column(db.String(64), nullable=False)
    category = db.Column(db.String(80), nullable=True)
    quantity = db.Column(db.Float, nullable=False)
    unit = db.Column(db.String(40), nullable=False)
    expiry_date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="active")

    __table_args__ = (
        db.Index(
            "ix_inventory_items_user_stack_status",
            "user_id",
            "stack_key",
            "status",
        ),
        db.Index(
            "ix_inventory_items_user_status_expiry",
            "user_id",
            "status",
            "expiry_date",
        ),
    )

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
    inventory_items = db.relationship("InventoryItem", back_populates="user")

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


def build_stack_key(name, unit, expiry_date):
    """Create a stable value identifier for items that can share a stack."""
    parts = (name.strip().casefold(), unit.strip().casefold(), expiry_date.isoformat())
    return hashlib.sha256("\x00".join(parts).encode("utf-8")).hexdigest()


def matching_active_stacks(user_id, stack_key):
    # Row locks serialize concurrent additions to the same stack.
    return (
        InventoryItem.query.filter_by(
            user_id=user_id,
            stack_key=stack_key,
            status="active",
        )
        .order_by(InventoryItem.id.asc())
        .with_for_update()
        .all()
    )


def apply_item_stack(user_id, existing_stacks, name, category, unit, expiry_date, quantity):
    """Fill older matching stacks first, then create only necessary overflow stacks."""
    remaining = quantity
    affected_items = []

    for stack in existing_stacks:
        if remaining <= 0:
            break

        available_space = max(MAX_STACK_QUANTITY - Decimal(str(stack.quantity)), Decimal("0"))
        if available_space <= 0:
            continue

        added_quantity = min(available_space, remaining)
        stack.quantity = float(Decimal(str(stack.quantity)) + added_quantity)
        if stack.category is None and category is not None:
            stack.category = category

        affected_items.append(stack)
        remaining -= added_quantity

    while remaining > 0:
        stack_quantity = min(MAX_STACK_QUANTITY, remaining)
        item = InventoryItem(
            user_id=user_id,
            name=name,
            stack_key=build_stack_key(name, unit, expiry_date),
            category=category,
            quantity=float(stack_quantity),
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
    app.config["ALLOWED_ORIGINS"] = ALLOWED_ORIGINS

    if config:
        app.config.update(config)

    db.init_app(app)
    migrate.init_app(app, db)

    @app.errorhandler(HTTPException)
    def json_http_error(error):
        return jsonify({"error": error.description}), error.code

    @app.errorhandler(Exception)
    def json_unexpected_error(error):
        db.session.rollback()
        if current_app.testing:
            raise error
        current_app.logger.exception("Unhandled API error")
        return jsonify({"error": "internal server error"}), 500

    @app.after_request
    def add_security_headers(response):
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; "
            "base-uri 'none'; "
            "form-action 'none'; "
            "frame-ancestors 'none';"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        return response

    @app.before_request
    def load_active_session():
        session = current_session()
        g.active_session = session
        g.current_user = session.user if session is not None else None

        if request.method == "OPTIONS":
            return None

        if request.method in {"POST", "PATCH", "PUT", "DELETE"}:
            origin_error = validate_trusted_origin()
            if origin_error:
                return jsonify({"error": origin_error}), 403

        if request.path in {"/health", "/auth/register", "/auth/login", "/auth/me"}:
            return None

        if request.path.startswith("/items") and session is None:
            return jsonify({"error": "authentication required"}), 401
        if request.method in {"POST", "PATCH", "PUT", "DELETE"}:
            if session is None:
                return jsonify({"error": "authentication required"}), 401
            csrf_error = validate_csrf(session)
            if csrf_error:
                return jsonify({"error": csrf_error}), 403
        return None

    @app.after_request
    def refresh_session(response):
        session = getattr(g, "active_session", None)
        if response.status_code < 400 and session is not None and session.revoked_at is None:
            session.last_seen_at = now_utc()
            db.session.commit()
        return response

    @app.get("/health")
    def health():
        try:
            db.session.execute(text("SELECT 1"))
        except SQLAlchemyError:
            db.session.rollback()
            return jsonify({"status": "unavailable"}), 503
        return jsonify({"status": "ok"})

    @app.get("/auth/me")
    def auth_me():
        user = get_current_user()
        if user is None:
            response = jsonify(
                {
                    "authenticated": False,
                    "session_expired": bool(getattr(g, "session_expired", False)),
                    "user": None,
                }
            )
            if getattr(g, "session_expired", False):
                response.delete_cookie(SESSION_COOKIE_NAME, path="/")
                response.delete_cookie(CSRF_COOKIE_NAME, path="/")
            return response
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

        try:
            user = User(email=email, password_hash=generate_password_hash(password))
            db.session.add(user)
            db.session.flush()
            _, token, csrf_token = issue_session(user)
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            return jsonify({"error": "That email is already registered."}), 409
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
        session = getattr(g, "active_session", None)
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
        stack_key = build_stack_key(item_name, unit, expiry_date)

        # Lock the owning user as well as matching stacks. The user lock also
        # covers the empty-stack case, where there is no stack row to lock yet.
        user = User.query.filter_by(id=get_current_user().id).with_for_update().one()
        existing_stacks = matching_active_stacks(user.id, stack_key)
        affected_items = apply_item_stack(
            user.id,
            existing_stacks,
            item_name,
            category,
            unit,
            expiry_date,
            quantity,
        )
        db.session.commit()
        primary_item = affected_items[0]

        payload = {"item": primary_item.to_dict()}
        if len(affected_items) > 1:
            payload["stacked_items"] = [item.to_dict() for item in affected_items]

        return jsonify(payload), 201

    @app.get("/items")
    @require_authentication
    def list_items():
        items = (
            InventoryItem.query.filter_by(user_id=get_current_user().id, status="active")
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

        item = InventoryItem.query.filter_by(
            id=item_id,
            user_id=get_current_user().id,
        ).first()
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

    if (
        not isinstance(data["email"], str)
        or not data["email"].strip()
        or "@" not in data["email"]
        or len(data["email"].strip()) > 254
    ):
        return "email must be a valid email address"

    if not isinstance(data["password"], str) or not 12 <= len(data["password"]) <= 128:
        return "password must be between 12 and 128 characters"

    return None


def current_session():
    if hasattr(g, "active_session"):
        return g.active_session

    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        g.active_session = None
        return None

    token_hash = hash_session_token(token)
    session = Session.query.filter_by(token_hash=token_hash).first()
    if session is None or session.revoked_at is not None:
        g.active_session = None
        return None

    now = now_utc()
    if ensure_utc(session.expires_at) <= now:
        session.revoked_at = now
        db.session.commit()
        g.active_session = None
        g.session_expired = True
        return None

    if now - ensure_utc(session.last_seen_at) > timedelta(minutes=SESSION_IDLE_MINUTES):
        session.revoked_at = now
        db.session.commit()
        g.active_session = None
        g.session_expired = True
        return None

    g.active_session = session
    return session


def get_current_user():
    if hasattr(g, "current_user"):
        return g.current_user
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


def ensure_utc(value):
    """Normalize database timestamps from drivers that omit timezone metadata."""
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def validate_csrf(session):
    submitted = request.headers.get(CSRF_HEADER_NAME)
    if not submitted:
        return "missing CSRF token"

    if not hmac.compare_digest(hash_session_token(submitted), session.csrf_hash):
        return "invalid CSRF token"

    csrf_cookie = request.cookies.get(CSRF_COOKIE_NAME)
    if not csrf_cookie or not hmac.compare_digest(csrf_cookie, submitted):
        return "invalid CSRF token"

    return None


def validate_trusted_origin():
    """Reject browser writes that did not originate from an allowed frontend."""
    origin = request.headers.get("Origin")
    allowed_origins = current_app.config["ALLOWED_ORIGINS"]
    if origin:
        return None if origin in allowed_origins else "invalid origin"

    if current_app.testing:
        return None

    return (
        None
        if request.host_url.rstrip("/") in allowed_origins
        else "invalid origin"
    )


def revoke_user_sessions(user_id):
    now = now_utc()
    Session.query.filter_by(user_id=user_id, revoked_at=None).update(
        {"revoked_at": now}
    )


def set_session_cookie(response, token, csrf_token):
    configured_value = os.environ.get("SESSION_COOKIE_SECURE")
    secure_cookie = (
        configured_value.lower() == "true"
        if configured_value is not None
        else not current_app.debug and not current_app.testing
    )
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
    if len(data["name"].strip()) > 120:
        return "name must be at most 120 characters"

    if "unit" in data and data["unit"] is not None:
        if not isinstance(data["unit"], str) or not data["unit"].strip():
            return "unit must be a non-empty string"
        if len(data["unit"].strip()) > 40:
            return "unit must be at most 40 characters"

    if "category" in data and data["category"] is not None:
        if not isinstance(data["category"], str):
            return "category must be a string or null"
        if len(data["category"].strip()) > 80:
            return "category must be at most 80 characters"

    if "quantity" in data and data["quantity"] is not None:
        try:
            quantity = Decimal(str(data["quantity"]))
        except (InvalidOperation, TypeError, ValueError):
            return "quantity must be a number"

        if not quantity.is_finite() or quantity <= 0:
            return "quantity must be greater than 0"

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
        return Decimal("1")

    return Decimal(str(value))


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


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
