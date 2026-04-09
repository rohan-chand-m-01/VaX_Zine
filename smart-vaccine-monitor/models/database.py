"""SQLAlchemy async engine and session factory."""

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from config.settings import settings
from utils.logger import setup_logger

logger = setup_logger("vaccine_monitor.database")


class Base(DeclarativeBase):
    """Base class for all ORM models."""
    pass


engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_session() -> AsyncSession:
    """Get an async database session.

    Yields:
        AsyncSession: Database session.
    """
    async with async_session_factory() as session:
        yield session


async def init_db() -> None:
    """Create all database tables if they don't exist."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables created/verified successfully")


async def close_db() -> None:
    """Close the database engine."""
    await engine.dispose()
    logger.info("Database engine closed")
