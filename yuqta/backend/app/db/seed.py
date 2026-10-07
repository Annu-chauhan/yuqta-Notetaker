"""Load data/seed.sql into the database.

    python -m app.db.seed             # (re)load business data from SEED_SQL_PATH
    python -m app.db.seed --if-empty  # load only if no customers exist yet (used on startup)
    python -m app.db.seed --clear     # delete all business data (customers, revenue, orders, renewals)

On startup (--if-empty) nothing is loaded when DEMO_BUSINESS_DATA=false, so meetings are analyzed
on their own until real business data is loaded. Meetings are never touched.
"""

import argparse
import logging
from pathlib import Path

from sqlalchemy import Engine, func, select, text

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.models import Customer
from app.db.session import get_engine


logger = logging.getLogger(__name__)


def seed_path() -> Path:
    path = Path(get_settings().seed_sql_path)
    if not path.is_file():
        raise FileNotFoundError(f"Seed file not found: {path}. Set SEED_SQL_PATH.")
    return path


def is_seeded(engine: Engine) -> bool:
    with engine.connect() as connection:
        return connection.execute(select(func.count()).select_from(Customer)).scalar_one() > 0


def load_seed(engine: Engine, path: Path) -> None:
    sql = path.read_text(encoding="utf-8")
    # Raw DB-API cursor: psycopg runs a multi-statement script when no parameters are passed.
    raw = engine.raw_connection()
    try:
        with raw.cursor() as cursor:
            cursor.execute(sql)
        raw.commit()
    except Exception:
        raw.rollback()
        raise
    finally:
        raw.close()


def clear(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE TABLE renewals, revenue, orders, customers RESTART IDENTITY CASCADE"))


def run(if_empty: bool = False) -> bool:
    """Returns True if seed data was loaded."""
    if if_empty and not get_settings().demo_business_data:
        logger.info("Seed skipped: DEMO_BUSINESS_DATA=false")
        return False
    engine = get_engine()
    if if_empty and is_seeded(engine):
        logger.info("Seed skipped: business data already present")
        return False
    path = seed_path()
    load_seed(engine, path)
    logger.info("Seed loaded from %s", path)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--if-empty", action="store_true", help="only seed when no customers exist")
    parser.add_argument("--clear", action="store_true", help="delete all business data and load nothing")
    args = parser.parse_args()
    configure_logging(get_settings().log_level)
    if args.clear:
        clear(get_engine())
        logger.info("Business data cleared; meetings are now analyzed on their own")
        return
    run(if_empty=args.if_empty)


if __name__ == "__main__":
    main()
