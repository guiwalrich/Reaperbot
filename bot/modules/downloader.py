"""Motor de Download do HotReaper Bot com proteção SSRF, hierarquia estrita de mídias e streaming com limites de memória."""
import asyncio
import json
import logging
import os
import re
import signal
import sys
import uuid
from pathlib import Path
from typing import Literal
from urllib.parse import urljoin, urlparse

import aiofiles
import httpx

from bot.utils import messages
from bot.core.config import TEMP_DIR
from bot.core.database import get_config
from bot.utils.resolver import is_safe_url, normalize_media_url, resolve_redirect_url

logger = logging.getLogger(__name__)

# Controle de sessões ativas para isolamento seguro
ACTIVE_SESSIONS: set[Path] = set()

# Regex para extração estrita de URLs de vídeo e imagem
VIDEO_EXTENSIONS_PATTERN = re.compile(r"https?://[^\s\"\'<>]+\.(?:mp4|webm|mov|mkv|m4v)(?:\?[^\s\"\'<>]*)?", re.IGNORECASE)
IMAGE_EXTENSIONS_PATTERN = re.compile(r"https?://[^\s\"\'<>]+\.(?:jpe?g|png|webp|gif)(?:\?[^\s\"\'<>]*)?", re.IGNORECASE)
M3U8_PATTERN = re.compile(r"https?://[^\s\"\'<>]+\.m3u8(?:\?[^\s\"\'<>]*)?", re.IGNORECASE)

CONTENT_TYPE_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "video/mp4": ".mp4",
    "video/webm": ".webm",
    "video/quicktime": ".mov",
    "video/x-matroska": ".mkv",
}

USER_AGENT_BROWSER = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Tamanho mínimo obrigatório para arquivo de vídeo (50 KB)
MIN_VIDEO_BYTES = 50 * 1024


class DownloadError(Exception):
    """Exceção levantada quando ocorre um erro conhecido durante o download."""
    pass


async def _kill_process_tree(proc: asyncio.subprocess.Process) -> None:
    """Encerra a árvore de processos completa para evitar processos zumbis."""
    if proc.returncode is not None:
        return
    try:
        if sys.platform != "win32":
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        else:
            proc.kill()
        await proc.wait()
    except (ProcessLookupError, OSError):
        pass


def _check_sizes(file_paths: list[Path], max_bytes: int, max_mb: int) -> None:
    """Valida o tamanho individual dos arquivos pós-processamento."""
    for p in file_paths:
        if p.exists() and p.stat().st_size > max_bytes:
            raise DownloadError(messages.ERROR_TOO_LARGE.format(max_size=max_mb))


async def _probe_video_codecs(file_path: Path, timeout: float = 8.0) -> tuple[str, str, str]:
    """Retorna (vcodec, pix_fmt, acodec) usando ffprobe para decisão inteligente de stream copy."""
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "stream=codec_type,codec_name,pix_fmt",
        "-of", "json",
        str(file_path),
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        if proc.returncode == 0 and stdout:
            data = json.loads(stdout.decode("utf-8", errors="ignore"))
            vcodec, pix_fmt, acodec = "", "", ""
            for s in data.get("streams", []):
                ctype = s.get("codec_type")
                if ctype == "video" and not vcodec:
                    vcodec = s.get("codec_name", "").lower()
                    pix_fmt = s.get("pix_fmt", "").lower()
                elif ctype == "audio" and not acodec:
                    acodec = s.get("codec_name", "").lower()
            return vcodec, pix_fmt, acodec
    except Exception:
        pass
    return "", "", ""

async def _normalize_video_for_telegram(input_path: Path, max_bytes: int, timeout: float = 60.0) -> Path:
    """
    Normaliza o vídeo para máxima compatibilidade no Telegram com Transcode Inteligente:
    - Se já for H.264 + yuv420p + AAC <= 48MB: executa Stream Copy instantâneo (-c copy) em 0.3s.
    - Caso contrário: executa re-encode adaptativo libx264/aac/yuv420p com FastStart.
    """
    if not input_path.exists() or not input_path.is_file():
        return input_path

    ext = input_path.suffix.lower()
    if ext not in [".mp4", ".webm", ".mov", ".mkv", ".ts"]:
        return input_path

    out_file = input_path.parent / f"norm_{uuid.uuid4().hex[:6]}.mp4"
    file_size = input_path.stat().st_size

    # Fase 3: Checagem estrita de compatibilidade para Stream Copy instantâneo (-c copy)
    if ext == ".mp4" and file_size <= 48 * 1024 * 1024:
        vcodec, pix_fmt, acodec = await _probe_video_codecs(input_path)
        if vcodec == "h264" and pix_fmt == "yuv420p" and acodec in ["aac", "mp4a", ""]:
            cmd_copy = [
                "ffmpeg", "-y", "-i", str(input_path),
                "-c", "copy",
                "-movflags", "+faststart",
                str(out_file),
            ]
            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd_copy,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await asyncio.wait_for(proc.communicate(), timeout=10.0)
                if out_file.exists() and out_file.stat().st_size >= MIN_VIDEO_BYTES:
                    try:
                        input_path.unlink(missing_ok=True)
                    except Exception:
                        pass
                    return out_file
            except Exception as e:
                logger.debug(f"Stream copy fallback para transcode completo: {e}")

    # Se o arquivo for muito pesado (> 48MB), aplica taxa de compressão adaptativa
    if file_size > 48 * 1024 * 1024:
        cmd = [
            "ffmpeg", "-y", "-i", str(input_path),
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "28",
            "-pix_fmt", "yuv420p",
            "-vf", "scale=min(1280\\,iw):-2",
            "-c:a", "aac",
            "-b:a", "128k",
            "-movflags", "+faststart",
            "-threads", "0",
            str(out_file),
        ]
    else:
        cmd = [
            "ffmpeg", "-y", "-i", str(input_path),
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "128k",
            "-movflags", "+faststart",
            "-threads", "0",
            str(out_file),
        ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(proc.communicate(), timeout=timeout)

        if out_file.exists() and out_file.stat().st_size >= MIN_VIDEO_BYTES:
            try:
                input_path.unlink(missing_ok=True)
            except Exception:
                pass
            return out_file
    except Exception as e:
        logger.warning(f"Normalização FFmpeg falhou para {input_path.name}: {e}. Mantendo arquivo original.")

    return input_path


def _extract_video_urls_from_html(html_content: str, base_url: str) -> list[str]:
    """Extrai URLs de vídeo de tags <video>, metadados og:video e variáveis de players JS."""
    found: list[str] = []

    # 1. Tags HTML5 <video> e <source>
    tag_matches = re.findall(r'<video[^>]+src=["\']([^"\']+)["\']', html_content, re.IGNORECASE)
    source_matches = re.findall(r'<source[^>]+src=["\']([^"\']+)["\']', html_content, re.IGNORECASE)
    found.extend(tag_matches)
    found.extend(source_matches)

    # 2. Metatags OpenGraph / Twitter Cards (og:video, twitter:player:stream)
    og_matches = re.findall(r'<meta[^>]+(?:property|name)=["\'](?:og:video(?::url|:secure_url)?|twitter:player:stream)["\'][^>]+content=["\']([^"\']+)["\']', html_content, re.IGNORECASE)
    found.extend(og_matches)

    # 3. Variáveis JavaScript de Players (KVS, VideoJS, JWPlayer, Flashvars)
    js_patterns = [
        r'(?:video_url|video_alt_url|file|src|stream_url|hls_url)\s*[:=]\s*["\'](https?://[^"\']+\.(?:mp4|webm|m3u8)[^"\']*)["\']',
        r'get_file/([^\s"\'<>]+\.mp4)',
        r'["\'](https?://[^"\']+/get_file/[^"\']+\.mp4[^"\']*)["\']',
    ]
    for pattern in js_patterns:
        for m in re.findall(pattern, html_content, re.IGNORECASE):
            found.append(m)

    # 4. Busca por extensões diretas de vídeo no HTML
    found.extend(VIDEO_EXTENSIONS_PATTERN.findall(html_content))
    found.extend(M3U8_PATTERN.findall(html_content))

    # Normaliza e deduplica
    cleaned: list[str] = []
    seen = set()
    for raw in found:
        # Se for caminho relativo tipo get_file/123.mp4
        if raw.startswith("get_file/"):
            full = urljoin(base_url, "/" + raw)
        else:
            full = urljoin(base_url, raw)

        # Filtra descartes óbvios (posters, thumbs, avatares)
        lower_full = full.lower()
        if any(bad in lower_full for bad in ["poster=", "thumbnail=", "avatar", "preview.jpg"]):
            continue

        if full not in seen:
            seen.add(full)
            cleaned.append(full)

    return cleaned


def _extract_image_urls_from_html(html_content: str, base_url: str) -> list[str]:
    """Extrai URLs de imagens de postagens reais, descartando estritamente avatares e posters."""
    found: list[str] = []

    # Metatags OpenGraph
    og_matches = re.findall(r'<meta[^>]+(?:property|name)=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', html_content, re.IGNORECASE)
    found.extend(og_matches)

    # Tags <img> principais de conteúdo
    img_matches = re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', html_content, re.IGNORECASE)
    found.extend(img_matches)

    found.extend(IMAGE_EXTENSIONS_PATTERN.findall(html_content))

    cleaned: list[str] = []
    seen = set()
    for raw in found:
        full = urljoin(base_url, raw)
        lower_full = full.lower()

        # Descarte estrito de avatares, logos, ícones e posters
        if any(bad in lower_full for bad in [
            "avatar", "useravatar", "logo", "icon", "favicon",
            "poster", "thumb", "capa", "banner", "default", ".svg"
        ]):
            continue

        if full not in seen:
            seen.add(full)
            cleaned.append(full)

    return cleaned


async def _run_yt_dlp_subprocess(
    url: str,
    session_dir: Path,
    timeout: float,
    max_mb: int,
) -> None:
    """Executa o yt-dlp via subprocess com validação estrita de certificados TLS."""
    clean_url = normalize_media_url(url)
    outtmpl = str(session_dir / "%(id)s.%(ext)s")

    format_selector = (
        f"bestvideo*[vcodec^=avc1][filesize<={max_mb}M]+bestaudio[acodec^=mp4a]/"
        f"bestvideo*[filesize<={max_mb}M]+bestaudio/"
        f"best[filesize<={max_mb}M]/"
        f"bestvideo*+bestaudio/best"
    )

    cmd = [
        sys.executable,
        "-m",
        "yt_dlp",
        "-o", outtmpl,
        "--format", format_selector,
        "--format-sort", "vcodec:h264,acodec:aac,res,size",
        "--merge-output-format", "mp4",
        "--user-agent", USER_AGENT_BROWSER,
        "--referer", clean_url,
        "--add-header", "Accept-Language: pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
        "--add-header", "Sec-Ch-Ua: \"Chromium\";v=\"124\", \"Google Chrome\";v=\"124\", \"Not-A.Brand\";v=\"99\"",
        "--add-header", "Sec-Ch-Ua-Mobile: ?0",
        "--add-header", "Sec-Ch-Ua-Platform: \"Windows\"",
        "--concurrent-fragments", "16",
        "--buffersize", "16K",
        "--http-chunk-size", "10M",
        "--max-downloads", "10",
        "--no-warnings",
        "--socket-timeout", "25",
        clean_url,
    ]

    kwargs_proc = {}
    if sys.platform != "win32":
        kwargs_proc["start_new_session"] = True

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        **kwargs_proc,
    )

    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        await _kill_process_tree(proc)
        raise DownloadError(messages.ERROR_TIMEOUT)

    # Filtra e descarta falsos positivos
    downloaded_files = []
    for p in session_dir.iterdir():
        if p.is_file() and p.name != ".gitkeep":
            ext = p.suffix.lower()
            if ext in [".svg", ".ico", ".html", ".xml", ".txt", ".json"]:
                p.unlink(missing_ok=True)
                continue
            if ext in [".mp4", ".webm", ".mov", ".mkv"] and p.stat().st_size < MIN_VIDEO_BYTES:
                p.unlink(missing_ok=True)
                continue
            downloaded_files.append(p)

    if downloaded_files:
        return

    if proc.returncode != 0:
        err_msg = (stderr.decode(errors="ignore") if stderr else "").lower()
        if any(k in err_msg for k in ["private", "not found", "does not exist", "deleted"]):
            raise DownloadError(messages.ERROR_PRIVATE_TWEET)
        raise DownloadError(messages.ERROR_NO_MEDIA)


async def _download_with_curl(
    file_url: str,
    session_dir: Path,
    max_bytes: int,
    max_mb: int,
    timeout: float = 45.0,
) -> Path:
    """Download de contingência com curl nativo para bypass de WAF/Cloudflare (TLS fingerprint)."""
    parsed = urlparse(file_url)
    ext = Path(parsed.path).suffix.lower()
    if not ext or len(ext) > 5:
        ext = ".mp4"
    filename = f"media_{uuid.uuid4().hex[:8]}{ext}"
    file_path = session_dir / filename

    cmd = [
        "curl",
        "-sL",
        "-A", USER_AGENT_BROWSER,
        "-H", "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,video/*,*/*;q=0.8",
        "-H", "Accept-Language: pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
        "-H", "Sec-Ch-Ua: \"Chromium\";v=\"124\", \"Google Chrome\";v=\"124\", \"Not-A.Brand\";v=\"99\"",
        "-H", "Sec-Ch-Ua-Mobile: ?0",
        "-H", "Sec-Ch-Ua-Platform: \"Windows\"",
        "-e", f"{parsed.scheme}://{parsed.netloc}/",
        "--max-time", str(int(timeout)),
        "--max-filesize", str(int(max_bytes * 1.25)),
        "-o", str(file_path),
        file_url,
    ]
    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(proc.communicate(), timeout=timeout + 5.0)

        if file_path.exists() and file_path.stat().st_size >= MIN_VIDEO_BYTES:
            return file_path
    except Exception as e:
        if proc and proc.returncode is None:
            try:
                proc.kill()
            except Exception:
                pass
        logger.debug(f"Download curl falhou para {file_url}: {e}")

    raise DownloadError(messages.ERROR_NO_MEDIA)

async def _download_stream_file(
    client: httpx.AsyncClient,
    file_url: str,
    session_dir: Path,
    max_bytes: int,
    max_mb: int,
) -> Path:
    """Baixa um arquivo via streaming direto com controle rígido de memória e tamanho."""
    if ".m3u8" in file_url.lower():
        await _run_yt_dlp_subprocess(file_url, session_dir, timeout=60.0, max_mb=max_mb)
        paths = [p for p in session_dir.iterdir() if p.is_file() and p.name != ".gitkeep"]
        if paths:
            return paths[0]
        raise DownloadError(messages.ERROR_NO_MEDIA)

    async with client.stream("GET", file_url) as response:
        response.raise_for_status()
        content_type = response.headers.get("content-type", "").lower().split(";")[0].strip()
        parsed = urlparse(file_url)
        ext_from_path = Path(parsed.path).suffix.lower()

        if ext_from_path and len(ext_from_path) > 1 and len(ext_from_path) <= 5:
            filename = f"media_{uuid.uuid4().hex[:8]}{ext_from_path}"
        else:
            ext = CONTENT_TYPE_EXTENSIONS.get(content_type, ".mp4")
            filename = f"media_{uuid.uuid4().hex[:8]}{ext}"

        if Path(filename).suffix.lower() in [".svg", ".ico", ".html", ".xml", ".txt", ".json"]:
            raise DownloadError(messages.ERROR_NO_MEDIA)

        file_path = session_dir / filename
        ext_clean = file_path.suffix.lower()
        is_video = ext_clean in [".mp4", ".webm", ".mov", ".mkv", ".ts"]
        limit_bytes = int(max_bytes * 2.5) if is_video else max_bytes

        downloaded_bytes = 0
        async with aiofiles.open(file_path, "wb") as f:
            async for chunk in response.aiter_bytes():
                downloaded_bytes += len(chunk)
                if downloaded_bytes > limit_bytes:
                    raise DownloadError(messages.ERROR_TOO_LARGE.format(max_size=max_mb))
                await f.write(chunk)

    if not file_path.exists() or file_path.stat().st_size == 0:
        raise DownloadError(messages.ERROR_NO_MEDIA)

    if is_video and file_path.stat().st_size < MIN_VIDEO_BYTES:
        file_path.unlink(missing_ok=True)
        raise DownloadError(messages.ERROR_NO_MEDIA)

    return file_path


async def _download_generic(url: str, session_dir: Path, max_bytes: int, max_mb: int, timeout: float) -> list[Path]:
    """Pipeline Universal de Download com streaming seguro e inspeção HTML limitada a 2MB."""
    clean_url = normalize_media_url(url)
    if not await is_safe_url(clean_url):
        raise DownloadError(messages.ERROR_UNKNOWN_URL)

    # --- Estágio 1: yt-dlp universal ---
    try:
        await _run_yt_dlp_subprocess(clean_url, session_dir, timeout, max_mb)
        paths = [p for p in session_dir.iterdir() if p.is_file() and p.name != ".gitkeep"]
        if paths:
            normalized_paths = []
            for p in paths:
                norm_p = await _normalize_video_for_telegram(p, max_bytes, timeout=45.0)
                normalized_paths.append(norm_p)
            _check_sizes(normalized_paths, max_bytes, max_mb)
            return normalized_paths
    except DownloadError as e:
        err_msg = str(e).lower()
        if str(e) in (messages.ERROR_TIMEOUT, messages.ERROR_PRIVATE_TWEET) or 'muito grande' in err_msg or 'limite' in err_msg:
            raise
        for p in session_dir.iterdir():
            if p.is_file() and p.name != ".gitkeep":
                p.unlink(missing_ok=True)
    except Exception:
        for p in session_dir.iterdir():
            if p.is_file() and p.name != ".gitkeep":
                p.unlink(missing_ok=True)

    # --- Estágio 2 e 3: HTTP Streaming & Inspecionador Web com Limite de Memória ---
    try:
        async def _check_redirect(response: httpx.Response):
            if response.is_redirect and "location" in response.headers:
                raw_location = str(response.headers["location"])
                target_url = resolve_redirect_url(str(response.url), raw_location)
                if not await is_safe_url(target_url):
                    raise DownloadError(messages.ERROR_UNKNOWN_URL)

        headers = {
            "User-Agent": USER_AGENT_BROWSER,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": clean_url,
        }

        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=timeout,
            headers=headers,
            event_hooks={"response": [_check_redirect]},
        ) as client:
            # 1. Faz stream da requisição para inspecionar Content-Type sem carregar tudo em RAM
            async with client.stream("GET", clean_url) as stream_resp:
                stream_resp.raise_for_status()
                content_type = stream_resp.headers.get("content-type", "").lower().split(";")[0].strip()
                final_url = str(stream_resp.url)

                # Se a URL já for arquivo de mídia direto
                if content_type.startswith("image/") or content_type.startswith("video/") or content_type.startswith("application/octet-stream"):
                    file_path = await _download_stream_file(client, clean_url, session_dir, max_bytes, max_mb)
                    norm_file = await _normalize_video_for_telegram(file_path, max_bytes, timeout=45.0)
                    _check_sizes([norm_file], max_bytes, max_mb)
                    return [norm_file]

                # Se for página HTML, lê no máximo 2MB de texto para proteção contra DoS de memória
                html_text = ""
                if "html" in content_type:
                    chunks = []
                    read_bytes = 0
                    max_html_bytes = 2 * 1024 * 1024  # 2 MB limite de segurança
                    async for chunk in stream_resp.aiter_bytes():
                        read_bytes += len(chunk)
                        chunks.append(chunk)
                        if read_bytes > max_html_bytes:
                            break
                    html_text = b"".join(chunks).decode("utf-8", errors="ignore")

            if html_text:
                # 1. Prioridade: Vídeos Reais (KVS/JS Streams e HTML5)
                video_candidates = _extract_video_urls_from_html(html_text, final_url)
                for candidate in video_candidates:
                    try:
                        file_path = await _download_stream_file(client, candidate, session_dir, max_bytes, max_mb)
                        norm_file = await _normalize_video_for_telegram(file_path, max_bytes, timeout=45.0)
                        _check_sizes([norm_file], max_bytes, max_mb)
                        return [norm_file]
                    except Exception:
                        for p in session_dir.iterdir():
                            if p.is_file() and p.name != ".gitkeep":
                                p.unlink(missing_ok=True)
                        continue

                # 2. Imagens Reais (Packs de até 10 Fotos)
                image_candidates = _extract_image_urls_from_html(html_text, final_url)
                downloaded_images = []
                for candidate in image_candidates[:10]:
                    try:
                        file_path = await _download_stream_file(client, candidate, session_dir, max_bytes, max_mb)
                        _check_sizes([file_path], max_bytes, max_mb)
                        downloaded_images.append(file_path)
                    except Exception:
                        continue
                if downloaded_images:
                    return downloaded_images

    except DownloadError:
        raise
    except httpx.HTTPStatusError as e:
        if e.response.status_code in (403, 401, 503):
            try:
                curl_file = await _download_with_curl(clean_url, session_dir, max_bytes, max_mb, timeout)
                ext = curl_file.suffix.lower()
                if ext in [".mp4", ".webm", ".mov", ".mkv", ".ts"]:
                    norm_file = await _normalize_video_for_telegram(curl_file, max_bytes, timeout=45.0)
                    _check_sizes([norm_file], max_bytes, max_mb)
                    return [norm_file]
                else:
                    _check_sizes([curl_file], max_bytes, max_mb)
                    return [curl_file]
            except Exception as ce:
                logger.debug(f"Fallback curl falhou para {clean_url}: {ce}")
        raise DownloadError(messages.ERROR_HTTP.format(status_code=e.response.status_code))
    except (httpx.ConnectError, httpx.ConnectTimeout):
        raise DownloadError(messages.ERROR_UNREACHABLE)
    except httpx.TimeoutException:
        raise DownloadError(messages.ERROR_TIMEOUT)
    except Exception as e:
        logger.warning(f"Inspecionador web falhou para {url}: {e}")

    # Valida se algum arquivo válido foi salvo na pasta
    valid_paths = [p for p in session_dir.iterdir() if p.is_file() and p.name != ".gitkeep"]
    if valid_paths:
        return valid_paths

    raise DownloadError(messages.ERROR_NO_MEDIA)


async def _download_twitter(url: str, session_dir: Path, max_bytes: int, max_mb: int, timeout: float) -> list[Path]:
    """Download especializado para Twitter/X."""
    return await _download_generic(url, session_dir, max_bytes, max_mb, timeout)


async def download(url: str, source: Literal["twitter", "generic"]) -> list[Path]:
    """Ponto de entrada público do motor de download com sessão atômica isolada."""
    session_id = uuid.uuid4()
    session_dir = TEMP_DIR / str(session_id)
    session_dir.mkdir(parents=True, exist_ok=True)

    ACTIVE_SESSIONS.add(session_dir)

    max_size_str = await get_config("max_file_size_mb", "50")
    timeout_str = await get_config("download_timeout_seconds", "60")

    try:
        max_mb = int(max_size_str)
        if max_mb <= 0:
            max_mb = 50
    except (ValueError, TypeError):
        max_mb = 50

    try:
        timeout = float(timeout_str)
        if timeout <= 0.0:
            timeout = 60.0
    except (ValueError, TypeError):
        timeout = 60.0

    max_bytes = max_mb * 1024 * 1024

    try:
        if source == "twitter":
            return await _download_twitter(url, session_dir, max_bytes, max_mb, timeout)
        elif source == "generic":
            return await _download_generic(url, session_dir, max_bytes, max_mb, timeout)
        else:
            raise DownloadError(messages.ERROR_UNKNOWN_URL)
    finally:
        ACTIVE_SESSIONS.discard(session_dir)




