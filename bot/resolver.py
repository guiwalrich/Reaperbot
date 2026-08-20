"""Módulo de resolução e classificação de URLs."""
import re
from typing import Literal

MediaSource = Literal["twitter", "generic", "unknown"]

TWITTER_PATTERN = re.compile(r"https?://(www\.)?(twitter\.com|x\.com)/\S+", re.IGNORECASE)


def classify_url(url: str) -> MediaSource:
    """Classifica a URL fornecida como 'twitter', 'generic' ou 'unknown'."""
    if not url or not isinstance(url, str):
        return "unknown"

    url_clean = url.strip()

    if TWITTER_PATTERN.search(url_clean):
        return "twitter"

    if url_clean.lower().startswith(("http://", "https://")):
        return "generic"

    return "unknown"
