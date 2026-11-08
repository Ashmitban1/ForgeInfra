"""Local integration entry point; leaves P1's source and GET routes unchanged."""
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / '.env', override=False)

from backend.main import app, _incidents, _lock
from backend.integrations.router import create_notification_router

app.include_router(create_notification_router(_incidents, _lock))
