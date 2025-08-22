# app/config.py
import os
from dotenv import load_dotenv

load_dotenv()

MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3307"))
MYSQL_DB = os.getenv("MYSQL_DB", "trellis")
MYSQL_USER = os.getenv("MYSQL_USER", "trellis")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "trellisPW")

ASYNC_MYSQL_URI = (
    f"mysql+aiomysql://{MYSQL_USER}:{MYSQL_PASSWORD}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DB}"
    "?charset=utf8mb4"
)

