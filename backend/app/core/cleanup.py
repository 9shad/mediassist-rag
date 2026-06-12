import asyncio
from datetime import datetime, timezone

from loguru import logger

from app.core.chat_db import delete_old_conversations
from app.core.config import settings


async def cleanup_old_conversations() -> None:
    """Background task that periodically deletes conversations older than
    CONVERSATION_RETENTION_DAYS (default 30). Runs every CLEANUP_INTERVAL_HOURS."""
    while True:
        try:
            deleted = delete_old_conversations(settings.conversation_retention_days)
            if deleted:
                logger.info(f"Cleanup: deleted {deleted} old conversation(s)")
        except Exception as e:
            logger.warning(f"Cleanup error: {e}")
        await asyncio.sleep(settings.cleanup_interval_hours * 3600)
