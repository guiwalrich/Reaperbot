"""Compatibility shim for bot/panel.py."""
import sys; from bot.panel import panel as _mod; sys.modules[__name__] = _mod

