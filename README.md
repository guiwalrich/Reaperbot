# 🔥 HotReaper Bot

Bot de download automático de mídias sob demanda para o Telegram. Recebe links do Twitter/X ou URLs diretas de mídia no chat privado, faz o download em segundo plano e reencaminha automaticamente para o grupo/canal destino configurado.

---

## 📌 Pré-requisitos

1. **Token do Bot**: Crie um novo bot via [@BotFather](https://t.me/BotFather) no Telegram para obter o `BOT_TOKEN`.
2. **ID do Chat Destino (Opcional no `.env`)**: Obtenha o ID do grupo adicionando o [@userinfobot](https://t.me/userinfobot) ou use o comando `/settarget` diretamente no grupo.
3. **Docker**: Instância Linux com Docker e Docker Compose instalados.

---

## ⚙️ Configuração do Ambiente

1. Clone o repositório e navegue até a pasta do projeto:
   ```bash
   git clone <url-do-repo>
   cd HotReaper
   ```

2. Copie o arquivo de exemplo de variáveis de ambiente e configure suas credenciais:
   ```bash
   cp .env.example .env
   nano .env
   ```

3. Preencha os campos no `.env`:
   - `BOT_TOKEN`: Token obtido no @BotFather.
   - `TARGET_CHAT_ID`: ID numérico do grupo destino (pode ser sobrescrito dinamicamente via `/settarget`).
   - `ALLOWED_USER_IDS`: IDs numéricos dos usuários autorizados separados por vírgula (ou deixe vazio para permitir qualquer usuário).

---

## 🚀 Deploy na Oracle Cloud (Always Free)

Exemplo de deploy na VPS Ubuntu 22.04:

```bash
# 1. Atualizar pacotes e instalar Docker + Docker Compose Plugin
sudo apt update && sudo apt install -y docker.io docker-compose-plugin

# 2. Clonar o repositório
git clone <url-do-repo> && cd HotReaper

# 3. Configurar o arquivo .env
cp .env.example .env && nano .env

# 4. Iniciar o container em segundo plano
docker compose up -d
```

---

## 🎯 Configurando o Grupo Destino

1. Adicione o bot ao grupo ou canal de destino das mídias.
2. Dê permissão para enviar mensagens/fotos/vídeos no grupo.
3. Dentro do próprio grupo, envie o comando:
   ```text
   /settarget
   ```
4. O bot responderá confirmando que aquele chat foi salvo como destino em `data/config.json`.

---

## 💡 Como Usar

1. Abra um chat privado com o bot.
2. Envie um link do Twitter/X (ex: `https://x.com/user/status/123456789`) ou uma URL direta de mídia (ex: `https://exemplo.com/imagem.jpg`).
3. O bot responderá com `"⏳ Baixando..."` e, em seguida, enviará a mídia diretamente para o grupo destino configurado.
