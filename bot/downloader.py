"""Módulo responsável por baixar mídias do Twitter e URLs genéricas."""
import asyncio
import logging
import shutil
import uuid
from pathlib import Path
from urllib.parse import urlparse

import aiofiles
import httpx
import yt_dlp

from bot import messages
from bot.config import TEMP_DIR

logger = logging.getLogger(__name__)

MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB

CONTENT_TYPE_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "video/mp4": ".mp4",
    "video/webm": ".webm",
}


class DownloadError(Exception):
    """Exceção customizada para erros durante o processo de download."""
    pass


def _cleanup(directory: Path) -> None:
    """Apaga todos os arquivos e o próprio diretório de forma silenciosa."""
    try:
        if directory.exists():
            shutil.rmtree(directory, ignore_errors=True)
    except Exception as e:
        logger.warning(f"Erro ao limpar diretório {directory}: {e}")


def _check_sizes(paths: list[Path]) -> None:
    """Verifica se algum dos arquivos baixados excede o limite de 50MB."""
    for path in paths:
        if path.is_file() and path.stat().st_size > MAX_FILE_SIZE_BYTES:
            raise DownloadError(messages.ERROR_TOO_LARGE)


def _run_yt_dlp(url: str, session_dir: Path) -> None:
    """Executa o download via yt-dlp em thread separada."""
    ydl_opts = {
        "outtmpl": str(session_dir / "%(title).50s.%(ext)s"),
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])


async def _download_twitter(url: str, session_dir: Path) -> list[Path]:
    """Baixa mídias do Twitter/X usando yt-dlp."""
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(None, _run_yt_dlp, url, session_dir)
    except yt_dlp.utils.DownloadError as e:
        err_msg = str(e).lower()
        if any(k in err_msg for k in ["private", "not found", "does not exist"]):
            raise DownloadError(messages.ERROR_PRIVATE_TWEET)
        raise DownloadError(messages.ERROR_NO_MEDIA) from e

    paths = [p for p in session_dir.iterdir() if p.is_file() and p.name != ".gitkeep"]
    if not paths:
        raise DownloadError(messages.ERROR_NO_MEDIA)

    _check_sizes(paths)
    return paths


async def _download_generic(url: str, session_dir: Path) -> list[Path]:
    """
    Tentativa 1: yt-dlp (suporta centenas de sites).
    Tentativa 2: httpx com verificação de Content-Type.
    """
    # --- Tentativa 1: yt-dlp ---
    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _run_yt_dlp, url, session_dir)
        paths = [p for p in session_dir.iterdir() if p.is_file() and p.name != ".gitkeep"]
        if paths:
            _check_sizes(paths)
            return paths
    except Exception:
        # Se o yt-dlp falhar ou não gerar arquivos, limpa os arquivos parciais e passa para a Tentativa 2
        for p in session_dir.iterdir():
            if p.is_file() and p.name != ".gitkeep":
                p.unlink(missing_ok=True)

    # --- Tentativa 2: httpx com verificação de Content-Type ---
    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            head_resp = None
            try:
                head_resp = await client.head(url, timeout=15.0)
            except httpx.RequestError:
                pass

            content_type = ""
            content_length = None
            if head_resp and head_resp.status_code == 200:
                content_type = head_resp.headers.get("content-type", "").lower()
                content_length = head_resp.headers.get("content-length")

            if not content_type:
                async with client.stream("GET", url, timeout=15.0) as resp:
                    resp.raise_for_status()
                    content_type = resp.headers.get("content-type", "").lower()
                    content_length = resp.headers.get("content-length")

            if not (content_type.startswith("image/") or content_type.startswith("video/")):
                raise DownloadError(messages.ERROR_NO_MEDIA)

            if content_length and int(content_length) > MAX_FILE_SIZE_BYTES:
                raise DownloadError(messages.ERROR_TOO_LARGE)

            # Determinar nome e extensão do arquivo
            ct_clean = content_type.split(";")[0].strip()
            parsed = urlparse(url)
            ext_from_path = Path(parsed.path).suffix.lower()

            if ext_from_path and len(ext_from_path) > 1:
                filename = Path(parsed.path).name
            else:
                ext = CONTENT_TYPE_EXTENSIONS.get(ct_clean, ".bin")
                filename = f"media{ext}"

            file_path = session_dir / filename

            async with client.stream("GET", url, timeout=60.0) as response:
                response.raise_for_status()
                downloaded_bytes = 0
                async with aiofiles.open(file_path, "wb") as f:
                    async for chunk in response.aiter_bytes():
                        downloaded_bytes += len(chunk)
                        if downloaded_bytes > MAX_FILE_SIZE_BYTES:
                            raise DownloadError(messages.ERROR_TOO_LARGE)
                        await f.write(chunk)

            paths = [file_path]
            _check_sizes(paths)
            return paths

    except DownloadError:
        raise
    except httpx.TimeoutException:
        raise DownloadError(messages.ERROR_TIMEOUT)
    except httpx.HTTPStatusError as e:
        raise DownloadError(messages.ERROR_HTTP.format(status_code=e.response.status_code))
    except httpx.RequestError:
        raise DownloadError(messages.ERROR_UNREACHABLE)
    except Exception as e:
        raise DownloadError(messages.ERROR_NO_MEDIA) from e


async def download(url: str, source: str) -> list[Path]:
    """
    Baixa a mídia da URL informada e retorna a lista de caminhos dos arquivos baixados.
    Cria uma pasta isolada por sessão em temp/<uuid>/.
    Em caso de falha, limpa o diretório da sessão e lança DownloadError.
    """
    session_dir = TEMP_DIR / str(uuid.uuid4())
    session_dir.mkdir(parents=True, exist_ok=True)

    try:
        if source == "twitter":
            paths = await _download_twitter(url, session_dir)
        elif source == "generic":
            paths = await _download_generic(url, session_dir)
        else:
            raise DownloadError("Tipo de fonte não suportado.")

        return paths
    except DownloadError:
        _cleanup(session_dir)
        raise
    except Exception as e:
        _cleanup(session_dir)
        raise DownloadError(messages.ERROR_UNEXPECTED) from e
