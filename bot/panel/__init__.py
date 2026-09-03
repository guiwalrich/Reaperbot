"""Compatibility package shim for bot.panel."""
import sys
from . import panel as _mod
sys.modules[__name__] = _mod

