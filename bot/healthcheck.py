"""Compatibility shim for bot.healthcheck."""
import sys
import bot.health.healthcheck as _mod
sys.modules[__name__] = _mod
