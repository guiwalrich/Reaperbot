"""Mensagens centralizadas do HotReaper Bot v3.0."""

# ─── Boas-vindas e Ajuda ───────────────────────────────────────
START = (
    "🔥 *HotReaper Bot v3.0*\n\n"
    "Sistema de download e despacho sob demanda.\n\n"
    "📎 *Como usar:*\n"
    "Envie qualquer link de mídia (Twitter/X ou URL direta) para baixar e enviar ao canal configurado.\n\n"
    "⚙️ *Comandos:*\n"
    "• /painel — Abrir o Painel de Controle\n"
    "• /settarget — Definir chat atual como destino\n"
    "• /help — Instruções de uso"
)

HELP = (
    "📖 *HotReaper — Instruções de Uso*\n\n"
    "*Download sob demanda:*\n"
    "Basta enviar um link com foto ou vídeo neste chat. O bot faz o download e envia automaticamente ao grupo/canal destino.\n\n"
    "*Links suportados:*\n"
    "• Twitter / X (posts com vídeo ou imagem)\n"
    "• URLs diretas de mídia (.mp4, .jpg, .png, .gif, .webm)\n"
    "• Diversos sites compatíveis com yt-dlp\n\n"
    "*Comandos principais:*\n"
    "• `/painel` — Acessa o painel de configurações, histórico e estatísticas\n"
    "• `/settarget` — Use dentro do canal/grupo para definir como destino\n"
    "• `/help` — Exibe esta mensagem de ajuda"
)

# ─── Grupo destino ─────────────────────────────────────────────
TARGET_SET = (
    "✅ *Destino configurado com sucesso!*\n\n"
    "As mídias baixadas serão enviadas para este chat a partir de agora."
)

TARGET_NOT_SET = (
    "❌ *Nenhum grupo destino configurado.*\n\n"
    "Use o comando `/settarget` dentro do grupo/canal ou configure pelo `/painel`."
)

# ─── Feedback de download ───────────────────────────────────────
DOWNLOADING = "⏳ *Baixando mídia...*"
SENT_SUCCESS = "✅ *Mídia enviada com sucesso para o canal destino!*"
PROCESSING_TIME = "⚡ *Download e envio concluídos em {duration:.1f}s*"

# ─── Erros de download ─────────────────────────────────────────
ERROR_UNKNOWN_URL = (
    "❌ *Link não reconhecido.*\n\n"
    "Envie um link válido do Twitter/X ou uma URL direta de foto/vídeo."
)
ERROR_PRIVATE_TWEET = "❌ Tweet não encontrado, excluído ou de conta privada."
ERROR_TOO_LARGE = "❌ Arquivo muito grande. O limite configurado é de {max_size}MB."
ERROR_TIMEOUT = "❌ Tempo limite de download excedido. O servidor demorou a responder."
ERROR_NO_MEDIA = "❌ Nenhuma mídia de foto ou vídeo encontrada neste link."
ERROR_HTTP = "❌ Não foi possível acessar o link (Erro HTTP {status_code})."
ERROR_UNREACHABLE = "❌ Link inacessível. Verifique se a URL está correta e online."
ERROR_UNEXPECTED = "❌ Ocorreu um erro inesperado durante o processamento:\n`{error}`"
ERROR_NO_TARGET = (
    "❌ *Nenhum grupo/canal destino configurado.*\n\n"
    "Adicione o bot ao canal desejado com permissão de postagem e use `/settarget` lá dentro, ou configure pelo `/painel`."
)

# ─── Painel de Controle ─────────────────────────────────────────
PANEL_TITLE = (
    "🎛️ *PAINEL DE CONTROLE — HotReaper VIP v3.0*\n\n"
    "Escolha uma das opções abaixo para gerenciar o bot:"
)
PANEL_MAIN_TITLE = PANEL_TITLE

PANEL_CONFIG_TITLE = (
    "⚙️ *CONFIGURAÇÕES GERAIS*\n\n"
    "• *Canal Destino:* `{target_chat}`\n"
    "• *Limite por Arquivo:* `{max_size} MB`\n"
    "• *Modo Silencioso:* `{silent_mode}`\n"
    "• *Modo de Legenda:* `{caption_mode}`\n"
    "• *Timeout de Download:* `{timeout}s`\n"
)

PANEL_STATS_TITLE = (
    "📊 *ESTATÍSTICAS DO SISTEMA*\n\n"
    "• *Total de Downloads:* `{total}`\n"
    "• *Sucessos:* `{successes}` | *Falhas:* `{failures}`\n"
    "• *Hoje:* `{today}` | *Últimos 7 dias:* `{week}`\n"
    "• *Arquivos Enviados:* `{total_files}`\n"
    "• *Volume Total:* `{total_mb:.1f} MB`\n\n"
    "*Por Fonte:*\n"
    "{by_source}"
)

PANEL_HISTORY_TITLE = "📋 *ÚLTIMOS DOWNLOADS*\n\n{history_items}"
PANEL_SYSTEM_TITLE = (
    "🔧 *STATUS DO SISTEMA*\n\n"
    "• *Versão:* `v{version}`\n"
    "• *Cache Temporário:* `{temp_size:.2f} MB` ({temp_files} arquivos)\n"
    "• *Banco de Dados:* `{db_size:.2f} KB`\n"
)
