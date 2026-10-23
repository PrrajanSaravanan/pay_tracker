from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from paytracker.config import get_settings


def sqlalchemy_url(database_url: str) -> str:
    """Point plain postgresql:// URLs at the psycopg 3 driver."""
    if database_url.startswith("postgresql://"):
        return "postgresql+psycopg://" + database_url.removeprefix("postgresql://")
    return database_url


@lru_cache
def get_engine() -> Engine:
    return create_engine(sqlalchemy_url(get_settings().database_url))


def get_session() -> Session:
    return sessionmaker(get_engine())()
