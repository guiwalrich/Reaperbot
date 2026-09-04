"""Módulo de Webhook Server assíncrono (aiohttp) para receber alertas em tempo real do RavenBot."""
import logging
from typing import Any
from aiohttp import web
from telegram import Bot

from bot.core.config import OWNER_ID

logger = logging.getLogger(__name__)


def create_webhook_app(bot: Bot) -> web.Application:
    """Cria e configura a aplicação aiohttp com as rotas de webhook do RavenBot."""
    app = web.Application()

    async def _safe_send_owner(text: str) -> None:
        """Envia mensagem ao dono do bot de forma resiliente."""
        if not OWNER_ID or OWNER_ID <= 0:
            logger.warning("Webhook disparado mas OWNER_ID não está configurado.")
            return
        try:
            await bot.send_message(
                chat_id=OWNER_ID,
                text=text,
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.error(f"Erro ao entregar notificação de webhook ao OWNER ({e})")

    # 1. Gateway PIX Instável
    async def handle_gateway_unstable(request: web.Request) -> web.Response:
        logger.warning("Recebido webhook: Gateway PIX Instável")
        try:
            data = await request.json() if request.can_read_body else {}
        except Exception:
            data = {}

        msg = (
            "⚠️ *ALERTA CRÍTICO: Gateway PIX Instável!*\n\n"
            "O RavenBot detectou que a taxa de erro do seu gateway passou de 50% nos últimos 10 minutos!\n\n"
            "👉 *Ação Imediata:* Entre no painel do RavenBot e alterne para um gateway reserva para não perder vendas de PIX."
        )
        await _safe_send_owner(msg)
        return web.json_response({"status": "ok", "event": "gateway_unstable"})

    # 2. Bot Offline / Caiu
    async def handle_bot_down(request: web.Request) -> web.Response:
        logger.warning("Recebido webhook: Bot Offline / Caiu")
        try:
            data = await request.json() if request.can_read_body else {}
        except Exception:
            data = {}

        msg = (
            "🚨 *ALERTA: Bot do RavenBot Offline/Instável!*\n\n"
            "O RavenBot reportou que o seu bot de vendas de atendimento ou entrega está instável ou caiu.\n\n"
            "👉 *Ação:* Verifique se o token do bot está válido no painel do RavenBot."
        )
        await _safe_send_owner(msg)
        return web.json_response({"status": "ok", "event": "bot_down"})

    # 3. PIX Aprovado / Venda Concluída
    async def handle_pix_approved(request: web.Request) -> web.Response:
        logger.info("Recebido webhook: PIX Aprovado")
        try:
            data = await request.json() if request.can_read_body else {}
        except Exception:
            data = {}

        valor = data.get("valor", data.get("amount", data.get("preco", "9,99")))
        cliente = data.get("nome", data.get("client_name", data.get("customer", data.get("usuario", "Cliente"))))
        plano = data.get("plano", data.get("plan_name", data.get("produto", "VIP")))

        msg = (
            "💰 *PIX APROVADO! VENDA CONFIRMADA!*\n\n"
            f"👤 *Cliente:* `{cliente}`\n"
            f"💵 *Valor:* `R$ {valor}`\n"
            f"📦 *Plano:* `{plano}`\n\n"
            "🚀 _Venda confirmada com sucesso pelo RavenBot!_"
        )
        await _safe_send_owner(msg)
        return web.json_response({"status": "ok", "event": "pix_approved"})

    # 4. Erro na Geração do PIX
    async def handle_pix_error(request: web.Request) -> web.Response:
        logger.warning("Recebido webhook: Erro na Geração do PIX")
        try:
            data = await request.json() if request.can_read_body else {}
        except Exception:
            data = {}

        msg = (
            "⚠️ *Aviso: Erro na Geração do PIX!*\n\n"
            "Um cliente tentou gerar uma cobrança no RavenBot mas o gateway retornou erro."
        )
        await _safe_send_owner(msg)
        return web.json_response({"status": "ok", "event": "pix_error"})

    # 5. Health Check
    async def handle_health(request: web.Request) -> web.Response:
        return web.json_response({"status": "healthy", "service": "hotreaper_webhooks"})

    app.router.add_post("/webhook/gateway", handle_gateway_unstable)
    app.router.add_post("/webhook/bot_down", handle_bot_down)
    app.router.add_post("/webhook/pix_pago", handle_pix_approved)
    app.router.add_post("/webhook/pix_erro", handle_pix_error)
    app.router.add_get("/health", handle_health)

    return app


async def start_webhook_server(bot: Bot, host: str = "0.0.0.0", port: int = 8088) -> web.AppRunner:
    """Inicia o servidor aiohttp em background dentro do event loop do bot."""
    app = create_webhook_app(bot)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    logger.info(f"🌐 Servidor de Webhooks do RavenBot ativo em http://{host}:{port}")
    return runner
