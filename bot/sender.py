"""Compatibility shim for bot/sender.py."""
import sys; from bot.modules import sender as _mod; sys.modules[__name__] = _mod

