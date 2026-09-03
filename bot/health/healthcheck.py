"""Script de Healthcheck rigoroso baseado na existência e atualização contínua do Heartbeat."""
import sys
import time
from pathlib import Path
from bot.core.config import DATA_DIR

HEARTBEAT_FILE = DATA_DIR / ".heartbeat"
MAX_HEARTBEAT_AGE_SECONDS = 60.0


def check_health() -> int:
    """
    Verifica se o processo do bot está ativo e atualizando o heartbeat.
    Se o arquivo não existir ou estiver estagnado (>60s), retorna 1 (UNHEALTHY).
    """
    if not HEARTBEAT_FILE.exists():
        print("Healthcheck FAILED: Arquivo de heartbeat não encontrado (processo não inicializado ou falhou no startup)", file=sys.stderr)
        return 1

    try:
        mtime = HEARTBEAT_FILE.stat().st_mtime
        age = time.time() - mtime
        if age > MAX_HEARTBEAT_AGE_SECONDS:
            print(f"Healthcheck FAILED: Heartbeat estagnado ({age:.1f}s > {MAX_HEARTBEAT_AGE_SECONDS}s)", file=sys.stderr)
            return 1

        return 0
    except Exception as e:
        print(f"Healthcheck FAILED: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(check_health())
