"""Inicialização e configuração do HotReaper VIP v3.0 com pool HTTPX resiliente."""
import asyncio
import logging
import shutil
import time
from pathlib import Path
from telegram import Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters
from telegram.request import HTTPXRequest

from bot.core.config import BOT_TOKEN, OWNER_ID, TEMP_DIR, DATA_DIR
from bot.core.database import init_db, reconcile_vault_integrity
from bot.handlers.handlers import (
    help_handler,
    message_handler,
    settarget_handler,
    setwelcome_handler,
    start_handler,
)
from bot.modules.downloader import ACTIVE_SESSIONS
from bot.panel.panel import panel_handler, panel_callback_handler
from bot.modules.scheduler import supervised_schedule_worker

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

HEARTBEAT_FILE = DATA_DIR / ".heartbeat"


def _cleanup_temp_on_startup() -> None:
    """Limpa a pasta temp de sessões residuais anteriores ao iniciar."""
    try:
        if TEMP_DIR.exists():
            for item in TEMP_DIR.iterdir():
                if item.is_dir():
                    shutil.rmtree(item, ignore_errors=True)
                elif item.is_file() and item.name != ".gitkeep":
                    item.unlink(missing_ok=True)
            logger.info("🧹 Pasta temp limpa com sucesso no startup.")
    except Exception as e:
        logger.warning(f"Aviso ao limpar pasta temp: {e}")


def _touch_heartbeat() -> None:
    """Cria ou atualiza o arquivo de heartbeat com o timestamp atual."""
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        HEARTBEAT_FILE.write_text(str(time.time()), encoding="utf-8")
    except Exception as e:
        logger.warning(f"Aviso ao gravar heartbeat: {e}")


async def _heartbeat_worker() -> None:
    """Atualiza o arquivo de heartbeat periodicamente enquanto o loop do bot estiver vivo."""
    while True:
        _touch_heartbeat()
        await asyncio.sleep(15)


async def _periodic_temp_cleanup_worker() -> None:
    """Worker em background que roda a cada 6 horas para limpar lixo temporário antigo (>1h)."""
    while True:
        try:
            await asyncio.sleep(6 * 3600)
            cleaned_mb = 0.0
            now = time.time()
            if TEMP_DIR.exists():
                for p in list(TEMP_DIR.iterdir()):
                    if p.is_file() and p.name != ".gitkeep":
                        if now - p.stat().st_mtime > 3600:
                            cleaned_mb += p.stat().st_size / (1024 * 1024)
                            p.unlink(missing_ok=True)
                    elif p.is_dir():
                        if p not in ACTIVE_SESSIONS:
                            if now - p.stat().st_mtime > 3600:
                                for sp in p.rglob("*"):
                                    if sp.is_file() and sp.name != ".gitkeep":
                                        cleaned_mb += sp.stat().st_size / (1024 * 1024)
                                shutil.rmtree(p, ignore_errors=True)
            if cleaned_mb > 0:
                logger.info(f"🧹 Coletor Automático: {cleaned_mb:.2f} MB de arquivos temporários limpos.")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning(f"Aviso no coletor periódico de lixo temporário: {e}")


async def post_init(application: Application) -> None:
    """Callback executado logo após a inicialização do event loop do Telegram."""
    await init_db()
    asyncio.create_task(_heartbeat_worker())
    asyncio.create_task(_periodic_temp_cleanup_worker())
    await reconcile_vault_integrity()
    asyncio.create_task(supervised_schedule_worker(application.bot))
    logger.info("📦 Banco de dados inicializado, Coletor 6h e Heartbeat contínuo ativos.")


async def channel_button_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Responde aos cliques de botões públicos no canal (ex: sininho de notificação)."""
    query = update.callback_query
    if not query:
        return
    if query.data == "btn_mute_tip":
        try:
            await query.answer(
                "🔔 Amor, para não perder nenhuma novidade quente:\n\n"
                "1. Toque nos 3 pontinhos (⋮) no topo direito deste canal\n"
                "2. Selecione 'Desativar silêncio' / 'Ativar som' 🔥",
                show_alert=True,
            )
        except Exception:
            pass


def main() -> None:
    """Ponto de entrada principal do bot com HTTPXRequest de alta tolerância a latência."""
    if not BOT_TOKEN:
        logger.error("❌ BOT_TOKEN não configurado no .env! O bot não pode ser iniciado.")
        return

    if not OWNER_ID or OWNER_ID <= 0:
        logger.error("❌ OWNER_ID não configurado ou inválido no .env! O bot não pode ser iniciado.")
        return

    _cleanup_temp_on_startup()
    _touch_heartbeat()

    # Configuração de requisições de rede com timeouts estendidos para envio de vídeos pesados
    request = HTTPXRequest(
        connection_pool_size=16,
        connect_timeout=60.0,
        read_timeout=300.0,
        write_timeout=300.0,
        media_write_timeout=300.0,
        pool_timeout=60.0,
    )

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .request(request)
        .concurrent_updates(True)
        .post_init(post_init)
        .build()
    )

    # Registrar handlers de comandos
    application.add_handler(CommandHandler("start", start_handler))
    application.add_handler(CommandHandler("help", help_handler))
    application.add_handler(CommandHandler("settarget", settarget_handler))
    application.add_handler(MessageHandler(filters.ChatType.CHANNEL & filters.Regex(r"^/settarget"), settarget_handler))
    application.add_handler(CommandHandler("setwelcome", setwelcome_handler))
    application.add_handler(CommandHandler("painel", panel_handler))

    # Registrar handler de botões interativos públicos (ex: botão de notificação do canal)
    application.add_handler(CallbackQueryHandler(channel_button_callback_handler, pattern=r"^btn_mute_tip$"))

    # Registrar handler de cliques em botões do painel administrativo
    application.add_handler(CallbackQueryHandler(panel_callback_handler))

    # Registrar handler de mensagens com links
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler)
    )

    logger.info("🚀 HotReaper VIP v3.0 iniciado com sucesso. Aguardando links...")
    application.run_polling(allowed_updates=["message", "channel_post", "callback_query"])

