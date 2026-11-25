from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import text
from app.core.config import settings

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    future=True
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
                        ('fb_error', 'TEXT')
                    ]:
                        if col_name not in yq_cols:
                            sync_conn.execute(text(f"ALTER TABLE youtube_queue_items ADD COLUMN {col_name} {col_type}"))

                # 4. Check youtube_drive_settings cross-platform flags
                res_ys = sync_conn.execute(text("PRAGMA table_info(youtube_drive_settings)"))
                ys_cols = [row[1] for row in res_ys.fetchall()]
                if ys_cols:
                    for col_name, col_type in [
                        ('auto_publish_instagram', 'BOOLEAN DEFAULT 1'),
                        ('auto_publish_facebook', 'BOOLEAN DEFAULT 1')
                    ]:
                        if col_name not in ys_cols:
                            sync_conn.execute(text(f"ALTER TABLE youtube_drive_settings ADD COLUMN {col_name} {col_type}"))
            except Exception:
                pass

        await conn.run_sync(migrate_sqlite_schema)
