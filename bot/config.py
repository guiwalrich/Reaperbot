"""Gerenciamento de configuração via variáveis de ambiente."""
import os
import json
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# --- Caminhos ---
ROOT_DIR = Path(__file__).parent.parent
TEMP_DIR = ROOT_DIR / "temp"
DATA_DIR = ROOT_DIR / "data"
CONFIG_FILE = DATA_DIR / "config.json"

# Garantir que as pastas existam
TEMP_DIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)


def _load_bot_token() -> str:
    """Carrega e valida o token do bot Telegram."""
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise ValueError(
            "BOT_TOKEN não configurado. Defina BOT_TOKEN no arquivo .env"
        )
    return token


def _load_target_chat_id() -> int | None:
    """Carrega o TARGET_CHAT_ID do config.json (prioridade) ou do .env."""
    # Prioridade 1: config.json (definido via /settarget)
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r") as f:
                data = json.load(f)
                if "target_chat_id" in data:
                    return int(data["target_chat_id"])
        except (json.JSONDecodeError, ValueError):
            pass

    # Prioridade 2: variável de ambiente
    raw = os.getenv("TARGET_CHAT_ID", "").strip()
    if raw:
        try:
            return int(raw)
        except ValueError:
            raise ValueError(
                f"TARGET_CHAT_ID inválido: '{raw}'. Deve ser um número inteiro."
            )
    return None


def _load_allowed_user_ids() -> list[int]:
    """Carrega a lista de IDs de usuários autorizados."""
    raw = os.getenv("ALLOWED_USER_IDS", "").strip()
    if not raw:
        return []  # Lista vazia = sem restrição
    try:
        return [int(uid.strip()) for uid in raw.split(",") if uid.strip()]
    except ValueError as e:
        raise ValueError(
            f"ALLOWED_USER_IDS inválido: {e}. Use IDs numéricos separados por vírgula."
        )


def save_target_chat_id(chat_id: int) -> None:
    """Persiste o TARGET_CHAT_ID no config.json (usado pelo /settarget)."""
    data = {}
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r") as f:
                data = json.load(f)
        except json.JSONDecodeError:
            pass
    data["target_chat_id"] = chat_id
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=2)


def get_target_chat_id() -> int | None:
    """Retorna o TARGET_CHAT_ID atual (permite atualização dinâmica)."""
    return _load_target_chat_id()


# --- Constantes exportadas ---
BOT_TOKEN: str = _load_bot_token()
TARGET_CHAT_ID: int | None = _load_target_chat_id()
ALLOWED_USER_IDS: list[int] = _load_allowed_user_ids()

