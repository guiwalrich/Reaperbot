"""Módulo de resolução, validação e classificação de URLs com proteção contra SSRF e domínio estrito."""
import asyncio
import ipaddress
import re
import socket
from urllib.parse import urlparse, urlunparse, urljoin
from typing import Literal

MediaSource = Literal["twitter", "generic", "unknown"]

ALLOWED_TWITTER_HOSTS = {"twitter.com", "www.twitter.com", "x.com", "www.x.com"}


def _is_ip_private_or_restricted(ip_str: str) -> bool:
    """Avalia se um IP é privado, loopback, link-local, multicast ou reservado."""
    try:
        ip = ipaddress.ip_address(ip_str)
        return (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        )
    except ValueError:
        return False


def resolve_redirect_url(base_url: str, location: str) -> str:
    """Resolve corretamente URLs relativas ou absolutas em cabeçalhos de redirecionamento."""
    return urljoin(base_url, location)


def normalize_media_url(url: str) -> str:
    """
    Normaliza subdomínios de idioma (ex: br., pt., es., fr., de., it.) e mobile (ex: m., mobile.)
    para o domínio canônico (ex: www.) ativando os extratores oficiais de plataformas de vídeo.
    """
    if not url or not isinstance(url, str):
        return url

    clean_url = url.split("#")[0].strip()
    try:
        parsed = urlparse(clean_url)
        hostname = (parsed.hostname or "").lower()
        parts = hostname.split(".")
        if len(parts) >= 3:
            if parts[0] in ["br", "pt", "es", "fr", "de", "it", "ja", "ru", "en", "m", "mobile"]:
                parts[0] = "www"
                new_netloc = ".".join(parts)
                if parsed.port:
                    new_netloc = f"{new_netloc}:{parsed.port}"
                return urlunparse(parsed._replace(netloc=new_netloc))
    except Exception:
        pass
    return clean_url


async def is_safe_url(url: str) -> bool:
    """
    Verifica de forma assíncrona se a URL é segura contra ataques de SSRF.
    Resolve o DNS no event loop e bloqueia hosts restritos, IPs privados e metadados de cloud.
    """
    if not url or not isinstance(url, str):
        return False

    try:
        parsed = urlparse(url.strip())
        if parsed.scheme not in ("http", "https"):
            return False

        hostname = parsed.hostname
        if not hostname:
            return False

        hostname_lower = hostname.lower()

        # Bloqueia hostnames locais óbvios e endpoints de metadados de cloud
        if hostname_lower in ("localhost", "metadata.google.internal", "instance-data"):
            return False

        # Se o hostname for um IP literal restrito
        if _is_ip_private_or_restricted(hostname_lower):
            return False

        loop = asyncio.get_running_loop()
        try:
            addr_infos = await loop.getaddrinfo(hostname, None)
            for family, _, _, _, sockaddr in addr_infos:
                ip_str = sockaddr[0]
                if _is_ip_private_or_restricted(ip_str):
                    return False
        except socket.gaierror:
            # Se a resolução local falhar (ex: censura de DNS de provedores locais contra sites adultos),
            # permite se for um formato de domínio público válido com TLD
            if re.match(r"^[a-zA-Z0-9][-a-zA-Z0-9]*(\.[a-zA-Z0-9][-a-zA-Z0-9]*)*\.[a-zA-Z]{2,}$", hostname_lower):
                return True
            return False

        return True
    except Exception:
        return False


def is_safe_url_sync(url: str) -> bool:
    """Validação síncrona preliminar de esquema, hostname e IP literal."""
    if not url or not isinstance(url, str):
        return False
    try:
        parsed = urlparse(url.strip())
        if parsed.scheme not in ("http", "https"):
            return False
        hostname = (parsed.hostname or "").lower()
        if not hostname or hostname in ("localhost", "metadata.google.internal", "instance-data"):
            return False
        if _is_ip_private_or_restricted(hostname):
            return False
        return True
    except Exception:
        return False


def classify_url(url: str) -> MediaSource:
    """
    Classifica a URL como 'twitter', 'generic' ou 'unknown'.
    Garante correspondência exata de domínio para Twitter/X (evita twitter.com.evil.com).
    """
    if not url or not isinstance(url, str):
        return "unknown"

    url_clean = url.strip()

    if not is_safe_url_sync(url_clean):
        return "unknown"

    try:
        parsed = urlparse(url_clean)
        hostname = (parsed.hostname or "").lower()

        # Validação estrita de domínio do Twitter/X
        if hostname in ALLOWED_TWITTER_HOSTS and parsed.path and len(parsed.path) > 1:
            return "twitter"

        if url_clean.lower().startswith(("http://", "https://")):
            return "generic"
    except Exception:
        return "unknown"

    return "unknown"

