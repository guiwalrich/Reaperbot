"""Módulo de gerenciamento do banco de dados SQLite (aiosqlite)."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiosqlite

from bot.config import DATA_DIR

DB_PATH = DATA_DIR / "hotreaper.db"
FREE_DOWNLOAD_LIMIT = 3


def _parse_subscription_end(val) -> datetime | None:
    """Converte o valor retornado do banco para objeto datetime fuso-horário UTC."""
    if val is None:
        return None
    if isinstance(val, datetime):
        if val.tzinfo is None:
            return val.replace(tzinfo=timezone.utc)
        return val
    if isinstance(val, str):
        try:
            dt = datetime.fromisoformat(val)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            return None
    return None


async def init_db() -> None:
    """Cria a tabela users se ela não existir no banco de dados."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                free_downloads_used INTEGER DEFAULT 0,
                subscription_end TIMESTAMP DEFAULT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.commit()


async def get_or_create_user(user_id: int, username: str | None = None) -> dict:
    """Retorna os dados do usuário. Se não existir, insere-o no banco."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()

        if row is None:
            await db.execute(
                "INSERT INTO users (user_id, username, free_downloads_used) VALUES (?, ?, 0)",
                (user_id, username),
            )
            await db.commit()
            async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cursor:
                row = await cursor.fetchone()

        return dict(row)


async def increment_download(user_id: int) -> None:
    """Incrementa o contador de downloads gratuitos utilizados."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET free_downloads_used = free_downloads_used + 1 WHERE user_id = ?",
            (user_id,),
        )
        await db.commit()


async def is_subscribed(user_id: int) -> bool:
    """Verifica se o usuário possui uma assinatura PRO ativa."""
    user = await get_or_create_user(user_id)
    sub_end = _parse_subscription_end(user.get("subscription_end"))
    if sub_end is not None:
        now = datetime.now(timezone.utc)
        return sub_end > now
    return False


async def can_download(user_id: int) -> bool:
    """Verifica se o usuário pode realizar o download (assinatura ativa OU cota grátis disponível)."""
    user = await get_or_create_user(user_id)
    sub_end = _parse_subscription_end(user.get("subscription_end"))
    now = datetime.now(timezone.utc)
    if sub_end is not None and sub_end > now:
        return True

    return user.get("free_downloads_used", 0) < FREE_DOWNLOAD_LIMIT


async def get_remaining_free(user_id: int) -> int:
    """Retorna o número de downloads gratuitos restantes."""
    user = await get_or_create_user(user_id)
    used = user.get("free_downloads_used", 0)
    return max(0, FREE_DOWNLOAD_LIMIT - used)


async def activate_subscription(user_id: int, days: int) -> datetime:
    """Ativa ou renova a assinatura por N dias e salva no banco de dados."""
    user = await get_or_create_user(user_id)
    current_end = _parse_subscription_end(user.get("subscription_end"))
    now = datetime.now(timezone.utc)

    start_base = current_end if (current_end and current_end > now) else now
    new_end = start_base + timedelta(days=days)
    new_end_iso = new_end.isoformat()

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET subscription_end = ? WHERE user_id = ?",
            (new_end_iso, user_id),
        )
        await db.commit()

    return new_end
