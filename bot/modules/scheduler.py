"""Módulo do Motor de Cadência Inteligente (2 Vídeos -> 1 Pack de até 3 Fotos) e Agendador Supervisionado em Background."""
import asyncio
import datetime
import logging
from pathlib import Path
from typing import Any

from telegram import Bot, InputMediaPhoto, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.error import TelegramError, RetryAfter

from bot.core.database import (
    get_config,
    get_channel,
    get_all_channels,
    register_channel,
    acquire_next_pending_video,
    acquire_next_pending_photos_pack,
    release_media_reservation,
    increment_channel_video_counter,
    reset_channel_video_counter,
    mark_media_sent_and_delete,
    mark_channel_welcomed,
    set_config,
    set_channel_welcome_message_id,
    get_channel_welcome_message_id,
    update_channel_last_dispatched,
)
from bot.modules.ai_caption import generate_ai_caption
from bot.modules.sender import _probe_video_metadata

logger = logging.getLogger(__name__)
async def _send_video_with_retry(
    bot: Bot,
    chat_id: str | int,
    file_path: Path,
    caption: str,
    width: int = 0,
    height: int = 0,
    duration: int = 0,
    max_retries: int = 3,
) -> None:
    """Envia um vídeo individual com suporte a streaming e metadados."""
    if not width or not height or not duration:
        p_w, p_h, p_d = await _probe_video_metadata(file_path)
        width = width or p_w
        height = height or p_h
        duration = duration or p_d

    for attempt in range(max_retries):
        try:
            with open(file_path, "rb") as vf:
                kwargs = {
                    "chat_id": chat_id,
                    "video": vf,
                    "caption": caption[:1024] if caption else None,
                    "supports_streaming": True,
                    "write_timeout": 300.0,
                    "read_timeout": 300.0,
                    "connect_timeout": 60.0,
                }
                if width and height:
                    kwargs["width"] = width
                    kwargs["height"] = height
                if duration:
                    kwargs["duration"] = duration

                await bot.send_video(**kwargs)
            return

        except RetryAfter as e:
            if attempt == max_retries - 1:
                raise TelegramError(f"RateLimit persistente ({e.retry_after}s)") from e
            await asyncio.sleep(float(e.retry_after) + 1.0)
        except TelegramError as e:
            if attempt == max_retries - 1:
                raise e
            await asyncio.sleep(2.0)


async def _send_photos_pack_with_retry(
    bot: Bot,
    chat_id: str | int,
    photos_data: list[dict[str, Any]],
    caption: str,
    max_retries: int = 3,
) -> None:
    """Envia até 3 fotos em formato de álbum (send_media_group) ou foto individual."""
    if not photos_data:
        return

    if len(photos_data) == 1:
        fpath = Path(photos_data[0]["file_path"])
        for attempt in range(max_retries):
            try:
                with open(fpath, "rb") as pf:
                    await bot.send_photo(
                        chat_id=chat_id,
                        photo=pf,
                        caption=caption[:1024] if caption else None,
                        write_timeout=300.0,
                        read_timeout=300.0,
                    )
                return
            except RetryAfter as e:
                if attempt == max_retries - 1:
                    raise TelegramError(f"RateLimit ({e.retry_after}s)") from e
                await asyncio.sleep(float(e.retry_after) + 1.0)
            except TelegramError as e:
                if attempt == max_retries - 1:
                    raise e
                await asyncio.sleep(2.0)
        return

    for attempt in range(max_retries):
        open_files = []
        try:
            media_group = []
            for idx, p_info in enumerate(photos_data):
                fpath = Path(p_info["file_path"])
                f_handle = open(fpath, "rb")
                open_files.append(f_handle)
                c = caption[:1024] if (idx == 0 and caption) else None
                media_group.append(InputMediaPhoto(media=f_handle, caption=c))

            await bot.send_media_group(
                chat_id=chat_id,
                media=media_group,
                write_timeout=300.0,
                read_timeout=300.0,
            )
            return
        except RetryAfter as e:
            if attempt == max_retries - 1:
                raise TelegramError(f"RateLimit ({e.retry_after}s)") from e
            await asyncio.sleep(float(e.retry_after) + 1.0)
        except TelegramError as e:
            if attempt == max_retries - 1:
                raise e
            await asyncio.sleep(2.0)
        finally:
            for fh in open_files:
                try:
                    fh.close()
                except Exception:
                    pass



async def send_welcome_message(bot: Bot, channel_id: str | int) -> int | None:
    """Envia a mensagem oficial de boas-vindas estilizada com botão interativo e fixa no topo do canal."""
    cid_str = str(channel_id).strip()
    text = await get_config("welcome_message_text")
    if not text:
        text = (
            "🔥 *SEJA MUITO BEM-VINDO AO MEU VIP PRIVADO!* 💋\n\n"
            "Que delícia ter você aqui comigo, amor... Esse cantinho foi criado só pra quem quer me ver sem filtros, sem censura e do jeitinho que você sempre sonhou. 😈\n\n"
            "✨ *O que vai rolar por aqui:*\n"
            "• Vídeos pesados e inéditos toda semana 🎬\n"
            "• Ensaios e fotos exclusivas que não posto em lugar nenhum 📸\n"
            "• Minha intimidade sem nenhum limite... 🔥\n\n"
            "🔔 *Dica de ouro:* Fixa esse canal no topo do seu Telegram e ativa as notificações para não perder nenhuma das minhas loucuras que vão entrar no ar!\n\n"
            "_Prepara a mente (e o corpo)... o show tá só começando._ 🔞🤤"
        )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔔 Ativar Notificações", callback_data="btn_mute_tip")]
    ])

    try:
        sent_msg = await bot.send_message(
            chat_id=cid_str,
            text=text,
            parse_mode="Markdown",
            reply_markup=keyboard,
        )
        try:
            await bot.pin_chat_message(
                chat_id=cid_str,
                message_id=sent_msg.message_id,
                disable_notification=False,
            )
        except Exception as pe:
            logger.warning(f"Aviso ao fixar mensagem de boas-vindas no canal {cid_str}: {pe}")

        await set_channel_welcome_message_id(cid_str, sent_msg.message_id)
        await mark_channel_welcomed(cid_str, 1)
        logger.info(f"Mensagem de boas-vindas enviada e fixada com sucesso no canal {cid_str}.")
        return sent_msg.message_id
    except Exception as e:
        logger.error(f"Erro ao enviar mensagem de boas-vindas no canal {cid_str}: {e}")
        return None

async def edit_welcome_message(bot: Bot, channel_id: str | int, new_text: str) -> bool:
    """
    Edita em tempo real a mensagem de boas-vindas já fixada no canal VIP e atualiza o template padrão.
    Se a mensagem não existir ou tiver sido excluída, envia uma nova e a fixa.
    """
    cid_str = str(channel_id).strip()
    await set_config("welcome_message_text", new_text)

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔔 Ativar Notificações", callback_data="btn_mute_tip")]
    ])

    msg_id = await get_channel_welcome_message_id(cid_str)
    if msg_id > 0:
        try:
            await bot.edit_message_text(
                chat_id=cid_str,
                message_id=msg_id,
                text=new_text,
                parse_mode="Markdown",
                reply_markup=keyboard,
            )
            logger.info(f"Mensagem de boas-vindas {msg_id} editada com sucesso no canal {cid_str}.")
            return True
        except Exception as e:
            logger.warning(f"Não foi possível editar mensagem {msg_id} no canal {cid_str} ({e}). Enviando nova...")

    # Se não conseguiu editar ou msg_id = 0, envia e fixa
    new_id = await send_welcome_message(bot, cid_str)
    return new_id is not None
_DISPATCH_LOCKS: dict[str, asyncio.Lock] = {}


def get_dispatch_lock(channel_id: str | int) -> asyncio.Lock:
    """Retorna ou cria uma trava assíncrona por canal para impedir disparos concorrentes simultâneos."""
    cid_str = str(channel_id).strip()
    if cid_str not in _DISPATCH_LOCKS:
        _DISPATCH_LOCKS[cid_str] = asyncio.Lock()
    return _DISPATCH_LOCKS[cid_str]


async def dispatch_next_from_vault(bot: Bot, channel_id: str | int) -> dict[str, Any]:
    """
    Executa o próximo disparo do acervo aplicando a REGRA DE CADÊNCIA com RESERVA ATÔMICA
    e trava de exclusão mútua (evita dois disparos ao mesmo tempo).
    """
    cid_str = str(channel_id).strip()
    lock = get_dispatch_lock(cid_str)
    if lock.locked():
        logger.warning(f"Disparo concorrente bloqueado para o canal {cid_str}: envio já em andamento.")
        return {
            "success": False,
            "media_type": "in_progress",
            "count": 0,
            "message": "⏳ Já existe um disparo sendo enviado para este canal! Aguarde o término.",
        }

    async with lock:
        channel = await get_channel(cid_str)
        if not channel:
            await register_channel(cid_str, "Canal de Disparo", "instant")
            channel = await get_channel(cid_str)

        # ─── BOAS-VINDAS: Envia e fixa antes do primeiro disparo no canal se ainda não enviada ───
        welcome_enabled_str = await get_config("welcome_message_enabled", "true")
        if welcome_enabled_str and welcome_enabled_str.lower() == "true":
            has_welcomed = channel.get("has_welcomed", 0) if channel else 0
            if not has_welcomed:
                await send_welcome_message(bot, cid_str)
                channel = await get_channel(cid_str)

        consecutive_videos = channel.get("consecutive_videos_count", 0) if channel else 0

        # ─── CENÁRIO A: Já saíram 2 vídeos seguidos -> Hora do Pack de Fotos ───
        if consecutive_videos >= 2:
            photos = await acquire_next_pending_photos_pack(cid_str, max_photos=3)
            if photos:
                try:
                    caption = photos[0].get("ai_caption") or await generate_ai_caption(
                        photos[0].get("title", ""),
                        media_type="photo",
                        media_path=photos[0].get("file_path"),
                    )
                    await _send_photos_pack_with_retry(bot, cid_str, photos, caption)
                    await mark_media_sent_and_delete([p["id"] for p in photos])
                    await reset_channel_video_counter(cid_str)
                    await update_channel_last_dispatched(cid_str)
                    logger.info(f"Pack de {len(photos)} fotos disparado com sucesso no canal {cid_str}. Cadência resetada.")
                    return {
                        "success": True,
                        "media_type": "photo_pack",
                        "count": len(photos),
                        "caption": caption,
                        "message": f"📸 Pack de {len(photos)} fotos disparado com sucesso!",
                    }
                except Exception as e:
                    await release_media_reservation([p["id"] for p in photos])
                    logger.error(f"Erro ao disparar pack de fotos no canal {cid_str}: {e}")
                    raise

            # Fallback se não houver fotos no acervo: envia o próximo vídeo
            video = await acquire_next_pending_video(cid_str)
            if video:
                try:
                    v_path = Path(video["file_path"])
                    caption = video.get("ai_caption") or await generate_ai_caption(
                        video.get("title", ""),
                        media_type="video",
                        media_path=v_path,
                    )
                    await _send_video_with_retry(
                        bot, cid_str, v_path, caption,
                        width=video.get("width", 0),
                        height=video.get("height", 0),
                        duration=video.get("duration_seconds", 0)
                    )
                    await mark_media_sent_and_delete([video["id"]])
                    await increment_channel_video_counter(cid_str)
                    await update_channel_last_dispatched(cid_str)
                    logger.info(f"Vídeo (fallback) disparado com sucesso no canal {cid_str}.")
                    return {
                        "success": True,
                        "media_type": "video",
                        "count": 1,
                        "caption": caption,
                        "message": "🎬 Vídeo disparado com sucesso (sem fotos no acervo)!",
                    }
                except Exception as e:
                    await release_media_reservation([video["id"]])
                    logger.error(f"Erro ao disparar vídeo fallback no canal {cid_str}: {e}")
                    raise

            return {"success": False, "media_type": "none", "count": 0, "message": "❌ O acervo deste canal está vazio."}

    # ─── CENÁRIO B: Menos de 2 vídeos enviados -> Dispara Vídeo ───
    video = await acquire_next_pending_video(cid_str)
    if video:
        try:
            v_path = Path(video["file_path"])
            caption = video.get("ai_caption") or await generate_ai_caption(
                video.get("title", ""),
                media_type="video",
                media_path=v_path,
            )
            await _send_video_with_retry(
                bot, cid_str, v_path, caption,
                width=video.get("width", 0),
                height=video.get("height", 0),
                duration=video.get("duration_seconds", 0)
            )
            await mark_media_sent_and_delete([video["id"]])
            new_count = await increment_channel_video_counter(cid_str)
            await update_channel_last_dispatched(cid_str)
            logger.info(f"Vídeo disparado com sucesso no canal {cid_str} ({new_count}/2).")
            return {
                "success": True,
                "media_type": "video",
                "count": 1,
                "caption": caption,
                "message": f"🎬 Vídeo disparado com sucesso! ({new_count}/2)",
            }
        except Exception as e:
            await release_media_reservation([video["id"]])
            logger.error(f"Erro ao disparar vídeo no canal {cid_str}: {e}")
            raise

    # Fallback se não houver vídeos no acervo: tenta enviar fotos
    photos = await acquire_next_pending_photos_pack(cid_str, max_photos=3)
    if photos:
        try:
            caption = photos[0].get("ai_caption") or await generate_ai_caption(
                photos[0].get("title", ""),
                media_type="photo",
                media_path=photos[0].get("file_path"),
            )
            await _send_photos_pack_with_retry(bot, cid_str, photos, caption)
            await mark_media_sent_and_delete([p["id"] for p in photos])
            await reset_channel_video_counter(cid_str)
            await update_channel_last_dispatched(cid_str)
            logger.info(f"Fotos (fallback) disparadas com sucesso no canal {cid_str}.")
            return {
                "success": True,
                "media_type": "photo_pack",
                "count": len(photos),
                "caption": caption,
                "message": f"📸 Pack de {len(photos)} fotos disparado com sucesso (sem vídeos no acervo)!",
            }
        except Exception as e:
            await release_media_reservation([p["id"] for p in photos])
            logger.error(f"Erro ao disparar fotos fallback no canal {cid_str}: {e}")
            raise

    return {"success": False, "media_type": "none", "count": 0, "message": "❌ O acervo deste canal está vazio."}


async def run_schedule_worker(bot: Bot) -> None:
    """Worker assíncrono em background que verifica e dispara mídias (por intervalo de horas ou horários fixos)."""
    logger.info("⏰ Agendador de disparos do HotReaper ativo.")
    last_checked_minute = ""

    while True:
        try:
            from bot.core.config import get_brazil_now
            now = get_brazil_now()
            current_minute = now.strftime("%H:%M")

            if current_minute != last_checked_minute:
                last_checked_minute = current_minute
                channels = await get_all_channels()

                for ch in channels:
                    mode = ch.get("dispatch_mode", "instant")
                    cid = ch["channel_id"]

                    # 1. Modo Horários Fixos
                    if mode == "scheduled":
                        schedule_times_str = ch.get("schedule_times", "")
                        times = [t.strip() for t in schedule_times_str.split(",") if t.strip()]

                        if current_minute in times:
                            logger.info(f"⏰ Horário programado atingido ({current_minute}) para o canal {cid}. Iniciando disparo...")
                            try:
                                res = await dispatch_next_from_vault(bot, cid)
                                logger.info(f"Resultado do disparo agendado no canal {cid}: {res.get('message')}")
                            except Exception as e:
                                logger.error(f"Erro no disparo agendado para o canal {cid}: {e}")

                    # 2. Modo Intervalo Dinâmico (A cada X horas)
                    elif mode == "interval":
                        interval_h = ch.get("interval_hours") or 2
                        last_disp = ch.get("last_dispatched_at")
                        should_dispatch = False

                        if not last_disp:
                            should_dispatch = True
                        else:
                            try:
                                if isinstance(last_disp, str):
                                    last_dt = datetime.datetime.fromisoformat(last_disp)
                                else:
                                    last_dt = last_disp
                                elapsed = (now - last_dt).total_seconds()
                                if elapsed >= interval_h * 3600:
                                    should_dispatch = True
                            except Exception:
                                should_dispatch = True

                        if should_dispatch:
                            logger.info(f"⏱️ Intervalo de {interval_h}h atingido para o canal {cid}. Disparando...")
                            try:
                                res = await dispatch_next_from_vault(bot, cid)
                                logger.info(f"Resultado do disparo por intervalo no canal {cid}: {res.get('message')}")
                            except Exception as e:
                                logger.error(f"Erro no disparo por intervalo para o canal {cid}: {e}")

        except asyncio.CancelledError:
            logger.info("⏰ Schedule worker cancelado.")
            break
        except Exception as e:
            logger.error(f"Erro no ciclo do schedule worker: {e}")

        await asyncio.sleep(20)


async def supervised_schedule_worker(bot: Bot) -> None:
    """Supervisor resiliente que monitora e reinicia o schedule_worker se ele falhar inesperadamente."""
    while True:
        try:
            await run_schedule_worker(bot)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"⚠️ Supervisor: Schedule worker sofreu falha crítica: {e}. Reiniciando em 5 segundos...")
            await asyncio.sleep(5)
