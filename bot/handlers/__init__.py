"""Compatibility package shim for bot.handlers."""
import sys
from . import handlers as _mod
sys.modules[__name__] = _mod

