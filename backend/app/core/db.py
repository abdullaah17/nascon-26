import time
from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, pool_pre_ping=True, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_session() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session


def initialize_database(retries: int = 60) -> None:
    from app.core.models import Base as ModelBase

    last_error: Exception | None = None
    for _ in range(retries):
        try:
            ModelBase.metadata.create_all(engine)
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            return
        except Exception as exc:  # database can still be starting
            last_error = exc
            time.sleep(1)
    raise RuntimeError("database did not become ready") from last_error
