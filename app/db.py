"""Database sessions for code that runs outside a web request (CLI, workers)."""

from functools import cache

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings


@cache
def _engine(url: str):
    return create_engine(url, pool_pre_ping=True)


def session_factory(settings: Settings) -> sessionmaker[Session]:
    return sessionmaker(bind=_engine(settings.sqlalchemy_url), expire_on_commit=False)
