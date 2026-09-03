"""HotReaper VIP v3.0 - Telegram Bot for Universal Media Downloads with AI Captions."""

# Public API re-exports for convenient access
from bot.core.config import BOT_TOKEN, OWNER_ID, BOT_VERSION, GROQ_API_KEY
from bot.core.database import init_db, DB_PATH
from bot.utils.messages import START, HELP
from bot.modules.downloader import download, DownloadError
from bot.modules.ai_caption import generate_ai_caption

__version__ = "3.0.0"
__all__ = [
    # Configuration
    "BOT_TOKEN",
    "OWNER_ID",
    "BOT_VERSION",
    "GROQ_API_KEY",
    # Database
    "init_db",
    "DB_PATH",
    # Messages
    "START",
    "HELP",
    # Core Features
    "download",
    "DownloadError",
    "generate_ai_caption",
    # Version
    "__version__",
]

