"""Compatibility shim for bot/scheduler.py."""
import sys; from bot.modules import scheduler as _mod; sys.modules[__name__] = _mod

