from typing import AsyncGenerator, Dict, Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import text
from app.core.config import settings


def normalize_async_db_url(raw_url: str) -> tuple[str, Dict[str, Any]]:
    """Normalizes postgres:// / postgresql:// URLs cleanly for SQLAlchemy + asyncpg."""
    url = (raw_url or "").strip()
    connect_args: Dict[str, Any] = {}
    if url.startswith("postgres://"):
        url = "postgresql+asyncpg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://") and "+asyncpg" not in url.split("://", 1)[0]:
        url = "postgresql+asyncpg://" + url[len("postgresql://"):]

    if url.startswith("postgresql+asyncpg://"):
        parsed = urlparse(url)
        pairs = parse_qsl(parsed.query, keep_blank_values=True)
        filtered = []
        needs_ssl = False
        for k, v in pairs:
            lk = k.lower()
            if lk == "sslmode":
                if v.lower() in ("require", "verify-ca", "verify-full"):
                    needs_ssl = True
            elif lk == "channel_binding":
                continue
            else:
                filtered.append((k, v))
        if needs_ssl or any(h in (parsed.hostname or "") for h in ("neon.tech", "supabase.co", "render.com")):
            connect_args["ssl"] = "require"
        if "-pooler" in (parsed.hostname or ""):
            connect_args["statement_cache_size"] = 0
        url = urlunparse(parsed._replace(query=urlencode(filtered)))

    return url, connect_args


_db_url, _db_connect_args = normalize_async_db_url(settings.DATABASE_URL)

engine = create_async_engine(
    _db_url,
    echo=False,
    future=True,
    pool_pre_ping=True,
    connect_args=_db_connect_args,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False
)

class Base(DeclarativeBase):
    pass

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        
        # SQLite schema auto-migration for newly added columns
        if _db_url.startswith("sqlite"):
            def migrate_sqlite_schema(sync_conn):
                try:
                    # 1. Check reviews table
                    res = sync_conn.execute(text("PRAGMA table_info(reviews)"))
                    r_cols = [row[1] for row in res.fetchall()]
                    if r_cols and 'origin' not in r_cols:
                        sync_conn.execute(text("ALTER TABLE reviews ADD COLUMN origin VARCHAR(50) DEFAULT 'LOCAL_DIRECT'"))
                    
                    # 2. Check google_connections table
                    res_g = sync_conn.execute(text("PRAGMA table_info(google_connections)"))
                    g_cols = [row[1] for row in res_g.fetchall()]
                    if g_cols:
                        for col_name, col_type in [
                            ('token_expiry', 'DATETIME'),
                            ('location_id', 'VARCHAR(100)'),
                            ('location_name', 'VARCHAR(200)'),
                            ('scopes_granted', 'TEXT'),
                            ('updated_at', 'DATETIME')
                        ]:
                            if col_name not in g_cols:
                                sync_conn.execute(text(f"ALTER TABLE google_connections ADD COLUMN {col_name} {col_type}"))

                    # 3. Check youtube_queue_items cross-platform columns
                    res_yq = sync_conn.execute(text("PRAGMA table_info(youtube_queue_items)"))
                    yq_cols = [row[1] for row in res_yq.fetchall()]
                    if yq_cols:
                        for col_name, col_type in [
                            ('ig_status', "VARCHAR(50) DEFAULT 'PENDING'"),
                            ('ig_media_id', 'VARCHAR(100)'),
                            ('ig_url', 'VARCHAR(255)'),
                            ('ig_published_at', 'DATETIME'),
                            ('ig_error', 'TEXT'),
                            ('fb_status', "VARCHAR(50) DEFAULT 'PENDING'"),
                            ('fb_video_id', 'VARCHAR(100)'),
                            ('fb_url', 'VARCHAR(255)'),
                            ('fb_published_at', 'DATETIME'),
                            ('fb_error', 'TEXT'),
                            ('first_comment', 'TEXT'),
                            ('ig_comment_id', 'VARCHAR(100)'),
                            ('fb_comment_id', 'VARCHAR(100)'),
                            ('ai_analyzed', 'BOOLEAN DEFAULT 0')
                        ]:
                            if col_name not in yq_cols:
                                sync_conn.execute(text(f"ALTER TABLE youtube_queue_items ADD COLUMN {col_name} {col_type}"))

                    # 4. Check youtube_drive_settings cross-platform & auto-pilot flags
                    res_ys = sync_conn.execute(text("PRAGMA table_info(youtube_drive_settings)"))
                    ys_cols = [row[1] for row in res_ys.fetchall()]
                    if ys_cols:
                        for col_name, col_type in [
                            ('auto_publish_instagram', 'BOOLEAN DEFAULT 1'),
                            ('auto_publish_facebook', 'BOOLEAN DEFAULT 1'),
                            ('auto_post_immediately', 'BOOLEAN DEFAULT 1'),
                            ('auto_first_comment', 'BOOLEAN DEFAULT 1'),
                            ('encrypted_gemini_api_key', 'TEXT')
                        ]:
                            if col_name not in ys_cols:
                                sync_conn.execute(text(f"ALTER TABLE youtube_drive_settings ADD COLUMN {col_name} {col_type}"))
                except Exception:
                    pass

            await conn.run_sync(migrate_sqlite_schema)
