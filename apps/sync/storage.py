"""Where the sync server keeps its data: SQLite on a laptop, PostgreSQL in production.

    VG_SYNC_DATABASE_URL=postgresql+psycopg://user:password@host:5432/viksitgaanw
    VG_SYNC_DB=apps/sync/data/sync.db        # the SQLite file, when no URL is set

The server was written against SQLite, and its queries stay plain SQL with
``?`` placeholders -- this module is what lets the same queries run on
PostgreSQL (Supabase, AWS RDS or any other):

* The tables are declared once, with SQLAlchemy, so each database gets its own
  column types (a picture is ``BLOB`` in SQLite and ``BYTEA`` in PostgreSQL).
* :class:`Conn` keeps the ``sqlite3``-style interface the server uses --
  ``con.execute(sql, params)``, rows readable as ``row["name"]`` or ``row[0]``
  -- and rewrites the placeholders for PostgreSQL.
* Every ``with store.connect()`` block is one transaction. On SQLite, which
  allows one writer at a time, blocks also take a process-wide lock; on
  PostgreSQL several server processes share the database, so code that must
  not race uses row locks (``con.for_update``) and guarded updates instead.

Only SQL both databases accept is used: ``ON CONFLICT ... DO UPDATE/NOTHING``
rather than SQLite's ``INSERT OR REPLACE``.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Sequence

from sqlalchemy import (
    Column,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    PrimaryKeyConstraint,
    Table,
    Text,
    create_engine,
    event,
    inspect,
    text,
)
from sqlalchemy.engine import Connection, CursorResult, Engine
from sqlalchemy.exc import IntegrityError  # noqa: F401 - the server catches it from here

metadata = MetaData()

Table(
    "devices", metadata,
    Column("id", Text, primary_key=True),
    Column("token_hash", Text, nullable=False, unique=True),
    Column("profile_id", Text, nullable=False),
    Column("segment", Text, nullable=False),
    Column("created_at", Text, nullable=False),
    Column("last_seen", Text),
    #: When the current token was issued; a device may swap it for a new one.
    Column("token_issued_at", Text),
    #: Set when the operator cuts a device off. Its token stops working.
    Column("revoked_at", Text),
)
Table(
    "records", metadata,
    Column("entity_type", Text, nullable=False),
    Column("entity_id", Text, nullable=False),
    Column("owner_profile_id", Text, nullable=False),
    Column("parties", Text, nullable=False, server_default="[]"),
    Column("payload", Text, nullable=False),
    Column("deleted", Integer, nullable=False, server_default="0"),
    Column("rev", Integer, nullable=False),
    Column("writer_device", Text, nullable=False),
    Column("updated_at", Text, nullable=False),
    PrimaryKeyConstraint("entity_type", "entity_id"),
    Index("ix_records_rev", "rev"),
)
Table(
    "media", metadata,
    Column("id", Text, primary_key=True),
    Column("entity_type", Text, nullable=False),
    Column("entity_id", Text, nullable=False),
    Column("owner_profile_id", Text, nullable=False),
    Column("mime", Text, nullable=False),
    Column("body", LargeBinary, nullable=False),
    Column("meta", Text, nullable=False, server_default="{}"),
)
Table("counters", metadata, Column("name", Text, primary_key=True), Column("value", Integer, nullable=False))
Table(
    "subscriptions", metadata,
    Column("profile_id", Text, primary_key=True),
    Column("plan", Text, nullable=False),
    Column("until", Text),
    Column("created_at", Text, nullable=False),
)
Table(
    "video_uploads", metadata,
    Column("id", Text, primary_key=True),
    Column("profile_id", Text, nullable=False),
    Column("target", Text, nullable=False),
    Column("entity_id", Text, nullable=False),
    Column("asset_id", Text),
    Column("playback_id", Text),
    Column("status", Text, nullable=False),
    Column("error", Text),
    Column("created_at", Text, nullable=False),
    Column("updated_at", Text, nullable=False),
)
Table(
    "plans", metadata,
    Column("code", Text, primary_key=True),
    Column("name", Text, nullable=False),
    Column("amount_paise", Integer, nullable=False),
    Column("months", Integer, nullable=False),
    Column("active", Integer, nullable=False, server_default="1"),
    Column("created_at", Text, nullable=False),
    #: subscription (months of video uploads) | promotion (days at the top of the lists)
    Column("kind", Text, nullable=False, server_default="subscription"),
    #: A promotion's length. Subscriptions keep theirs in months.
    Column("days", Integer),
    #: A promotion that also alerts the investors and partners it suits, once.
    Column("alert", Integer, nullable=False, server_default="0"),
    #: A message pack: how many messages to people one is not connected with.
    Column("credits", Integer),
)
# Amount and months are copied from the plan when a link is made, so a later
# price change never alters a link already out.
Table(
    "payments", metadata,
    Column("id", Text, primary_key=True),
    Column("profile_id", Text, nullable=False),
    Column("plan", Text, nullable=False),
    Column("plan_name", Text, nullable=False),
    Column("amount_paise", Integer, nullable=False),
    Column("months", Integer, nullable=False),
    Column("link_id", Text, unique=True),
    Column("url", Text),
    Column("status", Text, nullable=False),
    Column("provider_payment_id", Text),
    Column("until_after", Text),
    Column("expires_at", Text, nullable=False),
    Column("created_at", Text, nullable=False),
    Column("paid_at", Text),
    #: Copied from the plan, like the amount: what the payment buys.
    Column("kind", Text, nullable=False, server_default="subscription"),
    Column("days", Integer),
    Column("alert", Integer, nullable=False, server_default="0"),
    #: For a promotion, the record it promotes.
    Column("target_type", Text),
    Column("target_id", Text),
    #: For a message pack, the messages it buys.
    Column("credits", Integer),
    Index("ix_payments_profile", "profile_id"),
)
#: Messages a profile may still send to people it is not connected with. The
#: server alone keeps the count, and takes one as each such message arrives.
Table(
    "message_credits", metadata,
    Column("profile_id", Text, primary_key=True),
    Column("balance", Integer, nullable=False, server_default="0"),
    Column("updated_at", Text, nullable=False),
)
#: A record paid (or granted) a place at the top of others' lists. The server
#: alone decides this, and stamps it onto the record everyone pulls.
Table(
    "promotions", metadata,
    Column("entity_type", Text, nullable=False),
    Column("entity_id", Text, nullable=False),
    Column("profile_id", Text, nullable=False),
    #: The last day it is featured (inclusive), YYYY-MM-DD.
    Column("until", Text, nullable=False),
    #: When an alerting promotion last went through: devices alert once per value.
    Column("alert_at", Text),
    Column("updated_at", Text, nullable=False),
    PrimaryKeyConstraint("entity_type", "entity_id"),
    Index("ix_promotions_profile", "profile_id"),
)
Table("webhook_events", metadata, Column("id", Text, primary_key=True), Column("received_at", Text, nullable=False))
#: A profile's identity check, as this server did it. The server is the only
#: source of a profile's KYC status: whatever a device claims is overwritten.
#: No Aadhaar number, date of birth or document is ever kept (see identity.py).
Table(
    "verifications", metadata,
    Column("profile_id", Text, primary_key=True),
    Column("method", Text, nullable=False),
    #: Salted hash of the provider's id for the person.
    Column("reference", Text, nullable=False),
    #: The name as registered with the provider; shown only to its owner.
    Column("registered_name", Text, nullable=False),
    Column("aadhaar_backed", Integer, nullable=False, server_default="0"),
    Column("verified_at", Text, nullable=False),
    #: One identity vouches for one profile, even when two check at once.
    Index("ix_verifications_reference", "reference", unique=True),
)
#: One attempt: the PKCE verifier and state waiting for the provider's callback.
Table(
    "kyc_sessions", metadata,
    Column("state", Text, primary_key=True),
    Column("profile_id", Text, nullable=False),
    Column("method", Text, nullable=False),
    Column("verifier", Text, nullable=False),
    #: waiting | done | failed
    Column("status", Text, nullable=False),
    Column("error", Text),
    Column("created_at", Text, nullable=False),
    Column("expires_at", Text, nullable=False),
    Index("ix_kyc_sessions_profile", "profile_id"),
)
#: Profiles the operator has suspended for abuse: their devices are refused and
#: what they shared stops reaching anyone.
Table(
    "suspensions", metadata,
    Column("profile_id", Text, primary_key=True),
    Column("reason", Text, nullable=False),
    Column("created_at", Text, nullable=False),
)


class Row:
    """A result row, readable by column name (``row["id"]``) or position (``row[0]``)."""

    __slots__ = ("_values", "_index")

    def __init__(self, values: Sequence[Any], index: dict[str, int]) -> None:
        self._values = tuple(values)
        self._index = index

    def __getitem__(self, key: int | str) -> Any:
        return self._values[key] if isinstance(key, int) else self._values[self._index[key]]

    def keys(self) -> list[str]:
        return list(self._index)

    def get(self, key: str, default: Any = None) -> Any:
        return self[key] if key in self._index else default


class Result:
    def __init__(self, result: CursorResult) -> None:
        self.rowcount = result.rowcount
        if result.returns_rows:
            index = {name: position for position, name in enumerate(result.keys())}
            self._rows = [Row(values, index) for values in result.fetchall()]
        else:
            self._rows = []

    def fetchone(self) -> Row | None:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[Row]:
        return list(self._rows)

    def __iter__(self) -> Iterator[Row]:
        return iter(self._rows)


class Conn:
    """One transaction, with the ``sqlite3``-style interface the server's queries use."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection
        self.dialect = connection.dialect.name
        #: Appended to a SELECT whose rows are about to be changed: on
        #: PostgreSQL it holds them against a concurrent writer until commit.
        #: SQLite has no row locks and needs none -- it runs one writer at a time.
        self.for_update = " FOR UPDATE" if self.dialect == "postgresql" else ""

    def execute(self, sql: str, params: Sequence[Any] = ()) -> Result:
        if self.dialect != "sqlite":
            # psycopg takes %s; a literal % must be doubled first.
            sql = sql.replace("%", "%%").replace("?", "%s")
        return Result(self._connection.exec_driver_sql(sql, tuple(params)))


class Store:
    def __init__(self, url: str) -> None:
        self.url = url
        # No server-side prepared statements on PostgreSQL: a transaction-mode
        # connection pooler (Supabase's, PgBouncer) hands each transaction to
        # whichever backend is free, where a statement prepared elsewhere
        # does not exist -- or, worse, one of the same name already does.
        # These queries are short; preparing them saves nothing worth that.
        connect_args = {"prepare_threshold": None} if url.startswith("postgresql+psycopg") else {}
        self.engine: Engine = create_engine(url, future=True, pool_pre_ping=True, connect_args=connect_args)
        self.dialect = self.engine.dialect.name
        self._lock = threading.Lock() if self.dialect == "sqlite" else None
        if self.dialect == "sqlite":
            event.listen(self.engine, "connect", _sqlite_pragmas)

    @contextmanager
    def connect(self) -> Iterator[Conn]:
        if self._lock is None:
            with self.engine.begin() as connection:
                yield Conn(connection)
            return
        with self._lock, self.engine.begin() as connection:
            yield Conn(connection)

    def create(self) -> None:
        """Create what is missing: tables, and columns added since a database was made."""
        # One connection for all of it: a small database may allow only one.
        with self.engine.begin() as connection:
            metadata.create_all(connection)
            existing = inspect(connection)
            for table in metadata.sorted_tables:
                have = {column["name"] for column in existing.get_columns(table.name)}
                for column in table.columns:
                    if column.name not in have:
                        kind = column.type.compile(dialect=self.engine.dialect)
                        ddl = f"ALTER TABLE {table.name} ADD COLUMN {column.name} {kind}"
                        # Rows already there take the default, rather than NULL.
                        default = column.server_default.arg if column.server_default is not None else None
                        if isinstance(default, str):
                            ddl += " DEFAULT '" + default.replace("'", "''") + "'"
                            if not column.nullable:
                                ddl += " NOT NULL"
                        connection.execute(text(ddl))
            connection.execute(text("INSERT INTO counters (name, value) VALUES ('rev', 0) ON CONFLICT DO NOTHING"))


def _sqlite_pragmas(dbapi_connection: Any, _record: Any) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.close()


def database_url(env: dict[str, str], default_sqlite: Path) -> str:
    """The database to use: VG_SYNC_DATABASE_URL, else the SQLite file."""
    url = env.get("VG_SYNC_DATABASE_URL", "").strip()
    if url:
        # Hosts hand out postgres:// or postgresql://; SQLAlchemy wants the driver named.
        for prefix in ("postgres://", "postgresql://"):
            if url.startswith(prefix):
                return "postgresql+psycopg://" + url[len(prefix):]
        return url
    path = Path(env.get("VG_SYNC_DB") or default_sqlite)
    path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{path.as_posix()}"
