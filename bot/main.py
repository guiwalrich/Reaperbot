"""Inicialização e configuração do bot Telegram."""
import asyncio
import logging
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from bot.config import BOT_TOKEN
from bot.database import init_db
from bot.handlers import (
    help_handler,
    message_handler,
    plans_handler,
    settarget_handler,
    start_handler,
    status_handler,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def main() -> None:
    """Ponto de entrada principal do bot."""
    asyncio.run(init_db())

    application = Application.builder().token(BOT_TOKEN).build()

    # Registrar handlers
    application.add_handler(CommandHandler("start", start_handler))
    application.add_handler(CommandHandler("help", help_handler))
    application.add_handler(CommandHandler("settarget", settarget_handler))
    application.add_handler(CommandHandler("status", status_handler))
    application.add_handler(CommandHandler("planos", plans_handler))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler)
    )

    logger.info("HotReaper Bot iniciado. Aguardando mensagens...")
    application.run_polling(allowed_updates=["message"])
