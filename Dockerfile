FROM python:3.11-slim

# ffmpeg é obrigatório para o yt-dlp mesclar streams de áudio e vídeo
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Criar pastas de runtime (temp = downloads temporários, data = config persistida)
RUN mkdir -p temp data

CMD ["python", "run.py"]
