import copy
import hashlib
import hmac
import json
import logging
import os
import unicodedata
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from functools import wraps
from pathlib import Path
from secrets import token_urlsafe
from threading import RLock
from zoneinfo import ZoneInfo

import click
import joblib
import requests
from apscheduler.schedulers.blocking import BlockingScheduler
from cachetools import TTLCache
from flask import Flask, current_app, g, jsonify, request
from flask_mail import Mail, Message
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import select, text, update
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
mail = Mail()

MAX_STACK_QUANTITY = Decimal("10")
SESSION_COOKIE_NAME = "freshtracker_session"
CSRF_COOKIE_NAME = "freshtracker_csrf"
CSRF_HEADER_NAME = "X-CSRF-Token"
SESSION_IDLE_MINUTES = 30
SESSION_ABSOLUTE_HOURS = 24
MAX_RECIPE_INGREDIENTS = 25
MAX_RECIPE_INGREDIENT_LENGTH = 120
RECIPE_RESULT_LIMIT = 10
RECIPE_CACHE_MAX_SIZE = 256
RECIPE_CACHE_TTL_SECONDS = 6 * 60 * 60
RECIPE_STALE_TTL_SECONDS = 24 * 60 * 60
SPOONACULAR_RECIPES_URL = (
    "https://api.spoonacular.com/recipes/findByIngredients"
)
ALLOWED_ORIGINS = {
    origin.strip()
    for origin in os.environ.get(
        "ALLOWED_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    ).split(",")
    if origin.strip()
}


class RecipeProviderError(Exception):
    def __init__(self, message, status_code):
        super().__init__(message)
        self.status_code = status_code


class RecipeSuggestionCache:
    def __init__(self):
        # Six hours preserves quota because a fixed ingredient set is unlikely
        # to produce meaningfully different recipes within the same day.
        self.fresh = TTLCache(
            maxsize=RECIPE_CACHE_MAX_SIZE,
            ttl=RECIPE_CACHE_TTL_SECONDS,
        )
        self.stale = TTLCache(
            maxsize=RECIPE_CACHE_MAX_SIZE,
            ttl=RECIPE_STALE_TTL_SECONDS,
        )
        self.lock = RLock()

    def get_fresh(self, key):
        with self.lock:
            value = self.fresh.get(key)
            return copy.deepcopy(value) if value is not None else None

    def get_stale(self, key):
        with self.lock:
            value = self.stale.get(key)
            return copy.deepcopy(value) if value is not None else None

    def store(self, key, value):
        with self.lock:
            self.fresh[key] = copy.deepcopy(value)
            self.stale[key] = copy.deepcopy(value)


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
    alert_sent = db.Column(
        db.Boolean,
        nullable=False,
        default=False,
        server_default=db.false(),
    )
    waste_logs = db.relationship("WasteLog", back_populates="item")

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
        db.Index(
            "ix_inventory_items_expiry_alert_candidates",
            "expiry_date",
            postgresql_where=db.and_(
                alert_sent.is_(False),
                status == "active",
            ),
            sqlite_where=db.and_(
                alert_sent.is_(False),
                status == "active",
            ),
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
    waste_logs = db.relationship("WasteLog", back_populates="user")

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


class WasteLog(db.Model):
    __tablename__ = "waste_logs"

    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(
        db.Integer,
        db.ForeignKey("inventory_items.id"),
        nullable=False,
    )
    item = db.relationship("InventoryItem", back_populates="waste_logs")
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    user = db.relationship("User", back_populates="waste_logs")
    action = db.Column(
        db.Enum(
            "used",
            "wasted",
            name="waste_action",
            create_constraint=True,
            validate_strings=True,
        ),
        nullable=False,
    )
    category = db.Column(db.String(80), nullable=True)
    logged_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        server_default=db.func.now(),
    )

    __table_args__ = (
        db.Index("ix_waste_logs_user_logged_at", "user_id", "logged_at"),
    )


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
    provided_config = config or {}
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
        "DATABASE_URL",
        "sqlite:///freshtracker.db",
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["ALLOWED_ORIGINS"] = ALLOWED_ORIGINS
    app.config["MAIL_ENABLED"] = env_flag("MAIL_ENABLED", default=False)
    app.config["MAIL_SERVER"] = os.environ.get("MAIL_SERVER", "")
    app.config["MAIL_PORT"] = int(os.environ.get("MAIL_PORT", "587"))
    app.config["MAIL_USE_TLS"] = env_flag("MAIL_USE_TLS", default=True)
    app.config["MAIL_USE_SSL"] = env_flag("MAIL_USE_SSL", default=False)
    app.config["MAIL_USERNAME"] = os.environ.get("MAIL_USERNAME")
    app.config["MAIL_PASSWORD"] = os.environ.get("MAIL_PASSWORD")
    app.config["MAIL_DEFAULT_SENDER"] = os.environ.get("MAIL_DEFAULT_SENDER")
    app.config["MAIL_SUPPRESS_SEND"] = not app.config["MAIL_ENABLED"]
    app.config["EXPIRY_ALERT_TIMEZONE"] = os.environ.get(
        "EXPIRY_ALERT_TIMEZONE",
        "UTC",
    )
    app.config["EXPIRY_ALERT_HOUR"] = int(
        os.environ.get("EXPIRY_ALERT_HOUR", "7")
    )
    app.config["EXPIRY_ALERT_MINUTE"] = int(
        os.environ.get("EXPIRY_ALERT_MINUTE", "0")
    )
    app.config["SPOONACULAR_API_KEY"] = os.environ.get(
        "SPOONACULAR_API_KEY",
        "",
    )
    app.config["SPOONACULAR_TIMEOUT_SECONDS"] = float(
        os.environ.get("SPOONACULAR_TIMEOUT_SECONDS", "8")
    )

    app.config.update(provided_config)
    if "MAIL_SUPPRESS_SEND" not in provided_config:
        app.config["MAIL_SUPPRESS_SEND"] = not app.config["MAIL_ENABLED"]
    if (
        app.config["MAIL_SUPPRESS_SEND"]
        and not app.config["MAIL_DEFAULT_SENDER"]
    ):
        app.config["MAIL_DEFAULT_SENDER"] = (
            "FreshTracker <no-reply@freshtracker.local>"
        )

    validate_mail_config(app.config)
    validate_expiry_alert_config(app.config)
    validate_spoonacular_config(app.config)

    db.init_app(app)
    migrate.init_app(app, db)
    mail.init_app(app)
    app.extensions["recipe_suggestion_cache"] = RecipeSuggestionCache()
    app.cli.add_command(run_expiry_alert_scheduler)
    app.cli.add_command(send_expiry_alerts_once)

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

    @app.get("/waste-logs/category-summary")
    @require_authentication
    def waste_log_category_summary():
        rows = (
            db.session.query(
                WasteLog.category,
                WasteLog.action,
                db.func.count(WasteLog.id).label("count"),
            )
            .filter(WasteLog.user_id == get_current_user().id)
            .group_by(WasteLog.category, WasteLog.action)
            .order_by(WasteLog.category.asc(), WasteLog.action.asc())
            .all()
        )

        categories = {}
        for category, action, count in rows:
            summary = categories.setdefault(
                category,
                {
                    "category": category,
                    "used": 0,
                    "wasted": 0,
                },
            )
            summary[action] = count

        return jsonify({"categories": list(categories.values())})

    @app.post("/recipe-suggestions")
    @require_authentication
    def recipe_suggestions():
        data = request.get_json(silent=True)
        normalized_ingredients, error = normalize_recipe_ingredients(data)
        if error:
            return jsonify({"error": error}), 400

        cache_key = recipe_ingredients_cache_key(normalized_ingredients)
        cache = current_app.extensions["recipe_suggestion_cache"]
        cached_recipes = cache.get_fresh(cache_key)
        if cached_recipes is not None:
            return recipe_suggestion_response(
                normalized_ingredients,
                cached_recipes,
                source="cache",
            )

        try:
            recipes = fetch_recipe_suggestions(normalized_ingredients)
        except RecipeProviderError as error:
            stale_recipes = cache.get_stale(cache_key)
            if stale_recipes is not None:
                current_app.logger.warning(
                    "Serving stale recipe suggestions after provider failure"
                )
                return recipe_suggestion_response(
                    normalized_ingredients,
                    stale_recipes,
                    source="stale-cache",
                )
            return jsonify({"error": str(error)}), error.status_code

        cache.store(cache_key, recipes)
        return recipe_suggestion_response(
            normalized_ingredients,
            recipes,
            source="spoonacular",
        )

    @app.patch("/items/<int:item_id>")
    @require_authentication
    def update_item_status(item_id):
        data = request.get_json(silent=True) or {}
        status = data.get("status")

        if status not in {"used", "wasted"}:
            return jsonify({"error": "status must be either 'used' or 'wasted'"}), 400

        user_id = get_current_user().id

        # Session authentication performs a read before the view and SQLAlchemy
        # autobegins for it. End that read-only unit so this view owns the full
        # status-and-log write transaction explicitly.
        db.session.rollback()
        with db.session.begin():
            item = (
                InventoryItem.query.filter_by(
                    id=item_id,
                    user_id=user_id,
                )
                .with_for_update()
                .first()
            )
            if item is None:
                return jsonify({"error": "item not found"}), 404
            if item.status != "active":
                return jsonify({"error": "item is no longer active"}), 409

            item.status = status
            db.session.flush()
            db.session.add(
                WasteLog(
                    item_id=item.id,
                    user_id=user_id,
                    action=status,
                    category=item.category,
                )
            )
            db.session.flush()
            item_payload = item.to_dict()

        return jsonify({"item": item_payload})

    return app


def normalize_email(email):
    return email.strip().casefold()


def normalize_recipe_ingredients(data):
    if not isinstance(data, dict) or "ingredients" not in data:
        return None, "missing required field(s): ingredients"

    ingredients = data["ingredients"]
    if not isinstance(ingredients, list):
        return None, "ingredients must be a list"
    if not ingredients:
        return None, "ingredients must contain at least one item"
    if len(ingredients) > MAX_RECIPE_INGREDIENTS:
        return (
            None,
            f"ingredients must contain at most {MAX_RECIPE_INGREDIENTS} items",
        )

    normalized = set()
    for ingredient in ingredients:
        if not isinstance(ingredient, str) or not ingredient.strip():
            return None, "each ingredient must be a non-empty string"

        value = unicodedata.normalize(
            "NFKC",
            " ".join(ingredient.split()),
        ).casefold()
        if len(value) > MAX_RECIPE_INGREDIENT_LENGTH:
            return (
                None,
                "each ingredient must be at most "
                f"{MAX_RECIPE_INGREDIENT_LENGTH} characters",
            )
        if "," in value:
            return None, "ingredients must not contain commas"
        normalized.add(value)

    return tuple(sorted(normalized)), None


def recipe_ingredients_cache_key(ingredients):
    canonical_value = "\x00".join(ingredients).encode("utf-8")
    return hashlib.sha256(canonical_value).hexdigest()


def fetch_recipe_suggestions(ingredients):
    api_key = current_app.config.get("SPOONACULAR_API_KEY")
    if not api_key:
        raise RecipeProviderError(
            "recipe suggestions are not configured",
            503,
        )

    try:
        response = requests.get(
            SPOONACULAR_RECIPES_URL,
            headers={"x-api-key": api_key},
            params={
                "ingredients": ",".join(ingredients),
                "number": RECIPE_RESULT_LIMIT,
                "ranking": 1,
                "ignorePantry": "true",
            },
            timeout=current_app.config["SPOONACULAR_TIMEOUT_SECONDS"],
        )
    except requests.Timeout as error:
        current_app.logger.warning("Spoonacular request timed out")
        raise RecipeProviderError(
            "recipe provider temporarily unavailable",
            503,
        ) from error
    except requests.RequestException as error:
        current_app.logger.warning(
            "Spoonacular request failed: %s",
            type(error).__name__,
        )
        raise RecipeProviderError(
            "recipe provider temporarily unavailable",
            503,
        ) from error

    if response.status_code in {402, 429}:
        current_app.logger.warning(
            "Spoonacular quota or rate limit reached: status=%s",
            response.status_code,
        )
        raise RecipeProviderError(
            "recipe provider rate limit reached",
            503,
        )
    if not response.ok:
        current_app.logger.warning(
            "Spoonacular returned an error: status=%s",
            response.status_code,
        )
        raise RecipeProviderError(
            "recipe provider temporarily unavailable",
            502,
        )

    try:
        recipes = response.json()
    except ValueError as error:
        raise RecipeProviderError(
            "recipe provider returned an invalid response",
            502,
        ) from error

    if not isinstance(recipes, list):
        raise RecipeProviderError(
            "recipe provider returned an invalid response",
            502,
        )

    return recipes


def recipe_suggestion_response(ingredients, recipes, source):
    return jsonify(
        {
            "ingredients": list(ingredients),
            "recipes": recipes,
            "source": source,
        }
    )


def env_flag(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().casefold() in {"1", "true", "yes", "on"}


def validate_mail_config(config):
    if config["MAIL_USE_TLS"] and config["MAIL_USE_SSL"]:
        raise ValueError("MAIL_USE_TLS and MAIL_USE_SSL cannot both be enabled")

    if config["MAIL_ENABLED"]:
        missing = [
            name
            for name in ("MAIL_SERVER", "MAIL_DEFAULT_SENDER")
            if not config.get(name)
        ]
        if missing:
            raise ValueError(
                f"MAIL_ENABLED requires: {', '.join(missing)}"
            )


def validate_expiry_alert_config(config):
    ZoneInfo(config["EXPIRY_ALERT_TIMEZONE"])
    if not 0 <= config["EXPIRY_ALERT_HOUR"] <= 23:
        raise ValueError("EXPIRY_ALERT_HOUR must be between 0 and 23")
    if not 0 <= config["EXPIRY_ALERT_MINUTE"] <= 59:
        raise ValueError("EXPIRY_ALERT_MINUTE must be between 0 and 59")


def validate_spoonacular_config(config):
    if config["SPOONACULAR_TIMEOUT_SECONDS"] <= 0:
        raise ValueError("SPOONACULAR_TIMEOUT_SECONDS must be greater than 0")


def alert_calendar_date():
    return datetime.now(
        ZoneInfo(current_app.config["EXPIRY_ALERT_TIMEZONE"])
    ).date()


def claim_expiring_inventory_items(cutoff_date):
    columns = expiry_alert_columns()
    statement = (
        update(InventoryItem)
        .where(*expiry_alert_predicates(cutoff_date))
        .values(alert_sent=True)
        .returning(*columns)
    )
    claimed_items = [
        dict(item)
        for item in db.session.execute(statement).mappings().all()
    ]
    db.session.commit()
    return claimed_items


def preview_expiring_inventory_items(cutoff_date):
    statement = (
        select(*expiry_alert_columns())
        .where(*expiry_alert_predicates(cutoff_date))
        .order_by(InventoryItem.expiry_date, InventoryItem.id)
    )
    return [
        dict(item)
        for item in db.session.execute(statement).mappings().all()
    ]


def expiry_alert_columns():
    return (
        InventoryItem.id,
        InventoryItem.user_id,
        InventoryItem.name,
        InventoryItem.quantity,
        InventoryItem.unit,
        InventoryItem.expiry_date,
    )


def expiry_alert_predicates(cutoff_date):
    return (
        InventoryItem.expiry_date <= cutoff_date,
        InventoryItem.status == "active",
        InventoryItem.alert_sent.is_(False),
    )


def expiry_alert_message(item, recipient):
    return Message(
        subject=f"FreshTracker: {item['name']} expires soon",
        recipients=[recipient],
        body=(
            f"{item['name']} ({item['quantity']:g} {item['unit']}) expires on "
            f"{item['expiry_date'].isoformat()}.\n\n"
            "Open FreshTracker to use it before it goes to waste."
        ),
    )


def send_expiry_alerts(today=None):
    cutoff_date = (today or alert_calendar_date()) + timedelta(days=3)
    if not current_app.config["MAIL_ENABLED"]:
        preview_items = preview_expiring_inventory_items(cutoff_date)
        for item in preview_items:
            current_app.logger.info(
                "Dry-run expiry alert: item_id=%s user_id=%s expiry_date=%s",
                item["id"],
                item["user_id"],
                item["expiry_date"].isoformat(),
            )
        result = {
            "claimed": 0,
            "sent": 0,
            "failed": 0,
            "previewed": len(preview_items),
        }
        current_app.logger.info("Expiry alert dry run completed: %s", result)
        return result

    claimed_items = claim_expiring_inventory_items(cutoff_date)
    if not claimed_items:
        current_app.logger.info(
            "Expiry alert job completed: no eligible inventory items"
        )
        return {"claimed": 0, "sent": 0, "failed": 0}

    user_ids = {item["user_id"] for item in claimed_items}
    recipients = {
        user.id: user.email
        for user in User.query.filter(User.id.in_(user_ids)).all()
    }
    sent_count = 0
    failed_count = 0

    for item in claimed_items:
        recipient = recipients.get(item["user_id"])
        if recipient is None:
            failed_count += 1
            current_app.logger.error(
                "Cannot send expiry alert for item_id=%s: user not found",
                item["id"],
            )
            continue
        try:
            mail.send(expiry_alert_message(item, recipient))
            sent_count += 1
        except Exception:
            failed_count += 1
            current_app.logger.exception(
                "Failed to send expiry alert for item_id=%s",
                item["id"],
            )

    result = {
        "claimed": len(claimed_items),
        "sent": sent_count,
        "failed": failed_count,
    }
    current_app.logger.info("Expiry alert job completed: %s", result)
    return result


def execute_expiry_alert_job(app):
    with app.app_context():
        send_expiry_alerts()


@click.command("run-expiry-alert-scheduler")
def run_expiry_alert_scheduler():
    app = current_app._get_current_object()
    app.logger.setLevel(logging.INFO)
    scheduler = BlockingScheduler(
        timezone=app.config["EXPIRY_ALERT_TIMEZONE"]
    )
    scheduler.add_job(
        execute_expiry_alert_job,
        trigger="cron",
        args=[app],
        hour=app.config["EXPIRY_ALERT_HOUR"],
        minute=app.config["EXPIRY_ALERT_MINUTE"],
        id="nightly-expiry-alerts",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=60 * 60,
        next_run_time=datetime.now(
            ZoneInfo(app.config["EXPIRY_ALERT_TIMEZONE"])
        ),
    )
    app.logger.info(
        "Starting expiry alert scheduler for %02d:%02d %s",
        app.config["EXPIRY_ALERT_HOUR"],
        app.config["EXPIRY_ALERT_MINUTE"],
        app.config["EXPIRY_ALERT_TIMEZONE"],
    )
    scheduler.start()


@click.command("send-expiry-alerts")
def send_expiry_alerts_once():
    click.echo(json.dumps(send_expiry_alerts(), sort_keys=True))


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
