"""Compatibility shim for bot/handlers.py."""
import sys; from bot.handlers import handlers as _mod; sys.modules[__name__] = _mod

