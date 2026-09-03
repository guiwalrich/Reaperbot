# 🔥 HotReaper VIP v3.0

Bot autônomo profissional de download, inteligência artificial de legendas e automação de disparos de conteúdo VIP para o Telegram.

Desenvolvido para criadores de conteúdo e canais VIP, integrando **Motor Universal de Download (1800+ plataformas)**, **Normalização FFmpeg (H.264 / AAC / FastStart sem tela preta)**, **IA Groq Cloud para Legendas Adultas/Sensuais**, **Acervo Multi-Canal com Auto-Limpeza de Disco** e **Algoritmo de Cadência Inteligente (2 Vídeos ➔ 1 Pack de Fotos)**.

# 🔥 HotReaper — Telegram Universal Media Downloader Bot
> **HotReaper** é um bot para Telegram de download e reencaminhamento automático de mídias sob demanda. Ele recebe links no chat privado, baixa vídeos e fotos de diversas fontes (Twitter/X, URLs diretas e sites de mídia) e os envia automaticamente para um grupo ou canal destino configurado.
---

## 🌟 Principais Funcionalidades da v3.0

### 1️⃣ Motor de IA Groq Cloud (Copywriting Adulto/VIP)
- Geração instantânea de legendas em **< 0.8s** utilizando modelos LLaMA 3.3 / Qwen.
- 3 estilos de tom de voz configuráveis no painel:
  - 🔥 **Picante & Safada:** Textos quentes, diretos, com emojis provocantes.
  - 💋 **Sensual & Teasing:** Foco em atiçar a curiosidade e imaginação.
  - 👑 **Conversão VIP:** Foco em conversão e exclusividade para assinantes.
- **Acervo Reserva:** Catálogo com 40+ legendas pré-prontas ativado em caso de falha de conexão (zero posts sem legenda).

### 2️⃣ Acervo Multi-Canal & Auto-Limpeza de Disco
- Isolamento absoluto de mídias por canal (`/data/vault/<channel_id>/`).
- **Limpeza Imediata:** Assim que o vídeo ou pack de fotos é entregue no Telegram com sucesso, o arquivo físico é **apagado do disco na hora**, mantendo o uso de armazenamento sempre mínimo.

### 3️⃣ Algoritmo de Cadência Inteligente (2 Vídeos ➔ 1 Pack de Fotos)
- O bot rastreia a entrega e aplica a regra de engajamento:
  1. Dispara o **1º Vídeo**.
  2. Dispara o **2º Vídeo**.
  3. No 3º disparo: envia um **Pack de até 3 Fotos** como álbum (`send_media_group`) com a legenda da IA.
  4. Fallback automático: se não houver fotos no acervo, dispara o próximo vídeo sem interromper a fila.
- Funciona tanto no **agendamento automático diário** quanto no **disparo manual via botão**.

### 4️⃣ Normalização FFmpeg & Player Nativo no Telegram
- Transcode automático para codec universal `H.264 (libx264)` e formato de pixel `yuv420p` (100% livre de tela preta).
- Compressão adaptativa para vídeos pesados (>48MB) garantindo envio dentro do limite do Telegram.
- Injeção de `-movflags +faststart` e metadados `ffprobe` para streaming instantâneo.

---

## 📌 Pré-requisitos & Variáveis de Ambiente

Crie o arquivo `.env` a partir do `.env.example`:

```env
# Token gerado pelo @BotFather no Telegram
BOT_TOKEN=SEU_TOKEN_AQUI

# ID numérico do dono único do bot (obtenha via @userinfobot)
OWNER_ID=123456789

# Chave da API Groq Cloud (para geração de legendas via IA)
GROQ_API_KEY=gsk_sua_chave_groq_aqui
```

bash

## 🎛️ Painel de Controle Integrado (`/painel`)

Digite `/painel` no chat privado com o bot para acessar a interface completa:
- **📦 Acervo & Disparos:** Visão da fila em tempo real (vídeos, fotos, MB), próximo da cadência, alternador de modo (*Imediato / Agendado / Manual*) e botão de disparo manual imediato.
- **🤖 IA Groq:** Seleção de estilo de tom de voz da IA e teste de legendas ao vivo no chat.
- **⚙️ Configurações:** Limites de download, modo silencioso e definição de canal destino.
- **📊 Estatísticas & 📋 Histórico:** Métricas agregadas de downloads e logs de processamento.
- **🔧 Sistema & Cache:** Diagnóstico de saúde do container e limpeza de cache temporário.

---

## 🚀 Como Executar

### 🐳 Via Docker Compose (Produção Recomendada)

```bash
# Iniciar o container em segundo plano com build
docker compose up -d --build

# Visualizar logs em tempo real
docker compose logs -f
```

### 🧪 Executando os Testes Automatizados

```bash
pytest tests/ -v
```
