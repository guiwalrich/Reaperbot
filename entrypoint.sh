#!/bin/sh
set -e
mkdir -p /app/data /app/temp
chown -R appuser:appuser /app/data /app/temp 2>/dev/null || true
chmod -R 750 /app/data /app/temp 2>/dev/null || true
exec gosu appuser "$@"
