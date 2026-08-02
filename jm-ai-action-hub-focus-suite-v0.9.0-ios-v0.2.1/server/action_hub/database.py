from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


class Database:
    def __init__(self, url: str):
        self.url = url
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        self.engine: Engine = create_engine(
            url,
            connect_args=connect_args,
            pool_pre_ping=True,
            future=True,
        )
        if url.startswith("sqlite"):
            event.listen(self.engine, "connect", self._enable_sqlite_foreign_keys)
        self.session_factory = sessionmaker(
            bind=self.engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
            class_=Session,
        )

    @staticmethod
    def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    def _alembic_config(self) -> Config:
        cfg = Config()
        cfg.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
        cfg.set_main_option("sqlalchemy.url", self.url.replace("%", "%%"))
        return cfg

    def migrate_schema(self) -> None:
        """Upgrade to the packaged Alembic head.

        v0.1.0 created its schema directly with SQLAlchemy and did not have an
        ``alembic_version`` table. If that baseline is detected, stamp it as the
        first revision and apply only the additive control-loop migration.
        """

        inspector = inspect(self.engine)
        table_names = set(inspector.get_table_names())
        cfg = self._alembic_config()
        if table_names and "alembic_version" not in table_names:
            required_baseline = {"inbox_entries", "action_plans", "action_items", "audit_events"}
            if required_baseline.issubset(table_names):
                command.stamp(cfg, "0001_initial_v010")
        command.upgrade(cfg, "head")

    def create_schema(self, use_migrations: bool = True) -> None:
        if use_migrations:
            self.migrate_schema()
            return
        # A secondary worker may be configured not to run migrations, but it
        # must never bypass Alembic by silently creating the latest tables.
        required = {
            "inbox_entries",
            "action_plans",
            "action_items",
            "mobile_devices",
            "push_notifications",
            "priority_assessments",
            "daily_focus_plans",
            "focus_sessions",
            "alembic_version",
        }
        existing = set(inspect(self.engine).get_table_names())
        if not required.issubset(existing):
            missing = ", ".join(sorted(required - existing))
            raise RuntimeError(f"Database schema is not initialized; missing: {missing}")

    def ping(self) -> bool:
        try:
            with self.engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            return True
        except Exception:
            return False

    def session(self) -> Generator[Session, None, None]:
        db = self.session_factory()
        try:
            yield db
        finally:
            db.close()
