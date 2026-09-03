"""Compatibility shim for bot/config.py."""
import sys; from bot.core import config as _mod; sys.modules[__name__] = _mod

