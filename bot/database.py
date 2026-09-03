"""Compatibility shim for bot/database.py."""
import sys; from bot.core import database as _mod; sys.modules[__name__] = _mod

