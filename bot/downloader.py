"""Compatibility shim for bot/downloader.py."""
import sys; from bot.modules import downloader as _mod; sys.modules[__name__] = _mod

