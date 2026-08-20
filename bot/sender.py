"""Módulo de envio de mídias para o Telegram."""
import logging
from pathlib import Path
from telegram import Bot
from telegram.error import TelegramError

from bot.config import TARGET_CHAT_ID, get_target_chat_id

logger = logging.getLogger(__name__)

# Extensões tratadas como foto
PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
# Extensões tratadas como vídeo
VIDEO_EXTENSIONS = {".mp4", ".webm", ".gif"}
# Limite do Telegram para fotos via send_photo
MAX_PHOTO_SIZE = 10 * 1024 * 1024   # 10 MB
# Limite do Telegram para vídeos via send_video
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


async def send_media(bot: Bot, file_paths: list[Path], caption: str) -> None:
    """
    Envia a lista de arquivos baixados para o TARGET_CHAT_ID.
    Ao final do envio (sucesso ou falha), executa a limpeza da pasta de sessão.
    """
    target_id = get_target_chat_id() or TARGET_CHAT_ID
    if target_id is None:
        raise ValueError("TARGET_CHAT_ID não configurado. Use /settarget para definir o grupo destino.")

    # Caption truncada em 1024 caracteres (limite do Telegram)
    formatted_caption = caption[:1024] if caption else None

    try:
        for idx, path in enumerate(file_paths):
            if not path.exists():
                continue

            current_caption = formatted_caption if idx == 0 else None
            file_size = path.stat().st_size
            ext = path.suffix.lower()

            try:
                if ext in PHOTO_EXTENSIONS:
                    if file_size <= MAX_PHOTO_SIZE:
                        with open(path, "rb") as photo_file:
                            await bot.send_photo(
                                chat_id=target_id,
                                photo=photo_file,
                                caption=current_caption,
                            )
                    else:
                        with open(path, "rb") as doc_file:
                            await bot.send_document(
                                chat_id=target_id,
                                document=doc_file,
                                caption=current_caption,
                            )
                elif ext in VIDEO_EXTENSIONS:
                    if file_size <= MAX_VIDEO_SIZE:
                        with open(path, "rb") as video_file:
                            await bot.send_video(
                                chat_id=target_id,
                                video=video_file,
                                caption=current_caption,
                            )
                    else:
                        with open(path, "rb") as doc_file:
                            await bot.send_document(
                                chat_id=target_id,
                                document=doc_file,
                                caption=current_caption,
                            )
                else:
                    with open(path, "rb") as doc_file:
                        await bot.send_document(
                            chat_id=target_id,
                            document=doc_file,
                            caption=current_caption,
                        )
            except TelegramError as e:
                logger.error(f"Erro ao enviar arquivo individual {path.name}: {e}")
    finally:
        _cleanup_session(file_paths)
