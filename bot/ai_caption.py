"""Compatibility shim for bot/ai_caption.py."""
import sys; from bot.modules import ai_caption as _mod; sys.modules[__name__] = _mod

