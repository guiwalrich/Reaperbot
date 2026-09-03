"""Módulo de envio de mídias para o Telegram com metadados reais, streaming nativo e resiliência."""
import asyncio
import json
import logging
import sys
from pathlib import Path
from telegram import Bot
from telegram.error import TelegramError, RetryAfter

from bot.core.database import get_config

logger = logging.getLogger(__name__)

# Extensões tratadas como foto
PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
# Extensões tratadas como vídeo
VIDEO_EXTENSIONS = {".mp4", ".webm", ".gif", ".mov", ".mkv"}

MAX_PHOTO_SIZE = 10 * 1024 * 1024   # 10 MB
MAX_VIDEO_SIZE = 50 * 1024 * 1024   # 50 MB


def _cleanup_session(file_paths: list[Path]) -> None:
    """Identifica a pasta pai da sessão e apaga todos os seus arquivos e a própria pasta."""
    if not file_paths:
        return

    try:
        session_dir = file_paths[0].parent
        if not session_dir.exists() or not session_dir.is_dir():
            return

        for path in session_dir.iterdir():
            if path.is_file():
                path.unlink(missing_ok=True)

        session_dir.rmdir()
    except Exception as e:
        logger.warning(f"Erro ao limpar pasta de sessão {file_paths[0].parent}: {e}")


async def _probe_video_metadata(path: Path) -> tuple[int | None, int | None, int | None]:
    """
    Extrai largura, altura e duração do vídeo usando ffprobe para renderização perfeita no Telegram.
    Retorna (width, height, duration_seconds).
    """
    cmd = [
        "ffprobe",
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,duration:format=duration",
        "-of", "json",
        str(path),
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10.0)
        if proc.returncode == 0 and stdout:
            data = json.loads(stdout.decode(errors="ignore"))
            width = None
            height = None
            duration = None

            streams = data.get("streams", [])
            if streams:
                width = streams[0].get("width")
                height = streams[0].get("height")
                dur_raw = streams[0].get("duration")
                if dur_raw:
                    try:
                        duration = int(float(dur_raw))
                    except ValueError:
                        pass

            if duration is None and "format" in data:
                dur_raw = data["format"].get("duration")
                if dur_raw:
                    try:
                        duration = int(float(dur_raw))
                    except ValueError:
                        pass

            return width, height, duration
    except Exception as e:
        logger.debug(f"Aviso ao obter metadados do vídeo: {e}")

    return None, None, None


async def _send_single_file_with_retry(
    bot: Bot,
    target_id: int | str,
    path: Path,
    caption: str | None,
    max_retries: int = 3,
) -> None:
    """Envia um arquivo individual com metadados nativos e suporte a streaming."""
    file_size = path.stat().st_size
    ext = path.suffix.lower()

    width, height, duration = None, None, None
    if ext in VIDEO_EXTENSIONS:
        width, height, duration = await _probe_video_metadata(path)

    for attempt in range(max_retries):
        try:
            if ext in PHOTO_EXTENSIONS:
                if file_size <= MAX_PHOTO_SIZE:
                    with open(path, "rb") as photo_file:
                        await bot.send_photo(
                            chat_id=target_id,
                            photo=photo_file,
                            caption=caption,
                            write_timeout=300.0,
                            read_timeout=300.0,
                        )
                else:
                    with open(path, "rb") as doc_file:
                        await bot.send_document(
                            chat_id=target_id,
                            document=doc_file,
                            caption=caption,
                            write_timeout=300.0,
                            read_timeout=300.0,
                        )
            elif ext in VIDEO_EXTENSIONS:
                if file_size <= MAX_VIDEO_SIZE:
                    with open(path, "rb") as video_file:
                        kwargs = {
                            "chat_id": target_id,
                            "video": video_file,
                            "caption": caption,
                            "supports_streaming": True,
                            "write_timeout": 300.0,
                            "read_timeout": 300.0,
                        }
                        if width and height:
                            kwargs["width"] = width
                            kwargs["height"] = height
                        if duration:
                            kwargs["duration"] = duration

                        await bot.send_video(**kwargs)
                else:
                    with open(path, "rb") as doc_file:
                        await bot.send_document(
                            chat_id=target_id,
                            document=doc_file,
                            caption=caption,
                            write_timeout=300.0,
                            read_timeout=300.0,
                        )
            else:
                with open(path, "rb") as doc_file:
                    await bot.send_document(
                        chat_id=target_id,
                        document=doc_file,
                        caption=caption,
                        write_timeout=300.0,
                        read_timeout=300.0,
                    )
            return

        except RetryAfter as e:
            if attempt == max_retries - 1:
                raise TelegramError(f"Telegram RateLimit persistente após {max_retries} tentativas ({e.retry_after}s)") from e

            wait_time = float(e.retry_after) + 1.0
            logger.warning(f"Telegram RateLimit atingido. Aguardando {wait_time}s para reenvio de {path.name}...")
            await asyncio.sleep(wait_time)

        except TelegramError as e:
            logger.error(f"Tentativa {attempt + 1}/{max_retries} falhou para enviar {path.name}: {e}")
            if attempt == max_retries - 1:
                raise e
            await asyncio.sleep(2.0)


async def send_media(bot: Bot, file_paths: list[Path], caption: str = "") -> None:
    """
    Envia a lista de arquivos baixados para o canal/grupo destino configurado no banco de dados.
    Garante limpeza da pasta temporária em qualquer cenário.
    """
    try:
        target_id = await get_config("target_chat_id", "")
        if not target_id:
            raise ValueError("TARGET_CHAT_ID não configurado. Use /settarget ou configure no /painel.")

        formatted_caption = caption[:1024] if caption else None

        for idx, path in enumerate(file_paths):
            if not path.exists() or not path.is_file():
                continue

            current_caption = formatted_caption if idx == 0 else None
            await _send_single_file_with_retry(bot, target_id, path, current_caption)
    finally:
        _cleanup_session(file_paths)

