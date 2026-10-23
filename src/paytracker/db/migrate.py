"""Run Alembic from code, independent of the current working directory."""

from pathlib import Path

from alembic import command
from alembic.config import Config

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def alembic_config(url: str | None = None) -> Config:
    """Alembic config. Without `url`, env.py falls back to the app's DATABASE_URL."""
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    if url:
        # Config values go through ConfigParser interpolation, so escape '%'.
        config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return config


def upgrade(url: str | None = None) -> None:
    command.upgrade(alembic_config(url), "head")


def downgrade(url: str | None = None) -> None:
    command.downgrade(alembic_config(url), "base")
