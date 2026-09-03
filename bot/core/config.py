"""Gerenciamento de configuração via variáveis de ambiente."""
import datetime
import os
import zoneinfo
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# --- Fuso Horário Oficial (Brasília / America/Sao_Paulo) ---
BRAZIL_TZ = zoneinfo.ZoneInfo("America/Sao_Paulo")


def get_brazil_now() -> datetime.datetime:
    """Retorna datetime atual sempre no fuso horário oficial de Brasília (naive para SQLite)."""
    return datetime.datetime.now(BRAZIL_TZ).replace(tzinfo=None)


# --- Versão do Bot ---
BOT_VERSION = "3.0.0"

# --- Caminhos ---
ROOT_DIR = Path(__file__).parent.parent.parent
TEMP_DIR = ROOT_DIR / "temp"
DATA_DIR = ROOT_DIR / "data"
VAULT_DIR = DATA_DIR / "vault"

# Garantir que as pastas existam
TEMP_DIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)
VAULT_DIR.mkdir(exist_ok=True)


def _load_bot_token() -> str:
    """Carrega o token do bot Telegram."""
    return os.getenv("BOT_TOKEN", "").strip()


def _load_owner_id() -> int:
    """Carrega e valida o ID do dono único do bot (Fail-closed)."""
    raw = os.getenv("OWNER_ID", "").strip()
    if not raw:
        return 0
    try:
        val = int(raw)
        return val if val > 0 else 0
    except ValueError:
        return 0


def _load_groq_api_key() -> str:
    """Carrega a chave de API da Groq Cloud."""
    return os.getenv("GROQ_API_KEY", "").strip()


# --- Constantes exportadas ---
BOT_TOKEN: str = _load_bot_token()
OWNER_ID: int = _load_owner_id()
GROQ_API_KEY: str = _load_groq_api_key()
