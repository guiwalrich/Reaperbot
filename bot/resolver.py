"""Compatibility shim for bot/resolver.py."""
import sys; from bot.utils import resolver as _mod; sys.modules[__name__] = _mod

