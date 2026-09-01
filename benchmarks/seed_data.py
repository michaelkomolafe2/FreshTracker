"""Seed a local FreshTracker database for repeatable API benchmarks."""

import argparse
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FLASK_API_DIR = PROJECT_ROOT / "flask-api"
sys.path.insert(0, str(FLASK_API_DIR))

from app import InventoryItem, User, build_stack_key, create_app, db  # noqa: E402


DEFAULT_EMAIL = "benchmark@example.com"
DEFAULT_PASSWORD = "Benchmark-Password-1234"
ITEM_COUNT = 1_000


def build_inventory_items(user_id, today=None):
    base_date = today or date.today()
    items = []

    for index in range(ITEM_COUNT):
        name = f"Benchmark item {index + 1:04d}"
        unit = "item"
        expiry_date = base_date + timedelta(days=index % 30)
        items.append(
            InventoryItem(
                user_id=user_id,
                name=name,
                stack_key=build_stack_key(name, unit, expiry_date),
                category=f"Benchmark category {(index % 10) + 1}",
                quantity=1.0,
                unit=unit,
                expiry_date=expiry_date,
                status="active",
                alert_sent=False,
            )
        )

    return items


def seed_database(database_url, email, password):
    app = create_app({"SQLALCHEMY_DATABASE_URI": database_url})

    with app.app_context():
        try:
            with db.session.begin():
                user = User(
                    email=email.strip().casefold(),
                    password_hash=generate_password_hash(password),
                )
                db.session.bulk_save_objects([user], return_defaults=True)
                if user.id is None:
                    raise RuntimeError("database did not return the benchmark user id")

                db.session.bulk_save_objects(build_inventory_items(user.id))
        except IntegrityError as error:
            raise RuntimeError(
                f"benchmark user {email!r} already exists; use a fresh database "
                "or pass --email"
            ) from error

    return {"email": email.strip().casefold(), "inventory_items": ITEM_COUNT}


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL"),
        help="SQLAlchemy database URL (defaults to DATABASE_URL)",
    )
    parser.add_argument("--email", default=DEFAULT_EMAIL)
    parser.add_argument(
        "--password",
        default=os.environ.get("BENCHMARK_PASSWORD", DEFAULT_PASSWORD),
    )
    args = parser.parse_args()

    if not args.database_url:
        parser.error("--database-url or DATABASE_URL is required")
    if len(args.password) < 12:
        parser.error("benchmark password must contain at least 12 characters")

    return args


def main():
    args = parse_args()
    result = seed_database(args.database_url, args.email, args.password)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
