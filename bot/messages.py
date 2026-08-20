"""Mensagens centralizadas do HotReaper Bot."""

# ─── Boas-vindas ───────────────────────────────────────────────
START = (
    "👋 *Bem-vindo ao HotReaper!*\n\n"
    "Eu baixo mídias de qualquer link e envio direto para o grupo configurado.\n\n"
    "📎 *Como usar:*\n"
    "Basta me enviar qualquer link com foto ou vídeo — Twitter/X, sites de mídia ou URL direta.\n\n"
    "⚙️ *Comandos disponíveis:*\n"
    "/help — instruções de uso\n"
    "/settarget — definir grupo destino\n"
    "/status — ver seu status de uso"
)

# ─── Ajuda ─────────────────────────────────────────────────────
HELP = (
    "📖 *HotReaper — Instruções de Uso*\n\n"
    "*Enviar mídia:*\n"
    "Envie qualquer link com foto ou vídeo neste chat. O bot baixa e repassa ao grupo configurado.\n\n"
    "*Links suportados:*\n"
    "• Twitter / X\n"
    "• URLs diretas de imagem ou vídeo\n"
    "• Maioria dos sites de mídia\n\n"
    "*Comandos:*\n"
    "/settarget — use dentro do grupo para definir o destino das mídias\n"
    "/status — veja seu status de uso atual\n"
    "/help — exibe esta mensagem"
)

# ─── Grupo destino ─────────────────────────────────────────────
TARGET_SET = (
    "✅ *Grupo configurado com sucesso!*\n\n"
    "As mídias serão enviadas para este grupo a partir de agora."
)
TARGET_NOT_SET = (
    "❌ *Nenhum grupo configurado.*\n\n"
    "Use o comando /settarget dentro do grupo destino para configurar."
)

# ─── Feedback de download ───────────────────────────────────────
DOWNLOADING = "⏳ Baixando mídia..."
SENT_SUCCESS = "✅ Mídia enviada com sucesso!"

# ─── Erros de download ─────────────────────────────────────────
ERROR_UNKNOWN_URL = (
    "❌ *Link não reconhecido.*\n\n"
    "Envie um link válido do Twitter/X ou uma URL direta de foto ou vídeo."
)
ERROR_PRIVATE_TWEET = "❌ Tweet não encontrado ou é privado."
ERROR_TOO_LARGE = "❌ Arquivo muito grande. O limite é 50MB."
ERROR_TIMEOUT = "❌ Tempo limite de download excedido. Tente novamente."
ERROR_NO_MEDIA = "❌ Nenhuma mídia encontrada neste link."
ERROR_HTTP = "❌ Não foi possível acessar o link (erro HTTP {status_code})."
ERROR_UNREACHABLE = "❌ Link inacessível. Verifique se a URL está correta."
ERROR_UNEXPECTED = "❌ Ocorreu um erro inesperado. Tente novamente mais tarde."
ERROR_NO_TARGET = (
    "❌ *Nenhum grupo configurado.*\n\n"
    "Adicione o bot ao grupo desejado e use /settarget lá dentro."
)

# ─── Autorização ───────────────────────────────────────────────
UNAUTHORIZED = (
    "🔒 Você não tem permissão para usar este bot."
)

# ─── Status do usuário ─────────────────────────────────────────
STATUS_FREE = (
    "📊 *Seu status:*\n\n"
    "Plano: Gratuito\n"
    "Downloads usados: {used}/3\n"
    "Downloads restantes: {remaining}"
)
STATUS_PRO = (
    "📊 *Seu status:*\n\n"
    "Plano: ⭐ Pro\n"
    "Validade: {expiry}\n"
    "Downloads: Ilimitados"
)

# ─── Freemium ──────────────────────────────────────────────────
FREE_DOWNLOADS_REMAINING = (
    "📎 Mídia enviada! Você ainda tem *{remaining}* download(s) gratuito(s)."
)
FREE_DOWNLOADS_LAST = (
    "📎 Mídia enviada!\n\n"
    "⚠️ Este foi seu *último download gratuito*.\n"
    "Use /planos para continuar usando o HotReaper."
)
FREE_LIMIT_REACHED = (
    "🔒 *Seus downloads gratuitos acabaram.*\n\n"
    "Assine o HotReaper para continuar baixando mídias sem limite.\n\n"
    "Use /planos para ver as opções disponíveis."
)

# ─── Planos ────────────────────────────────────────────────────
PLANS = (
    "⭐ *Planos HotReaper*\n\n"
    "━━━━━━━━━━━━━━━━━━━━\n"
    "📅 *Mensal* — {price_monthly}\n"
    "Acesso ilimitado por 30 dias\n\n"
    "📆 *Trimestral* — {price_quarterly}\n"
    "Acesso ilimitado por 90 dias\n"
    "━━━━━━━━━━━━━━━━━━━━\n\n"
    "Use /pagar mensal ou /pagar trimestral para assinar."
)

# ─── Pagamento ─────────────────────────────────────────────────
PAYMENT_SUCCESS = (
    "🎉 *Pagamento confirmado!*\n\n"
    "Sua assinatura está ativa até *{expiry}*.\n"
    "Aproveite downloads ilimitados! 🚀"
)
SUBSCRIPTION_EXPIRING = (
    "⚠️ *Sua assinatura expira em {days} dia(s).*\n\n"
    "Renove agora com /planos para não perder o acesso."
)
SUBSCRIPTION_EXPIRED = (
    "⏰ *Sua assinatura expirou.*\n\n"
    "Use /planos para renovar e continuar com downloads ilimitados."
)
