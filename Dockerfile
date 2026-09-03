FROM python:3.11-slim

# Instala ffmpeg, curl, gosu e tzdata para fuso horário de Brasília
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg curl gosu tzdata \
    && rm -rf /var/lib/apt/lists/*

ENV TZ=America/Sao_Paulo

WORKDIR /app

# Cria usuário não-privilegiado appuser (UID 1000)
RUN useradd -m -u 1000 appuser

# Instala dependências do Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia código da aplicação
COPY . .

# Garante permissões de execução no entrypoint
RUN chmod +x /app/entrypoint.sh

# Healthcheck baseado em vivacidade do Heartbeat
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -m bot.healthcheck || exit 1

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["python", "run.py"]
