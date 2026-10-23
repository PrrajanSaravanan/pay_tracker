import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from paytracker.config import get_settings
from paytracker.db import migrate
from paytracker.db.seed import seed
from paytracker.db.session import sqlalchemy_url


@pytest.fixture(scope="session")
def db_url():
    """A throwaway `<dbname>_test` database on the dev server, migrated and seeded."""
    base = make_url(sqlalchemy_url(get_settings().database_url))
    test_db = f"{base.database}_test"
    admin = create_engine(base.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{test_db}" WITH (FORCE)'))
            conn.execute(text(f'CREATE DATABASE "{test_db}"'))
    except OperationalError:
        pytest.skip("Postgres is not reachable; run `docker compose up -d`")

    url = base.set(database=test_db).render_as_string(hide_password=False)
    migrate.upgrade(url)
    engine = create_engine(url)
    with Session(engine) as session:
        seed(session)
    engine.dispose()

    yield url

    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{test_db}" WITH (FORCE)'))
    admin.dispose()


@pytest.fixture(scope="session")
def engine(db_url):
    engine = create_engine(db_url)
    yield engine
    engine.dispose()


@pytest.fixture
def session(engine):
    """A session whose changes, including commits, are rolled back after the test."""
    with engine.connect() as conn:
        outer = conn.begin()
        with Session(bind=conn, join_transaction_mode="create_savepoint") as session:
            yield session
        outer.rollback()
