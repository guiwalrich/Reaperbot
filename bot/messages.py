"""Compatibility shim for bot/messages.py."""
import sys; from bot.utils import messages as _mod; sys.modules[__name__] = _mod

