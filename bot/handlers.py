"""Handlers para processamento de comandos e mensagens do Telegram."""
import logging
import re
import traceback
from datetime import datetime
from telegram import Update
from telegram.ext import ContextTypes

from bot import messages
from bot.config import ALLOWED_USER_IDS, save_target_chat_id
from bot.database import (
    _parse_subscription_end,
    can_download,
    get_or_create_user,
    get_remaining_free,
    increment_download,
    is_subscribed,
)
from bot.downloader import DownloadError, download
from bot.resolver import classify_url
from bot.sender import send_media

logger = logging.getLogger(__name__)

URL_PATTERN = re.compile(r"https?://\S+")


def _is_authorized(user_id: int) -> bool:
    """Verifica se o usuário está autorizado a utilizar o bot."""
    if not ALLOWED_USER_IDS:
        return True  # Lista vazia = sem restrição de usuários
    return user_id in ALLOWED_USER_IDS


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Responde ao comando /start com instruções de uso."""
    if not update.effective_user or not _is_authorized(update.effective_user.id):
        return

    if update.message:
        await update.message.reply_text(messages.START, parse_mode="Markdown")


async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Responde ao comando /help com ajuda detalhada."""
    if not update.effective_user or not _is_authorized(update.effective_user.id):
        return

    if update.message:
        await update.message.reply_text(messages.HELP, parse_mode="Markdown")


async def settarget_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Define o chat atual como o grupo/canal destino para envio das mídias."""
    if not update.effective_user or not _is_authorized(update.effective_user.id):
        return

    if not update.effective_chat:
        return

    chat_id = update.effective_chat.id
    save_target_chat_id(chat_id)

    if update.message:
        await update.message.reply_text(messages.TARGET_SET, parse_mode="Markdown")


async def status_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Exibe o status atual de uso e assinatura do usuário."""
    if not update.effective_user or not _is_authorized(update.effective_user.id):
        return

    user_id = update.effective_user.id
    username = update.effective_user.username
    user = await get_or_create_user(user_id, username)
    subscribed = await is_subscribed(user_id)

    if not update.message:
        return

    if subscribed:
        sub_end = _parse_subscription_end(user.get("subscription_end"))
        expiry_str = sub_end.strftime("%d/%m/%Y") if sub_end else "N/A"
        await update.message.reply_text(messages.STATUS_PRO.format(expiry=expiry_str), parse_mode="Markdown")
    else:
        used = user.get("free_downloads_used", 0)
        remaining = max(0, 3 - used)
        await update.message.reply_text(messages.STATUS_FREE.format(used=used, remaining=remaining), parse_mode="Markdown")


async def plans_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Exibe a lista de planos de assinatura disponíveis."""
    if not update.effective_user or not _is_authorized(update.effective_user.id):
        return

    if update.message:
        await update.message.reply_text(
            messages.PLANS.format(price_monthly="150 ⭐", price_quarterly="350 ⭐"),
            parse_mode="Markdown",
        )


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Processa mensagens recebidas, verifica freemium, extrai URLs e realiza o envio."""
    if not update.effective_user or not _is_authorized(update.effective_user.id):
        return

    if not update.message or not update.message.text:
        return

    user_id = update.effective_user.id
    username = update.effective_user.username
    await get_or_create_user(user_id, username)

    match = URL_PATTERN.search(update.message.text)
    if not match:
        return

    url = match.group(0)
    source = classify_url(url)

    if source == "unknown":
        await update.message.reply_text(messages.ERROR_UNKNOWN_URL, parse_mode="Markdown")
        return

    # Verificar limite freemium antes de baixar
    if not await can_download(user_id):
        await update.message.reply_text(messages.FREE_LIMIT_REACHED, parse_mode="Markdown")
        return

    status_msg = await update.message.reply_text(messages.DOWNLOADING)

    try:
        file_paths = await download(url, source)
        await send_media(context.bot, file_paths, caption=url)

        # Incrementar contador após envio bem-sucedido
        await increment_download(user_id)
        subscribed = await is_subscribed(user_id)
        remaining = await get_remaining_free(user_id)

        if subscribed:
            await status_msg.edit_text(messages.SENT_SUCCESS, parse_mode="Markdown")
        elif remaining == 0:
            await status_msg.edit_text(messages.FREE_DOWNLOADS_LAST, parse_mode="Markdown")
        else:
            await status_msg.edit_text(
                messages.FREE_DOWNLOADS_REMAINING.format(remaining=remaining),
                parse_mode="Markdown",
            )

    except DownloadError as e:
        await status_msg.edit_text(str(e), parse_mode="Markdown")
    except ValueError:
        await status_msg.edit_text(messages.ERROR_NO_TARGET, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Erro inesperado no message_handler: {e}\n{traceback.format_exc()}")
        await status_msg.edit_text(messages.ERROR_UNEXPECTED, parse_mode="Markdown")
