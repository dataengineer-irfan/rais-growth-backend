from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
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
                cursor = sync_conn.connection.cursor()
                # 1. Check reviews table
                r_cols = [c[1] for c in cursor.execute("PRAGMA table_info(reviews)").fetchall()]
                if r_cols and 'origin' not in r_cols:
                    cursor.execute("ALTER TABLE reviews ADD COLUMN origin VARCHAR(50) DEFAULT 'LOCAL_DIRECT'")
                
                # 2. Check google_connections table
                g_cols = [c[1] for c in cursor.execute("PRAGMA table_info(google_connections)").fetchall()]
                if g_cols:
                    for col_name, col_type in [
                        ('token_expiry', 'DATETIME'),
                        ('location_id', 'VARCHAR(100)'),
                        ('location_name', 'VARCHAR(200)'),
                        ('scopes_granted', 'TEXT'),
                        ('updated_at', 'DATETIME')
                    ]:
                        if col_name not in g_cols:
                            cursor.execute(f"ALTER TABLE google_connections ADD COLUMN {col_name} {col_type}")
                sync_conn.connection.commit()
            except Exception:
                pass

        await conn.run_sync(migrate_sqlite_schema)
