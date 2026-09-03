"""Handlers para processamento de comandos e mensagens do Telegram com suporte avançado a Canais e Groq IA."""
import html
import logging
import re
import shutil
import time
import traceback
import uuid
from pathlib import Path
from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from bot.utils import messages
from bot.core.config import OWNER_ID, VAULT_DIR
from bot.modules.ai_caption import generate_ai_caption
from bot.core.database import (
    get_config,
    set_config,
    log_download,
    get_channel,
    register_channel,
    add_media_to_vault,
    get_vault_stats,
)
from bot.modules.downloader import DownloadError, download
from bot.utils.resolver import classify_url
from bot.modules.scheduler import dispatch_next_from_vault
from bot.modules.sender import _probe_video_metadata

logger = logging.getLogger(__name__)

URL_PATTERN = re.compile(r"https?://\S+")


def _is_owner(user_id: int) -> bool:
    """Verifica se o usuário é o dono exclusivo do bot (Fail-closed estrito)."""
    if not OWNER_ID or OWNER_ID <= 0:
        logger.error("⛔ OWNER_ID não configurado no .env! Acesso estritamente bloqueado.")
        return False
    return user_id == OWNER_ID


def _clean_markdown(text: str) -> str:
    """Sanitiza caracteres especiais de Markdown para evitar erros de formatação no Telegram."""
    if not text:
        return ""
    return text.replace("`", "\x27").replace("*", "").replace("_", "").replace("[", "(").replace("]", ")")


async def _safe_reply(update: Update, text: str) -> None:
    """Responde à mensagem do usuário de forma segura contra falhas de rede."""
    msg = update.effective_message
    if msg:
        try:
            await msg.reply_text(text, parse_mode="Markdown")
        except TelegramError as e:
            logger.warning(f"Aviso ao enviar resposta Telegram: {e}")


async def _safe_edit_or_reply(status_msg, update: Update, text: str) -> None:
    """Edita a mensagem de status ou envia uma nova se a edição falhar."""
    if status_msg:
        try:
            await status_msg.edit_text(text, parse_mode="Markdown")
            return
        except TelegramError:
            pass

    await _safe_reply(update, text)


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Responde ao comando /start com instruções de uso."""
    if not update.effective_user or not _is_owner(update.effective_user.id):
        return
    await _safe_reply(update, messages.START)


async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Responde ao comando /help com ajuda detalhada."""
    if not update.effective_user or not _is_owner(update.effective_user.id):
        return
    await _safe_reply(update, messages.HELP)


async def settarget_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Define ou cadastra um grupo/canal destino para envio das mídias.
    Suporta:
    1. /settarget @nomedocanal ou /settarget -100xxxxxxxxxx (enviado no privado)
    2. /settarget enviado dentro de um grupo
    3. /settarget enviado como post dentro de um canal
    """
    # 1. Se foi enviado como post de canal (channel_post)
    if update.channel_post:
        chat = update.effective_chat
        if not chat:
            return
        chat_id = str(chat.id)
        chat_title = chat.title or "Canal VIP"
        await set_config("target_chat_id", chat_id)
        await register_channel(chat_id, chat_title, "instant")
        try:
            await update.channel_post.reply_text(
                f"✅ *Canal configurado com sucesso como destino!*\n\n"
                f"• *Nome:* `{chat_title}`\n"
                f"• *ID:* `{chat_id}`",
                parse_mode="Markdown"
            )
        except Exception:
            pass
        return

    # 2. Se foi enviado por usuário
    if not update.effective_user or not _is_owner(update.effective_user.id):
        return

    # Caso A: Usuário passou argumento no comando (ex: /settarget @canalvip ou /settarget -1001234567890)
    if context.args and len(context.args) > 0:
        target_input = context.args[0].strip()
        try:
            chat = await context.bot.get_chat(target_input)
            chat_id = str(chat.id)
            chat_title = chat.title or chat.username or target_input

            # Verifica se o bot é administrador no canal
            try:
                member = await context.bot.get_chat_member(chat_id, context.bot.id)
                if member.status.lower() not in ["administrator", "creator"]:
                    await _safe_reply(
                        update,
                        f"⚠️ *Atenção:* O canal `{chat_title}` foi configurado, mas o bot *não é administrador* lá!\n\n"
                        f"👉 Adicione o bot como Administrador no canal com permissão de postar mensagens para que os envios funcionem."
                    )
            except Exception:
                pass

            await set_config("target_chat_id", chat_id)
            await register_channel(chat_id, chat_title, "instant")
            await _safe_reply(
                update,
                f"🎯 *Canal configurado com sucesso!*\n\n"
                f"• *Nome:* `{chat_title}`\n"
                f"• *ID:* `{chat_id}`\n"
                f"• *Status:* Ativo para novos downloads e disparos.\n\n"
                f"_Você pode gerenciar este e outros canais pelo comando `/painel`._"
            )
            return

        except TelegramError as e:
            await _safe_reply(
                update,
                f"❌ *Não foi possível acessar o canal `{target_input}`.*\n\n"
                f"📌 *Como resolver:*\n"
                f"1. Adicione este bot ao seu canal como **Administrador** (com permissão de postar mensagens).\n"
                f"2. Em seguida, envie aqui:\n"
                f"   `/settarget {target_input}`\n\n"
                f"_Detalhe do erro: {e.message}_"
            )
            return
        except Exception as e:
            await _safe_reply(update, f"❌ Erro ao configurar canal: {e}")
            return

    # Caso B: Usuário executou /settarget sem argumentos
    if update.effective_chat:
        chat_id = str(update.effective_chat.id)
        chat_title = update.effective_chat.title or "Canal Principal"

        # Se executou no chat privado, exibe o tutorial fácil de configuração
        if update.effective_chat.type == "private":
            current_target = await get_config("target_chat_id", "") or "Nenhum canal configurado"
            channel_info = await get_channel(current_target) if current_target else None
            curr_name = channel_info.get("title", current_target) if channel_info else current_target

            await _safe_reply(
                update,
                f"🎯 *CONFIGURAÇÃO DE CANAL DESTINO*\n\n"
                f"• *Canal Ativo Atual:* `{curr_name}`\n\n"
                f"📋 *Como vincular seu canal:* \n"
                f"1. Abra seu canal no Telegram e adicione o bot como **Administrador** (permissão de enviar mensagens).\n"
                f"2. Envie aqui no privado o @username ou o ID numérico do canal:\n"
                f"   • `/settarget @seucanal`\n"
                f"   • `/settarget -1001234567890`\n\n"
                f"_Dica: Você também pode usar o menu 🎯 Canais no `/painel`._"
            )
            return

        # Se executou dentro de um grupo/supergrupo
        await set_config("target_chat_id", chat_id)
        await register_channel(chat_id, chat_title, "instant")
        await _safe_reply(update, f"✅ *Este chat foi configurado como destino:* `{chat_title}` (`{chat_id}`)")


async def setwelcome_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Configura o texto padrão e edita a mensagem de boas-vindas do canal em tempo real."""
    if not update.effective_user or not _is_owner(update.effective_user.id):
        return

    target_chat = await get_config("target_chat_id", "")
    if not context.args:
        cur_text = await get_config("welcome_message_text", "")
        help_msg = (
            "📝 *Mensagem Oficial de Boas-Vindas Atual:*\n\n"
            f"{cur_text}\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "💡 *Como alterar:*\n"
            "Envie `/setwelcome <seu novo texto aqui>` para atualizar o texto padrão e editar a mensagem já fixada no canal em tempo real!"
        )
        await _safe_reply(update, help_msg)
        return

    new_text = " ".join(context.args).strip()
    await set_config("welcome_message_text", new_text)

    edited_in_channel = False
    if target_chat:
        from bot.modules.scheduler import edit_welcome_message
        edited_in_channel = await edit_welcome_message(context.bot, target_chat, new_text)

    chan_info = f"`{target_chat}`" if target_chat else "_(Nenhum canal configurado)_"
    status_line = "• *Mensagem editada no canal:* ✅ Sim (em tempo real)" if edited_in_channel else "• *Status no canal:* Salvo como padrão para o próximo envio"

    resp = (
        "✅ *Mensagem de Boas-Vindas atualizada com sucesso!*\n\n"
        f"• *Canal Alvo:* {chan_info}\n"
        f"{status_line}\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📋 *Nova Mensagem:*\n\n"
        f"{new_text}"
    )
    await _safe_reply(update, resp)


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Processa mensagens com links, faz download, gera legenda IA e encaminha ao Acervo/Disparo."""
    if not update.effective_user or not _is_owner(update.effective_user.id):
        return

    if not update.message or not update.message.text:
        return

    match = URL_PATTERN.search(update.message.text)
    if not match:
        return

    url = match.group(0)
    source = classify_url(url)

    if source == "unknown":
        await _safe_reply(update, messages.ERROR_UNKNOWN_URL)
        return

    silent_mode_str = await get_config("silent_mode", "false")
    is_silent = silent_mode_str.lower() == "true"

    status_msg = None
    if not is_silent and update.message:
        try:
            status_msg = await update.message.reply_text(messages.DOWNLOADING, parse_mode="Markdown")
        except TelegramError as e:
            logger.debug(f"Aviso ao enviar status downloading: {e}")

    start_time = time.monotonic()

    try:
        target_chat_id = await get_config("target_chat_id", "")
        if not target_chat_id:
            raise ValueError("Destino não configurado")

        channel = await get_channel(target_chat_id)
        if not channel:
            await register_channel(target_chat_id, "Canal Principal", "instant")
            channel = await get_channel(target_chat_id)

        dispatch_mode = channel.get("dispatch_mode", "instant") if channel else "instant"

        # Executa download universal com extração e normalização FFmpeg
        file_paths = await download(url, source)
        total_size = sum(p.stat().st_size for p in file_paths if p.is_file())

        chan_vault_dir = VAULT_DIR / str(target_chat_id)
        chan_vault_dir.mkdir(parents=True, exist_ok=True)

        last_ai_caption = ""

        # Salva as mídias no Acervo do canal
        for p in file_paths:
            if not p.exists() or not p.is_file():
                continue

            ext = p.suffix.lower()
            mtype = "video" if ext in [".mp4", ".webm", ".mov", ".mkv"] else "photo"

            caption_mode = await get_config("caption_mode", "ai")
            if caption_mode == "url":
                ai_cap = url
            elif caption_mode == "custom":
                ai_cap = await get_config("custom_caption", "") or url
            else:
                # No modo AI, a legenda é gerada fresca no momento exato do disparo
                ai_cap = None

            vault_file_path = chan_vault_dir / f"{uuid.uuid4().hex[:10]}{ext}"
            shutil.move(p, vault_file_path)

            width, height, duration_sec = 0, 0, 0
            if mtype == "video":
                w, h, d = await _probe_video_metadata(vault_file_path)
                width = w or 0
                height = h or 0
                duration_sec = d or 0

            await add_media_to_vault(
                channel_id=target_chat_id,
                file_path=vault_file_path,
                media_type=mtype,
                file_size_bytes=vault_file_path.stat().st_size,
                duration_seconds=duration_sec,
                width=width,
                height=height,
                title=p.stem,
                ai_caption=ai_cap,
                original_url=url,
            )

        duration = time.monotonic() - start_time

        # Registra sucesso no histórico do banco de dados
        await log_download(
            url=url,
            source=source,
            file_count=len(file_paths),
            total_size_bytes=total_size,
            status="SUCCESS",
            error_message=None,
            duration_seconds=duration,
        )

        # Se o canal estiver em modo de disparo instantâneo, dispara agora
        if dispatch_mode == "instant":
            dispatch_res = await dispatch_next_from_vault(context.bot, target_chat_id)
            disp_cap = dispatch_res.get("caption") or "Enviado com sucesso!"
            success_text = f"{messages.SENT_SUCCESS}\n⚡ *Legenda IA:* _{_clean_markdown(disp_cap)}_\n{messages.PROCESSING_TIME.format(duration=duration)}"
        else:
            stats = await get_vault_stats(target_chat_id)
            mode_lbl = "⏰ *AGENDADO*" if dispatch_mode == "scheduled" else "🖐 *MANUAL*"
            success_text = (
                f"📦 *Mídia salva no Acervo com sucesso!*\n\n"
                f"• *Modo de Disparo:* {mode_lbl}\n"
                f"• *Fila do Canal:* {stats['pending_videos']} vídeos | {stats['pending_photos']} fotos\n"
                f"• *Legenda IA:* ⏰ _Será gerada no momento da publicação no canal_\n\n"
                f"{messages.PROCESSING_TIME.format(duration=duration)}"
            )

        if not is_silent:
            await _safe_edit_or_reply(status_msg, update, success_text)

    except DownloadError as e:
        duration = time.monotonic() - start_time
        err_str = str(e)
        await log_download(url, source, 0, 0, "FAILED", err_str, duration)
        await _safe_edit_or_reply(status_msg, update, err_str)

    except ValueError:
        duration = time.monotonic() - start_time
        err_str = "Destino não configurado"
        await log_download(url, source, 0, 0, "FAILED", err_str, duration)
        await _safe_edit_or_reply(status_msg, update, messages.ERROR_NO_TARGET)

    except Exception as e:
        duration = time.monotonic() - start_time
        err_str = f"{type(e).__name__}: {e}"
        logger.error(f"Erro inesperado ao processar {url}: {e}\n{traceback.format_exc()}")
        await log_download(url, source, 0, 0, "FAILED", err_str, duration)

        safe_err = _clean_markdown(str(e)[:120])
        msg_err = messages.ERROR_UNEXPECTED.format(error=safe_err)
        await _safe_edit_or_reply(status_msg, update, msg_err)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler global de erros e exceções não tratadas."""
    logger.error(f"Exceção não tratada ao processar update: {context.error}", exc_info=context.error)


