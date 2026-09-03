"""Painel de Controle Administrativo com Acervo, Gestão de Canais, Cadência e Groq IA."""
import datetime
import logging
import shutil
from pathlib import Path
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from bot.utils import messages
from bot.modules import downloader
from bot.core.config import OWNER_ID, BOT_VERSION, TEMP_DIR, DATA_DIR, VAULT_DIR
from bot.modules.ai_caption import generate_ai_caption
from bot.core.database import (
    DB_PATH,
    get_all_config,
    get_config,
    set_config,
    get_download_stats,
    get_recent_downloads,
    get_channel,
    get_all_channels,
    register_channel,
    set_channel_dispatch_mode,
    set_channel_schedule_times,
    get_vault_stats,
)
from bot.modules.scheduler import dispatch_next_from_vault, get_dispatch_lock

logger = logging.getLogger(__name__)


def _is_owner(user_id: int) -> bool:
    """Verifica se o usuário é o dono exclusivo do bot (Fail-closed estrito)."""
    if not OWNER_ID or OWNER_ID <= 0:
        return False
    return user_id == OWNER_ID


def _get_temp_stats() -> tuple[float, int]:
    """Retorna (tamanho_mb, total_arquivos) da pasta temp."""
    total_size = 0
    file_count = 0
    if TEMP_DIR.exists():
        for p in TEMP_DIR.rglob("*"):
            if p.is_file() and p.name != ".gitkeep":
                total_size += p.stat().st_size
                file_count += 1
    return total_size / (1024 * 1024), file_count


def _get_db_size_kb() -> float:
    """Retorna tamanho do arquivo do banco em KB."""
    if DB_PATH.exists():
        return DB_PATH.stat().st_size / 1024
    return 0.0


async def _safe_answer_query(query, text: str | None = None, show_alert: bool = False) -> None:
    """Responde à callback query de forma segura, evitando quebras por timeout ou double answer."""
    try:
        if text:
            await query.answer(text=text, show_alert=show_alert)
        else:
            await query.answer()
    except TelegramError as e:
        logger.debug(f"Aviso ao responder callback query: {e}")
    except Exception as e:
        logger.warning(f"Erro inesperado no answer query: {e}")


async def _safe_edit_message(query, text: str, reply_markup: InlineKeyboardMarkup) -> None:
    """Edita a mensagem do menu de forma segura contra erros de rede ou conteúdo idêntico."""
    try:
        if query.message:
            await query.message.edit_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    except TelegramError as e:
        logger.debug(f"Aviso ao editar mensagem do painel: {e}")
    except Exception as e:
        logger.warning(f"Erro inesperado ao editar painel: {e}")


# ─── Menus e Teclados ──────────────────────────────────────────

def _format_dispatch_schedule_info(channel: dict | None) -> tuple[str, str]:
    """Calcula dinamicamente a data/hora do último disparo e a previsão exata do próximo disparo em horário de Brasília."""
    if not channel:
        return "Nenhum canal ativo", "Aguardando canal"

    from bot.core.config import get_brazil_now
    now = get_brazil_now()
    last_disp = channel.get("last_dispatched_at")
    mode = channel.get("dispatch_mode", "instant")
    interval_h = channel.get("interval_hours", 2) or 2
    schedule_times = channel.get("schedule_times", "10:00,14:00,18:00,22:00") or ""

    # 1. Formata o Último Disparo
    last_dt = None
    if not last_disp:
        last_str = "Nenhum registro ainda"
    else:
        try:
            if isinstance(last_disp, str):
                last_dt = datetime.datetime.fromisoformat(last_disp)
            else:
                last_dt = last_disp
            if last_dt.date() == now.date():
                last_str = f"Hoje às {last_dt.strftime('%H:%M')}"
            elif (now.date() - last_dt.date()).days == 1:
                last_str = f"Ontem às {last_dt.strftime('%H:%M')}"
            else:
                last_str = last_dt.strftime("%d/%m às %H:%M")
        except Exception:
            last_str = str(last_disp)

    # 2. Previsão do Próximo Disparo de acordo com a configuração
    if mode == "interval":
        if not last_dt:
            next_str = "⚡ Imediato (ao iniciar envio)"
        else:
            next_dt = last_dt + datetime.timedelta(hours=interval_h)
            if next_dt <= now:
                next_str = "⚡ Imediato (horário atingido)"
            else:
                diff_sec = int((next_dt - now).total_seconds())
                diff_min = diff_sec // 60
                h_left = diff_min // 60
                m_left = diff_min % 60
                time_tag = f"em ~{h_left}h {m_left}m" if h_left > 0 else f"em ~{m_left}m"
                day_tag = "Hoje" if next_dt.date() == now.date() else "Amanhã"
                next_str = f"{day_tag} às {next_dt.strftime('%H:%M')} ({time_tag})"

    elif mode == "scheduled":
        times = sorted([t.strip() for t in schedule_times.split(",") if t.strip()])
        cur_hm = now.strftime("%H:%M")
        upcoming = [t for t in times if t > cur_hm]
        if upcoming:
            next_str = f"Hoje às {upcoming[0]}"
        elif times:
            next_str = f"Amanhã às {times[0]}"
        else:
            next_str = "Não configurado"

    elif mode == "instant":
        next_str = "⚡ Imediato (ao enviar novo link)"
    elif mode == "manual":
        next_str = "🖐 Sob demanda (manual via botão)"
    else:
        next_str = mode

    return last_str, next_str


def _main_menu_keyboard() -> InlineKeyboardMarkup:
    """Gera o teclado do menu principal do painel."""
    keyboard = [
        [
            InlineKeyboardButton("📦 Acervo & Disparos", callback_data="panel:vault"),
            InlineKeyboardButton("🎯 Canais & Destinos", callback_data="panel:channels"),
        ],
        [
            InlineKeyboardButton("🤖 IA Groq (Legendas)", callback_data="panel:ai"),
            InlineKeyboardButton("⚙️ Configurações", callback_data="panel:config"),
        ],
        [
            InlineKeyboardButton("📊 Estatísticas", callback_data="panel:stats"),
            InlineKeyboardButton("📋 Histórico", callback_data="panel:history"),
        ],
        [
            InlineKeyboardButton("🔧 Sistema & Cache", callback_data="panel:system"),
            InlineKeyboardButton("❌ Fechar Painel", callback_data="panel:close"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


async def _main_menu_content() -> tuple[str, InlineKeyboardMarkup]:
    """Gera o texto e o teclado do menu principal do painel com status dinâmico em tempo real."""
    target_chat = await get_config("target_chat_id", "") or ""
    channel = await get_channel(target_chat) if target_chat else None
    chan_title = channel.get("title", target_chat) if channel else (target_chat or "Não configurado")
    mode = channel.get("dispatch_mode", "instant") if channel else "instant"
    interval_h = channel.get("interval_hours", 2) if channel else 2
    schedule_times = channel.get("schedule_times", "10:00,14:00,18:00,22:00") if channel else ""

    mode_labels = {
        "interval": f"⏱️ A cada {interval_h}h (Ativo)",
        "instant": "⚡ Imediato (ao baixar)",
        "scheduled": f"⏰ Agendado ({schedule_times})",
        "manual": "🖐 Manual (sob clique)",
    }
    mode_label = mode_labels.get(mode, mode)
    last_disp_label, next_disp_label = _format_dispatch_schedule_info(channel)

    text = (
        f"🎛️ *PAINEL DE CONTROLE — HotReaper VIP v3.0*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🎯 *Canal Ativo:* `{chan_title}`\n"
        f"⚙️ *Modo de Disparo:* `{mode_label}`\n"
        f"🕒 *Último Post:* `{last_disp_label}`\n"
        f"⏳ *Próximo Post:* `{next_disp_label}`\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Escolha uma seção abaixo para gerenciar:"
    )
    return text, _main_menu_keyboard()


async def _channels_menu_keyboard() -> tuple[str, InlineKeyboardMarkup]:
    """Gera o menu de gerenciamento e seleção rápida de canais destino."""
    active_target = await get_config("target_chat_id", "") or ""
    all_channels = await get_all_channels()

    lines = [
        "🎯 *GESTÃO DE CANAIS DESTINO*",
        "━━━━━━━━━━━━━━━━━━━━",
    ]
    if active_target:
        active_ch = await get_channel(active_target)
        active_name = active_ch.get("title", active_target) if active_ch else active_target
        lines.append(f"⭐ *Canal Ativo:* `{active_name}` (`{active_target}`)\n")
    else:
        lines.append("• *Canal Ativo:* `Nenhum canal ativo`\n")

    lines.append("📋 *Canais Cadastrados:*")
    if not all_channels:
        lines.append("  _Nenhum canal cadastrado ainda._\n")
    else:
        for ch in all_channels:
            cid = ch["channel_id"]
            title = ch.get("title") or "Canal VIP"
            mode = ch.get("dispatch_mode", "instant").upper()
            is_cur = " ⭐ (ATIVO)" if cid == active_target else ""
            lines.append(f"  • *{title}* (`{cid}`) — `{mode}`{is_cur}")
        lines.append("")

    lines.append(
        "➕ *Para vincular um novo canal:*\n"
        "1. Adicione este bot ao seu canal como **Administrador** (com permissão de postar mensagens).\n"
        "2. Envie no chat privado: `/settarget @seucanal` ou `/settarget -100xxxxxxxxxx`"
    )

    text = "\n".join(lines)

    keyboard = []
    # Botões para alternar canal ativo com 1 clique
    for ch in all_channels:
        cid = ch["channel_id"]
        title = ch.get("title") or cid
        is_cur = "⭐ " if cid == active_target else ""
        keyboard.append([
            InlineKeyboardButton(f"{is_cur}Selecionar: {title[:20]}", callback_data=f"panel:set_active_chan:{cid}")
        ])

    keyboard.append([
        InlineKeyboardButton("🎯 Usar este chat privado como Destino", callback_data="panel:set_dest_current"),
    ])
    keyboard.append([
        InlineKeyboardButton("🔙 Menu Principal", callback_data="panel:main"),
    ])

    return text, InlineKeyboardMarkup(keyboard)


async def _vault_menu_keyboard() -> tuple[str, InlineKeyboardMarkup]:
    """Gera a visualização completa do Acervo de Mídias e controle de disparos."""
    target_chat = await get_config("target_chat_id", "") or "Não configurado"
    channel = await get_channel(target_chat) if target_chat else None
    chan_title = channel.get("title", target_chat) if channel else target_chat
    mode = channel.get("dispatch_mode", "instant") if channel else "instant"
    consecutive_v = channel.get("consecutive_videos_count", 0) if channel else 0
    schedule_times = channel.get("schedule_times", "10:00,14:00,18:00,22:00") if channel else ""

    stats = await get_vault_stats(target_chat)
    interval_h = channel.get("interval_hours", 2) if channel else 2
    mode_labels = {
        "interval": f"⏱️ A CADA {interval_h}H (Ativo)",
        "instant": "⚡ IMEDIATO (Baixa e dispara)",
        "scheduled": f"⏰ AGENDADO ({schedule_times})",
        "manual": "🖐 MANUAL (Apenas sob clique)",
    }
    mode_label = mode_labels.get(mode, mode)

    next_cadence = "📸 Pack de até 3 Fotos" if consecutive_v >= 2 else f"🎬 Vídeo ({consecutive_v + 1}/2)"
    last_disp_label, next_disp_label = _format_dispatch_schedule_info(channel)

    text = (
        f"📦 *ACERVO DE MÍDIAS & DISPAROS*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🎯 *Destino Ativo:* `{chan_title}`\n"
        f"📊 *Na Fila:* 🎬 `{stats['pending_videos']}` vídeos  •  📸 `{stats['pending_photos']}` fotos\n"
        f"💾 *Tamanho:* `{stats['total_mb']} MB`  •  🔄 *Próximo:* `{next_cadence}`\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"⚙️ *Modo de Disparo:* `{mode_label}`\n"
        f"🕒 *Último Post:* `{last_disp_label}`\n"
        f"⏳ *Próximo Post:* `{next_disp_label}`\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"_Cadência: A cada 2 vídeos enviados, o próximo disparo solta até 3 fotos!_"
    )

    keyboard = [
        [
            InlineKeyboardButton("🚀 Disparar Próximo Agora", callback_data="panel:dispatch_now"),
            InlineKeyboardButton("📢 Enviar Boas-Vindas", callback_data="panel:send_welcome_now"),
        ],
        [
            InlineKeyboardButton("⏱️ Modo Intervalo", callback_data="panel:interval_menu"),
            InlineKeyboardButton("⚡ Modo Imediato", callback_data="panel:set_mode:instant"),
        ],
        [
            InlineKeyboardButton("🖐 Modo Manual", callback_data="panel:set_mode:manual"),
            InlineKeyboardButton("⏰ Modo Agendado", callback_data="panel:set_mode:scheduled"),
        ],
        [
            InlineKeyboardButton("📝 Ver / Editar Boas-Vindas", callback_data="panel:welcome_menu"),
            InlineKeyboardButton("🎯 Trocar Canal", callback_data="panel:channels"),
        ],
        [
            InlineKeyboardButton("🔙 Menu Principal", callback_data="panel:main"),
        ],
    ]
    return text, InlineKeyboardMarkup(keyboard)


async def _interval_menu_keyboard() -> tuple[str, InlineKeyboardMarkup]:
    """Gera o submenu de configuração do Modo Intervalo Dinâmico."""
    target_chat = await get_config("target_chat_id", "") or "Não configurado"
    channel = await get_channel(target_chat) if target_chat else None
    chan_title = channel.get("title", target_chat) if channel else target_chat
    interval_h = channel.get("interval_hours", 2) if channel else 2
    mode = channel.get("dispatch_mode", "instant") if channel else "instant"
    is_interval_active = mode == "interval"
    last_disp = channel.get("last_dispatched_at") if channel else None
    last_disp_str = last_disp if last_disp else "Nenhum disparo registrado ainda"

    status_str = f"✅ Ativo (A cada {interval_h}h)" if is_interval_active else "⚪ Inativo (Clique abaixo para ativar)"
    last_disp_label, next_disp_label = _format_dispatch_schedule_info(channel)

    text = (
        f"⏱️ *MODO INTERVALO DINÂMICO*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🎯 *Canal Alvo:* `{chan_title}`\n"
        f"📊 *Status:* {status_str}\n"
        f"🕒 *Último Post:* `{last_disp_label}`\n"
        f"⏳ *Próximo Post:* `{next_disp_label}`\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💡 *Como Funciona:*\n"
        f"• Enquanto o seu computador estiver ligado, o bot dispara automaticamente a cada intervalo escolhido.\n"
        f"• Se o PC estava desligado e você acabou de ligar, ele solta a próxima mídia imediatamente nos primeiros minutos!\n\n"
        f"👇 *Escolha o intervalo desejado para ativar:*"
    )

    b1 = "⚡ A cada 1 Hora" + (" (Ativo)" if is_interval_active and interval_h == 1 else "")
    b2 = "🔥 A cada 2 Horas" + (" (Ativo)" if is_interval_active and interval_h == 2 else "")
    b3 = "⏳ A cada 3 Horas" + (" (Ativo)" if is_interval_active and interval_h == 3 else "")
    b4 = "🌙 A cada 4 Horas" + (" (Ativo)" if is_interval_active and interval_h == 4 else "")

    keyboard = [
        [
            InlineKeyboardButton(b1, callback_data="panel:set_interval:1"),
            InlineKeyboardButton(b2, callback_data="panel:set_interval:2"),
        ],
        [
            InlineKeyboardButton(b3, callback_data="panel:set_interval:3"),
            InlineKeyboardButton(b4, callback_data="panel:set_interval:4"),
        ],
        [
            InlineKeyboardButton("🔙 Voltar ao Acervo", callback_data="panel:vault"),
            InlineKeyboardButton("🏠 Menu Principal", callback_data="panel:main"),
        ],
    ]
    return text, InlineKeyboardMarkup(keyboard)


async def _welcome_menu_keyboard() -> tuple[str, InlineKeyboardMarkup]:
    """Gera o menu de visualização e controle da mensagem de boas-vindas."""
    from bot.core.database import is_channel_welcomed
    target_chat = await get_config("target_chat_id", "") or "Não configurado"
    cur_text = await get_config("welcome_message_text", "")
    is_welcomed = await is_channel_welcomed(target_chat) if target_chat else False
    status_label = "✅ Postada e Fixada no Canal" if is_welcomed else "⏳ Pendente (Será postada no 1º envio)"

    text = (
        f"📝 *MENSAGEM DE BOAS-VINDAS & NOTIFICAÇÕES*\n\n"
        f"• *Canal Alvo:* `{target_chat}`\n"
        f"• *Status:* {status_label}\n"
        f"• *Botão Interativo:* `🔔 Ativar Notificações` (Com modal explicativo)\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📋 *Texto Atual Configurado:*\n\n"
        f"{cur_text}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"_Para alterar o texto e atualizar no canal, envie:_ `/setwelcome <seu texto>`"
    )

    keyboard = [
        [
            InlineKeyboardButton("📢 Reenviar & Fixar Agora", callback_data="panel:send_welcome_now"),
            InlineKeyboardButton("🔄 Restaurar Padrão", callback_data="panel:restore_welcome_default"),
        ],
        [
            InlineKeyboardButton("🔙 Voltar ao Acervo", callback_data="panel:vault"),
            InlineKeyboardButton("🏠 Menu Principal", callback_data="panel:main"),
        ],
    ]
    return text, InlineKeyboardMarkup(keyboard)


async def _ai_menu_keyboard() -> tuple[str, InlineKeyboardMarkup]:
    """Gera o menu de configuração do motor de IA Groq Cloud."""
    style = await get_config("ai_caption_style", "picante") or "picante"
    caption_mode = await get_config("caption_mode", "ai") or "ai"

    style_labels = {
        "picante": "🔥 Picante & Safada",
        "sensual": "💋 Sensual & Teasing",
        "conversao": "👑 Conversão VIP Exclusiva",
    }
    cur_style = style_labels.get(style, style)

    text = (
        f"🤖 *MOTOR DE IA GROQ CLOUD (Qwen)*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"⚡ *Status:* `ATIVO & CONECTADO`\n"
        f"💬 *Modo:* `{caption_mode.upper()}`  •  🎭 *Estilo:* `{cur_style}`\n"
        f"📚 *Acervo Reserva:* `40+ Legendas Pré-Prontas`\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"_Legendas calibradas para criadora VIP: 100% brasileiras e até 2 emojis._"
    )

    keyboard = [
        [
            InlineKeyboardButton("🔥 Picante & Safada", callback_data="panel:set_ai_style:picante"),
            InlineKeyboardButton("💋 Sensual & Teasing", callback_data="panel:set_ai_style:sensual"),
        ],
        [
            InlineKeyboardButton("👑 Conversão VIP", callback_data="panel:set_ai_style:conversao"),
            InlineKeyboardButton("🧪 Testar Legenda da IA", callback_data="panel:test_ai_caption"),
        ],
        [
            InlineKeyboardButton("🔙 Menu Principal", callback_data="panel:main"),
        ],
    ]
    return text, InlineKeyboardMarkup(keyboard)


async def _config_menu_keyboard() -> tuple[str, InlineKeyboardMarkup]:
    """Gera o texto e teclado do submenu de configurações."""
    target_chat = await get_config("target_chat_id", "") or "Não configurado"
    channel = await get_channel(target_chat) if target_chat else None
    chan_title = channel.get("title", target_chat) if channel else target_chat
    max_size = await get_config("max_file_size_mb", "50")
    silent_mode = await get_config("silent_mode", "false")
    caption_mode = await get_config("caption_mode", "ai")
    timeout = await get_config("download_timeout_seconds", "60")

    silent_label = "ATIVADO (Silencioso)" if silent_mode.lower() == "true" else "DESATIVADO (Normal)"
    caption_labels = {"ai": "🤖 IA Groq Cloud", "url": "Link Original", "none": "Sem Legenda"}
    caption_label = caption_labels.get(caption_mode, caption_mode)

    text = messages.PANEL_CONFIG_TITLE.format(
        target_chat=chan_title,
        max_size=max_size,
        silent_mode=silent_label,
        caption_mode=caption_label,
        timeout=timeout,
    )

    silent_toggle_btn = "🔔 Desativar Silencioso" if silent_mode.lower() == "true" else "🔇 Ativar Silencioso"

    keyboard = [
        [
            InlineKeyboardButton("🎯 Gerenciar / Trocar Canais", callback_data="panel:channels"),
        ],
        [
            InlineKeyboardButton("📏 10MB", callback_data="panel:set_size:10"),
            InlineKeyboardButton("📏 50MB", callback_data="panel:set_size:50"),
            InlineKeyboardButton("📏 100MB", callback_data="panel:set_size:100"),
        ],
        [
            InlineKeyboardButton(silent_toggle_btn, callback_data="panel:toggle_silent"),
        ],
        [
            InlineKeyboardButton("🔙 Menu Principal", callback_data="panel:main"),
        ],
    ]
    return text, InlineKeyboardMarkup(keyboard)


async def _stats_menu_keyboard() -> tuple[str, InlineKeyboardMarkup]:
    """Gera o texto e teclado do submenu de estatísticas."""
    stats = await get_download_stats()
    total = stats["total_downloads"]
    successes = stats["successful_downloads"]
    rate = (successes / total * 100) if total > 0 else 0.0
    total_mb = stats["total_size_bytes"] / (1024 * 1024)

    by_source_str = "\n".join(f"  • {k.capitalize()}: {v}" for k, v in stats.get("by_source", {}).items()) or "  • Nenhum registro"
    text = messages.PANEL_STATS_TITLE.format(
        total=total,
        successes=successes,
        failures=stats["failed_downloads"],
        rate=rate,
        total_mb=total_mb,
        total_files=stats["total_files"],
        today=stats["today_downloads"],
        week=stats["week_downloads"],
        by_source=by_source_str,
    )

    keyboard = [
        [
            InlineKeyboardButton("🔄 Atualizar", callback_data="panel:stats"),
            InlineKeyboardButton("🔙 Menu Principal", callback_data="panel:main"),
        ]
    ]
    return text, InlineKeyboardMarkup(keyboard)


async def _history_menu_keyboard() -> tuple[str, InlineKeyboardMarkup]:
    """Gera o texto e teclado do submenu de histórico."""
    recent = await get_recent_downloads(limit=5)
    if not recent:
        hist_lines = "Nenhum download registrado ainda."
    else:
        entries = []
        for d in recent:
            st = "✅" if d.get("status") == "SUCCESS" else "❌"
            sz_mb = (d.get("total_size_bytes") or 0) / (1024 * 1024)
            dur = d.get("duration_seconds") or 0.0
            u = d.get("url", "")
            short_url = u[:35] + "..." if len(u) > 35 else u
            entries.append(f"{st} `{short_url}`\n   ↳ {sz_mb:.1f} MB | {dur:.1f}s")
        hist_lines = "\n\n".join(entries)

    text = messages.PANEL_HISTORY_TITLE.format(history_items=hist_lines)
    keyboard = [
        [
            InlineKeyboardButton("🔄 Atualizar", callback_data="panel:history"),
            InlineKeyboardButton("🔙 Menu Principal", callback_data="panel:main"),
        ]
    ]
    return text, InlineKeyboardMarkup(keyboard)


def _system_menu_keyboard() -> tuple[str, InlineKeyboardMarkup]:
    """Gera o texto e teclado do submenu de sistema."""
    temp_mb, temp_files = _get_temp_stats()
    db_kb = _get_db_size_kb()

    text = messages.PANEL_SYSTEM_TITLE.format(
        version=BOT_VERSION,
        temp_size=temp_mb,
        temp_files=temp_files,
        db_size=db_kb,
    )
    keyboard = [
        [
            InlineKeyboardButton("🧹 Limpar Cache Temporário", callback_data="panel:clean_cache"),
        ],
        [
            InlineKeyboardButton("🔄 Atualizar", callback_data="panel:system"),
            InlineKeyboardButton("🔙 Menu Principal", callback_data="panel:main"),
        ],
    ]
    return text, InlineKeyboardMarkup(keyboard)


# ─── Handlers Principais ───────────────────────────────────────

async def panel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Comando /painel: Abre o painel de controle administrativo para o dono."""
    if not update.effective_user or not _is_owner(update.effective_user.id):
        return

    if not update.message:
        return

    text, reply_markup = await _main_menu_content()
    try:
        await update.message.reply_text(
            text,
            reply_markup=reply_markup,
            parse_mode="Markdown",
        )
    except TelegramError as e:
        logger.warning(f"Aviso ao abrir painel: {e}")


async def panel_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Roteia todas as ações de botões do painel administrativo com proteção e resposta única."""
    query = update.callback_query
    if not query:
        return

    user_id = query.from_user.id if getattr(query, "from_user", None) else (update.effective_user.id if update.effective_user else 0)
    if not _is_owner(user_id):
        await _safe_answer_query(query, "⛔ Acesso restrito ao administrador.", show_alert=True)
        return

    data = query.data or ""
    if not data.startswith("panel:"):
        return

    # 1. Fechar Painel
    if data == "panel:close":
        await _safe_answer_query(query)
        try:
            if query.message:
                await query.message.delete()
        except Exception:
            pass
        return

    # 2. Menu Principal
    elif data == "panel:main":
        await _safe_answer_query(query)
        text, kb = await _main_menu_content()
        await _safe_edit_message(query, text, kb)

    # 3. Submenu Canais & Destinos
    elif data == "panel:channels":
        await _safe_answer_query(query)
        text, kb = await _channels_menu_keyboard()
        await _safe_edit_message(query, text, kb)

    # 4. Selecionar Canal Ativo
    elif data.startswith("panel:set_active_chan:"):
        target_cid = data.split(":")[2]
        ch = await get_channel(target_cid)
        ch_title = ch.get("title", target_cid) if ch else target_cid
        await set_config("target_chat_id", target_cid)
        await _safe_answer_query(query, f"✅ Canal ativo alterado para: {ch_title}", show_alert=True)
        text, kb = await _channels_menu_keyboard()
        await _safe_edit_message(query, text, kb)

    # 5. Submenu Acervo & Disparos
    elif data == "panel:vault":
        await _safe_answer_query(query)
        text, kb = await _vault_menu_keyboard()
        await _safe_edit_message(query, text, kb)

    # 6. Disparo Manual do Acervo com Trava Anti-Duplicação e Feedback Imediato
    elif data == "panel:dispatch_now":
        target_chat = await get_config("target_chat_id", "")
        if not target_chat:
            await _safe_answer_query(query, "❌ Nenhum canal configurado.", show_alert=True)
            return

        lock = get_dispatch_lock(target_chat)
        if lock.locked():
            await _safe_answer_query(
                query,
                "⏳ O bot já está gerando a legenda e enviando uma mídia agora!\nPor favor, aguarde alguns segundos.",
                show_alert=True,
            )
            return

        # Notifica o usuário imediatamente para ele ter certeza de que o clique funcionou
        await _safe_answer_query(
            query,
            "🚀 Disparo iniciado! A IA está analisando a mídia e enviando ao canal...",
            show_alert=False,
        )

        res = await dispatch_next_from_vault(context.bot, target_chat)
        if not res.get("success") and res.get("media_type") == "in_progress":
            await _safe_answer_query(query, res.get("message"), show_alert=True)
        else:
            text, kb = await _vault_menu_keyboard()
            await _safe_edit_message(query, text, kb)

    # 6.1 Disparo Manual de Boas-Vindas
    elif data == "panel:send_welcome_now":
        target_chat = await get_config("target_chat_id", "")
        if not target_chat:
            await _safe_answer_query(query, "❌ Nenhum canal configurado.", show_alert=True)
            return

        from bot.modules.scheduler import send_welcome_message
        msg_id = await send_welcome_message(context.bot, target_chat)
        if msg_id:
            await _safe_answer_query(query, "✅ Boas-Vindas enviada e fixada no canal!", show_alert=True)
        else:
            await _safe_answer_query(query, "❌ Falha ao enviar boas-vindas. Verifique se o bot é admin no canal.", show_alert=True)
        text, kb = await _vault_menu_keyboard()
        await _safe_edit_message(query, text, kb)

    # 6.2 Submenu de Boas-Vindas
    elif data == "panel:welcome_menu":
        await _safe_answer_query(query)
        text, kb = await _welcome_menu_keyboard()
        await _safe_edit_message(query, text, kb)

    # 6.3 Restaurar Boas-Vindas Padrão
    elif data == "panel:restore_welcome_default":
        from bot.core.database import DEFAULT_CONFIGS
        target_chat = await get_config("target_chat_id", "")
        def_text = DEFAULT_CONFIGS.get("welcome_message_text", "")
        await set_config("welcome_message_text", def_text)

        if target_chat:
            from bot.modules.scheduler import edit_welcome_message
            await edit_welcome_message(context.bot, target_chat, def_text)

        await _safe_answer_query(query, "✅ Boas-Vindas restaurada para o padrão oficial!", show_alert=True)
        text, kb = await _welcome_menu_keyboard()
        await _safe_edit_message(query, text, kb)

    # 7. Alterar Modo de Disparo do Canal
    elif data.startswith("panel:set_mode:"):
        new_mode = data.split(":")[2]
        target_chat = await get_config("target_chat_id", "")
        if target_chat:
            await set_channel_dispatch_mode(target_chat, new_mode)
            await _safe_answer_query(query, f"✅ Modo de disparo alterado para: {new_mode.upper()}")
        else:
            await _safe_answer_query(query, "❌ Defina um canal primeiro.", show_alert=True)
        text, kb = await _vault_menu_keyboard()
        await _safe_edit_message(query, text, kb)

    # 7.1 Submenu Modo Intervalo
    elif data == "panel:interval_menu":
        await _safe_answer_query(query)
        text, kb = await _interval_menu_keyboard()
        await _safe_edit_message(query, text, kb)

    # 7.2 Definir Horas do Modo Intervalo
    elif data.startswith("panel:set_interval:"):
        hours = int(data.split(":")[2])
        target_chat = await get_config("target_chat_id", "")
        if target_chat:
            from bot.core.database import set_channel_interval_hours
            await set_channel_dispatch_mode(target_chat, "interval")
            await set_channel_interval_hours(target_chat, hours)
            await _safe_answer_query(query, f"✅ Modo Intervalo ativado: A cada {hours}h!", show_alert=True)
        else:
            await _safe_answer_query(query, "❌ Defina um canal primeiro.", show_alert=True)
        text, kb = await _interval_menu_keyboard()
        await _safe_edit_message(query, text, kb)

    # 8. Submenu IA Groq
    elif data == "panel:ai":
        await _safe_answer_query(query)
        text, kb = await _ai_menu_keyboard()
        await _safe_edit_message(query, text, kb)

    # 9. Alterar Estilo de Legenda da IA
    elif data.startswith("panel:set_ai_style:"):
        new_style = data.split(":")[2]
        await set_config("ai_caption_style", new_style)
        await _safe_answer_query(query, f"✅ Estilo de IA alterado para: {new_style.upper()}")
        text, kb = await _ai_menu_keyboard()
        await _safe_edit_message(query, text, kb)

    # 10. Testar Legenda da IA ao vivo
    elif data == "panel:test_ai_caption":
        await _safe_answer_query(query, "🤖 Gerando legenda de teste...")
        style = await get_config("ai_caption_style", "picante") or "picante"
        sample_caption = await generate_ai_caption("Vídeo dançando de lingerie no quarto", media_type="video", style=style)
        if query.message:
            try:
                await query.message.reply_text(
                    f"🧪 *Legenda Gerada pela Groq ({style.upper()}):*\n\n{sample_caption}",
                    parse_mode="Markdown"
                )
            except Exception:
                pass

    # 11. Submenu Configurações
    elif data == "panel:config":
        await _safe_answer_query(query)
        text, kb = await _config_menu_keyboard()
        await _safe_edit_message(query, text, kb)

    # 12. Usar Chat Atual como Destino
    elif data == "panel:set_dest_current":
        chat_id = str(update.effective_chat.id) if update.effective_chat else ""
        chat_title = update.effective_chat.title or "Canal Principal" if update.effective_chat else "Canal Principal"
        if chat_id:
            await set_config("target_chat_id", chat_id)
            await register_channel(chat_id, chat_title, "instant")
            await _safe_answer_query(query, f"✅ Destino definido: {chat_id}")
        else:
            await _safe_answer_query(query, "❌ Erro ao identificar chat.", show_alert=True)
        text, kb = await _channels_menu_keyboard()
        await _safe_edit_message(query, text, kb)

    # 13. Ajustar Limite de Tamanho
    elif data.startswith("panel:set_size:"):
        size_val = data.split(":")[2]
        await set_config("max_file_size_mb", size_val)
        await _safe_answer_query(query, f"✅ Limite definido para {size_val}MB")
        text, kb = await _config_menu_keyboard()
        await _safe_edit_message(query, text, kb)

    # 14. Alternar Modo Silencioso
    elif data == "panel:toggle_silent":
        curr = await get_config("silent_mode", "false")
        new_val = "false" if curr.lower() == "true" else "true"
        await set_config("silent_mode", new_val)
        status_lbl = "ATIVADO" if new_val == "true" else "DESATIVADO"
        await _safe_answer_query(query, f"✅ Modo silencioso {status_lbl}")
        text, kb = await _config_menu_keyboard()
        await _safe_edit_message(query, text, kb)

    # 15. Submenu Estatísticas
    elif data == "panel:stats":
        await _safe_answer_query(query)
        text, kb = await _stats_menu_keyboard()
        await _safe_edit_message(query, text, kb)

    # 16. Submenu Histórico
    elif data == "panel:history":
        await _safe_answer_query(query)
        text, kb = await _history_menu_keyboard()
        await _safe_edit_message(query, text, kb)

    # 17. Submenu Sistema & Cache
    elif data == "panel:system":
        await _safe_answer_query(query)
        text, kb = _system_menu_keyboard()
        await _safe_edit_message(query, text, kb)

    # 18. Limpar Cache Temporário
    elif data == "panel:clean_cache":
        try:
            cleaned_mb = 0.0
            if TEMP_DIR.exists():
                for p in TEMP_DIR.iterdir():
                    if p.is_file() and p.name != ".gitkeep":
                        cleaned_mb += p.stat().st_size / (1024 * 1024)
                        p.unlink(missing_ok=True)
                    elif p.is_dir():
                        if p not in downloader.ACTIVE_SESSIONS:
                            for sp in p.rglob("*"):
                                if sp.is_file() and sp.name != ".gitkeep":
                                    cleaned_mb += sp.stat().st_size / (1024 * 1024)
                            shutil.rmtree(p, ignore_errors=True)

            await _safe_answer_query(query, f"🧹 Limpeza concluída: {cleaned_mb:.2f} MB liberados!")
        except Exception as e:
            logger.error(f"Erro ao limpar cache temporário: {e}")
            await _safe_answer_query(query, "❌ Erro ao limpar cache.", show_alert=True)

        text, kb = _system_menu_keyboard()
        await _safe_edit_message(query, text, kb)

