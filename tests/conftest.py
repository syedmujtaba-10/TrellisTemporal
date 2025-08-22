# tests/conftest.py
# tests/conftest.py (very top)
import sys, asyncio
if sys.platform.startswith("win"):
    # aiomysql requires the Selector loop on Windows
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import os
from dotenv import load_dotenv
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

# Load .env so port/creds match your compose
load_dotenv()

@pytest_asyncio.fixture(scope="session")
async def db_ready():
    host = os.getenv("MYSQL_HOST", "localhost")
    port = int(os.getenv("MYSQL_PORT", "3306"))  # set 3307 in .env if you remapped
    db   = os.getenv("MYSQL_DB", "trellis")
    user = os.getenv("MYSQL_USER", "trellis")
    pwd  = os.getenv("MYSQL_PASSWORD", "trellisPW")

    # Driver should match your app (aiomysql if you switched)
    driver = os.getenv("SQLA_DRIVER", "aiomysql")  # set to "asyncmy" if you kept asyncmy
    uri = f"mysql+{driver}://{user}:{pwd}@{host}:{port}/{db}?charset=utf8mb4"

    engine = create_async_engine(uri, pool_pre_ping=True)

    try:
        async with engine.begin() as conn:
            await conn.scalar(text("SELECT 1"))
    except Exception as e:
        import pytest
        pytest.skip(f"MySQL not reachable at {host}:{port} ({e})")

    yield
    await engine.dispose()
