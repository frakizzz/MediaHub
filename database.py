import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base

# Якщо є посилання від Render — беремо його, якщо ні — локальний SQLite
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./mediahub.db")

# Render дає лінк з "postgres://", а SQLAlchemy потрібен "postgresql+asyncpg://"
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)

# SQLite вимагає специфічних налаштувань, Postgres - ні
connect_args = {"check_same_thread": False} if "sqlite" in DATABASE_URL else {}

engine = create_async_engine(DATABASE_URL, echo=False, connect_args=connect_args)
async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()

async def get_db():
    async with async_session() as session:
        yield session