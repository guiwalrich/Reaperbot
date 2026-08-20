markdown


# 🔥 HotReaper — Telegram Universal Media Downloader Bot
> **HotReaper** é um bot para Telegram de download e reencaminhamento automático de mídias sob demanda. Ele recebe links no chat privado, baixa vídeos e fotos de diversas fontes (Twitter/X, URLs diretas e sites de mídia) e os envia automaticamente para um grupo ou canal destino configurado.
---
## ✨ Principais Funcionalidades
- 🎬 **Extrator Universal de Mídias**:
  - Suporte completo a vídeos e imagens do **Twitter / X** (`twitter.com`, `x.com`).
  - Suporte a **URLs Diretas** de mídias (`.mp4`, `.jpg`, `.png`, `.gif`, `.webp`, `.webm`).
  - Fallback inteligente de 2 etapas: tenta extração via **`yt-dlp`** e faz verificação dinâmica de **`Content-Type`** via `httpx`.
- 👥 **Gerenciamento de Grupo Destino (`/settarget`)**:
  - Altere dinamicamente o grupo/canal de destino executando o comando `/settarget` dentro do grupo desejado, com persistência em tempo de execução (`data/config.json`).
- 💎 **Sistema Freemium Integrado**:
  - Banco de dados SQLite (`data/hotreaper.db`) gerenciado via `aiosqlite`.
  - Cota inicial de **3 downloads gratuitos** por usuário.
  - Suporte a planos de assinatura **PRO** ilimitados.
- 🛡️ **Segurança e Gestão de Recursos**:
  - Limite rígido de **50MB** por arquivo (limite da Telegram Bot API).
  - Isolamento de downloads por pasta temporária por sessão (`temp/<uuid>/`).
  - **Limpeza automática** garantida de arquivos residuais no bloco `finally`.
  - Restrição de acesso por lista branca de IDs (`ALLOWED_USER_IDS`).
- 🐳 **Pronto para Produção (Docker & Docker Compose)**:
  - Containerizado com Python 3.11-slim + `ffmpeg` pré-instalado.
  - Política de reinício automático (`restart: always`).
---
## 📌 Comandos do Bot
| Comando | Descrição |
|---|---|
| `/start` | Exibe a mensagem de boas-vindas e instruções básicas. |
| `/help` | Lista os comandos disponíveis e guia de uso. |
| `/settarget` | Define o grupo/canal atual como destino das mídias enviadas. |
| `/status` | Exibe o status da sua conta (downloads usados/restantes ou validade PRO). |
| `/planos` | Exibe os planos de assinatura disponíveis. |
---
## 🛠️ Tecnologias Utilizadas
- **Linguagem:** Python 3.11
- **Telegram SDK:** `python-telegram-bot v21.6`
- **Downloaders:** `yt-dlp` & `httpx` (streaming assíncrono com `aiofiles`)
- **Banco de Dados:** SQLite (`aiosqlite`)
- **Manipulação Mídia:** `ffmpeg`
- **Deploy & Container:** Docker & Docker Compose
---
## 📂 Estrutura do Projeto
```text
HotReaper/
├── bot/
│   ├── __init__.py
│   ├── config.py         # Carregamento de variáveis e prioridade de configs
│   ├── database.py       # Gerenciamento do banco SQLite (Usuários & Assinaturas)
│   ├── downloader.py     # Motor de download (yt-dlp + httpx streaming)
│   ├── handlers.py       # Manipuladores de mensagens e comandos do Telegram
│   ├── main.py           # Ponto de entrada do bot e registro de handlers
│   ├── messages.py       # Centralização de todos os textos e respostas em Markdown
│   ├── resolver.py       # Classificador de URLs (Twitter vs Generic vs Unknown)
│   └── sender.py         # Envio seguro de fotos/vídeos/docs + limpeza de sessão
├── data/                 # Armazena config.json e hotreaper.db (Volume Docker)
├── temp/                 # Pasta de sessões temporárias de download (Volume Docker)
├── .env.example          # Modelo de variáveis de ambiente
├── .gitignore
├── Dockerfile            # Imagem Python 3.11 + ffmpeg
├── docker-compose.yml
├── requirements.txt
├── run.py                # Script de execução
└── README.md
🚀 Como Rodar Localmente
Pré-requisitos
Docker & Docker Compose instalados e em execução.
Token de bot criado no @BotFather.
Passo a Passo
Clonar o repositório:

bash


git clone <url-do-repositorio> HotReaper
cd HotReaper
Configurar as Variáveis de Ambiente: Copie o .env.example para .env:

bash


cp .env.example .env
Edite o arquivo .env:

env


# Token do Telegram obtido no @BotFather
BOT_TOKEN=123456789:AABBCCDDEEFFaabbccddeeff
# (Opcional) ID numérico do grupo destino inicial
TARGET_CHAT_ID=-1001234567890
# IDs de usuários autorizados separados por vírgula (vazio = público)
ALLOWED_USER_IDS=111111111,222222222
Subir com Docker Compose:

bash


docker compose up -d --build
Verificar os Logs:

bash


docker compose logs -f
🌐 Deploy na Oracle Cloud / VPS (Ubuntu 22.04)
Conecte-se na sua VPS e instale o Docker:

bash


sudo apt update && sudo apt install -y docker.io docker-compose-plugin
Clone o projeto e configure o ambiente:

bash


git clone <url-do-repositorio> HotReaper
cd HotReaper
cp .env.example .env
nano .env
Inicie o serviço:

bash


docker compose up -d --build
🎯 Guia Rápido de Uso
Adicione o bot ao seu grupo destino e dê permissão para enviar mídias.
Dentro do grupo, envie o comando /settarget.
Abra o chat privado com o bot e envie qualquer link com foto ou vídeo.
O bot responderá com "⏳ Baixando mídia..." e reencaminhará o arquivo para o grupo configurado.
