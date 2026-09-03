"""Módulo de Inteligência Artificial para geração de legendas adultas/VIP via Groq Cloud com visão computacional (multimodal) e acervo reserva."""
import asyncio
import base64
import json
import logging
import random
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Literal

import httpx

from bot.core.config import GROQ_API_KEY
from bot.core.database import get_config

logger = logging.getLogger(__name__)

GROQ_ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"

# Modelos padrão na Groq em ordem de prioridade (modelos com suporte multimodal de visão no topo)
DEFAULT_GROQ_MODELS = [
    "qwen/qwen3.8-27b",
    "qwen/qwen3.6-27b",
    "groq/compound",
    "groq/compound-mini",
]

# ─── Catálogo de Legendas Reserva Pré-Prontas (Brasileiras, Naturais e Impecáveis) ───

BACKUP_CAPTIONS_PICANTE = [
    "Tava com um calor insuportável no quarto hoje... olha onde a roupa foi parar 😈",
    "Gravei todinha sem calcinha pensando em você... me diz se você aguenta assistir até o fim 🔥",
    "Você não imagina a loucura que eu aprontei na cama hoje... vem ver de pertinho 🤤",
    "Perdi a vergonha e fiz tudo que você sempre me pede... gostou da visão? 💋",
    "Deixei a porta aberta e gravei esse momento bem safado só pra você 😈🔥",
    "Tava subindo pelas paredes e tive que registrar essa delícia... aproveita 🤤",
    "Vem ver o que eu faço quando fico sozinha no quarto pensando em você 🔞🔥",
    "Segura essa visão que hoje eu tava totalmente sem limites... delícia pura 😈",
    "Quem tem coragem de assistir tudinho sem babar na tela? Me conta o que achou 🤤💋",
    "O clima esquentou por aqui e não deu pra segurar a vontade... corre pra ver 🔥",
    "Sem calcinha e morrendo de vontade... vem cá matar essa curiosidade 😈",
    "Olha o que acabou de sair do forno pra vocês... gravei todinha com muito tesão 🤤🔥",
    "Tava inspirada e totalmente safada hoje... o resultado ficou uma loucura 💋",
    "Mais um momento quente e exclusivo gravado especialmente pra quem aprecia de verdade 😈🔥",
    "Tô daquele jeito hoje... quem vem cuidar de mim e me fazer companhia? 🤤🔞",
    "Pra esquentar seu dia do melhor jeito possível... aproveita cada segundo 🔥😈",
    "Gostou do que viu? Imagina se você estivesse aqui comigo ao vivo 💋",
    "Toda molhadinha só pra atiçar sua imaginação... vem cá ver 🤤🔞",
]

BACKUP_CAPTIONS_SENSUAL = [
    "Um pedacinho do meu mundinho secreto pra você admirar e se apaixonar 💋✨",
    "Gosto quando você olha cada detalhe com desejo... gostou do ângulo que escolhi? 😈",
    "Deixando o seu dia muito mais gostoso e interessante hoje... dá uma olhadinha 💋🔥",
    "Sensualidade pura e sem limites... o que achou desse momento de pertinho? 🤤",
    "Um toque de provocação irresistível pra não sair da sua cabeça o dia todo 💋😈",
    "Você prefere me ver de frente ou de costas? Fica a dúvida no ar 😈",
    "Aquela olhadinha de lado que diz exatamente o que eu tô querendo de você 💋🤤",
    "Provocando na medida certa pra acelerar os seus batimentos... curtiu? 🔥",
]

BACKUP_CAPTIONS_CONVERSAO = [
    "O melhor conteúdo tá sempre aqui no VIP... aproveita que esse tá surreal de bom 👑🔥",
    "Conteúdo pesado e 100% exclusivo pra quem não perde nenhuma novidade quente 🤤🔞",
    "Quem me acompanha aqui dentro sabe: a qualidade e o tesão são sem comparação 😈👑",
    "Atualização pesada pra fechar o dia do melhor jeito possível... dá o play 🔥💋",
    "Mais uma entrega especial e sem censura com a exclusividade que você merece 🔞👑",
    "Não perde tempo e assiste logo essa delícia do começo ao fim 🤤🔥",
]

ALL_BACKUP_CAPTIONS = BACKUP_CAPTIONS_PICANTE + BACKUP_CAPTIONS_SENSUAL + BACKUP_CAPTIONS_CONVERSAO


def _extract_video_frame_base64(video_path: Path | str, max_width: int = 720) -> str | None:
    """Extrai defensivamente 1 frame rápido do vídeo usando ffmpeg e converte em base64."""
    v_path = Path(video_path)
    if not v_path.exists() or v_path.stat().st_size == 0:
        return None

    ffmpeg_bin = shutil.which("ffmpeg")
    if not ffmpeg_bin:
        return None

    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp_f:
        tmp_path = Path(tmp_f.name)

    try:
        cmd = [
            ffmpeg_bin, "-y",
            "-ss", "00:00:01",
            "-i", str(v_path),
            "-vframes", "1",
            "-q:v", "3",
            "-vf", f"scale='min({max_width},iw)':-2",
            str(tmp_path),
        ]
        res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=6)
        if res.returncode == 0 and tmp_path.exists() and tmp_path.stat().st_size > 0:
            return base64.b64encode(tmp_path.read_bytes()).decode("utf-8")
    except Exception as e:
        logger.debug(f"Aviso ao extrair frame de vídeo para visão: {e}")
    finally:
        tmp_path.unlink(missing_ok=True)

    return None


def _encode_photo_base64(photo_path: Path | str) -> str | None:
    """Lê defensivamente uma foto e codifica em base64 para envio à visão computacional."""
    p_path = Path(photo_path)
    if not p_path.exists() or p_path.stat().st_size == 0:
        return None
    try:
        # Lê os bytes da imagem
        raw = p_path.read_bytes()
        if len(raw) > 0:
            return base64.b64encode(raw).decode("utf-8")
    except Exception as e:
        logger.debug(f"Aviso ao codificar foto em base64: {e}")
    return None


def _get_system_prompt(style: str) -> str:
    """Gera o System Prompt com arquitetura objetiva: Visão de Vestimenta/Cena -> Persona VIP +18 -> Execução Direta."""
    return (
        "Você é uma mulher brasileira muito safada, gostosa e sem pudor, dona de um canal VIP adulto +18 no Telegram.\n"
        "Seu único papel é escrever uma legenda curta, MUITO apelativa, provocante e com muito tesão para atiçar seus assinantes.\n\n"
        "FLUXO OBRIGATÓRIO DE CRIAÇÃO:\n"
        "1. OBSERVE A CENA E O QUE VOCÊ ESTÁ VESTINDO:\n"
        "   - Analise com precisão o que você está vestindo:\n"
        "     • Se estiver sem nada: diga que está pelada, nua, sem nada ou sem roupa.\n"
        "     • Se estiver de lingerie ou calcinha: mencione a lingerie ou calcinha (cite a cor se for nítida, ex: lingerie preta).\n"
        "     • Se estiver de biquíni: mencione biquíni (NUNCA chame biquíni de lingerie ou fitinhas).\n"
        "     • Se estiver com amarras/harness ou fantasia: mencione as amarras ou a fantasia.\n"
        "   - Quantas pessoas aparecem? Se houver casal ou homem junto, fale no plural ('a gente', 'olha o que a gente aprontou', 'fizemos essa loucura').\n"
        "   - Se estiver apenas a mulher, fale em primeira pessoa ('olha como eu fico', 'gravei pensando em você', 'tô morrendo de tesão').\n"
        "   - NUNCA use a palavra 'sozinha'.\n"
        "2. TOM APELATIVO +18 E LINGUAGEM:\n"
        "   - Fale com muito tesão, malícia e safadeza de verdade, sem vergonha e sem censura.\n"
        "   - Use vocabulário brasileiro natural e apelativo: tesão, molhadinha, gostosa, safada, me comer, me fuder, gemer, sem calcinha, aproveitar.\n"
        "   - NUNCA use gírias masculinas de amigos ('cara', 'mano', 'velho', 'bro'). Chame de 'amor', 'gostoso', 'vida', ou fale direto ao ponto sem vocativo.\n"
        "   - NUNCA faça narrações mecânicas de ações (proibido 'me mexia de propósito'). Foque no tesão visual e na provocação.\n"
        "   - Sem formalidades: use português informal, direto e quente.\n"
        "3. FORMATO:\n"
        "   - Apenas 1 ou 2 frases curtas com no máximo 1 ou 2 emojis safados no final (ex: 🔥, 😈, 🤤 ou 🔞)."
    )


def _sanitize_caption(raw_text: str) -> str:
    """Higieniza a legenda, corrige slips arcaicos, remove tags e restringe a no máximo 2 emojis."""
    clean = re.sub(r'<think>.*?</think>', '', raw_text, flags=re.DOTALL).strip()
    clean = re.sub(r'^(?:Legenda:?|Aqui\s*est[aá]:?|Texto:?|Resposta:?)\s*', '', clean, flags=re.IGNORECASE)
    clean = clean.strip('"\'' )

    # Remove vocativos masculinos de 'amigos' que destoam de uma criadora VIP (ex: "Cara, olha como...")
    clean = re.sub(r'^(?:Cara|Mano|Velho|Bro|Parça|Brother)[,\s]+', '', clean, flags=re.IGNORECASE)
    # Capitaliza primeira letra caso tenha removido o início
    if clean:
        clean = clean[0].upper() + clean[1:]

    # Correção defensiva em regex contra termos formais/arcaicos
    formal_replacements = {
        r'\bdespidos\b': 'peladas',
        r'\bdespido\b': 'pelada',
        r'\bdespidas\b': 'peladas',
        r'\bdespida\b': 'pelada',
        r'\bdeleitar(?:-se)?\b': 'aproveitar',
        r'\bdesfrutar\b': 'curtir',
        r'\banseios\b': 'desejos',
        r'\bdeliciar-se\b': 'aproveitar',
    }
    for pattern, rep in formal_replacements.items():
        clean = re.sub(pattern, rep, clean, flags=re.IGNORECASE)

    # Proíbe sequências exageradas de emojis (mantém no máximo 2 emojis no texto)
    emoji_pattern = re.compile(
        r'[\U00010000-\U0010ffff\u2600-\u27bf\u2b50\u2b55\u231a-\u231b\u23e9-\u23ec\u23f0\u23f3]'
    )
    emojis = emoji_pattern.findall(clean)
    if len(emojis) > 2:
        count = 0
        def _keep_max_two(match):
            nonlocal count
            count += 1
            return match.group(0) if count <= 2 else ""
        clean = emoji_pattern.sub(_keep_max_two, clean)

    # Limpa espaços duplos
    clean = re.sub(r'\s+', ' ', clean).strip()
    return clean


def get_random_backup_caption(style: str = "picante") -> str:
    """Retorna uma legenda reserva pré-pronta caso extremo onde todas as tentativas da IA falhem."""
    if style == "sensual":
        return random.choice(BACKUP_CAPTIONS_SENSUAL)
    elif style == "conversao":
        return random.choice(BACKUP_CAPTIONS_CONVERSAO)
    elif style == "picante":
        return random.choice(BACKUP_CAPTIONS_PICANTE)
    return random.choice(ALL_BACKUP_CAPTIONS)


async def generate_ai_caption(
    title_or_context: str = "",
    media_type: str = "video",
    style: str | None = None,
    media_path: Path | str | None = None,
    timeout: float = 12.0,
) -> str:
    """
    Gera uma legenda adulta altamente contextual via Groq Cloud com visão computacional (multimodal)
    e 3 travas estritas de gênero feminino, português coloquial brasileiro e anti-formalismo.
    """
    if not style:
        style = await get_config("ai_caption_style", "picante") or "picante"

    api_key = GROQ_API_KEY
    if not api_key:
        api_key = await get_config("groq_api_key", "") or ""

    if not api_key:
        logger.warning("GROQ_API_KEY não configurada. Utilizando acervo reserva de legendas.")
        return get_random_backup_caption(style)

    configured_model = await get_config("groq_model", "qwen/qwen3.8-27b") or "qwen/qwen3.8-27b"
    models_to_try = [configured_model] + [m for m in DEFAULT_GROQ_MODELS if m != configured_model]

    system_prompt = _get_system_prompt(style)

    # Sanitiza o contexto textual: remove links ou slugs gringos
    clean_ctx = title_or_context.strip()
    if not clean_ctx or any(token in clean_ctx.lower() for token in ["http", "www", ".com", ".mp4", ".jpg", ".webp", "/", "\\", "_", "-"]):
        clean_ctx = f"Novo {media_type} quente e exclusivo gravado para os assinantes VIP"

    # Tenta obter imagem em base64 (visão computacional)
    image_b64 = None
    if media_path:
        try:
            if media_type == "photo":
                image_b64 = _encode_photo_base64(media_path)
            elif media_type == "video":
                image_b64 = _extract_video_frame_base64(media_path)
        except Exception as e:
            logger.debug(f"Aviso na extração de mídia para visão: {e}")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=timeout) as client:
        for model_name in models_to_try:
            # 1. Tenta primeiro com visão computacional se a imagem estiver disponível
            if image_b64:
                payload_vision = {
                    "model": model_name,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "text",
                                    "text": f"Analise a cena desta mídia visual e o contexto original ({clean_ctx}). Crie a legenda provocante ideal:" if clean_ctx else "Analise a cena desta mídia visual e crie a legenda provocante ideal:"
                                },
                                {
                                    "type": "image_url",
                                    "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}
                                }
                            ]
                        }
                    ],
                    "temperature": 0.55,
                    "max_tokens": 100,
                }
                try:
                    res = await client.post(GROQ_ENDPOINT, headers=headers, json=payload_vision)
                    if res.status_code == 200:
                        data = res.json()
                        choices = data.get("choices", [])
                        if choices:
                            raw = choices[0].get("message", {}).get("content", "").strip()
                            clean = _sanitize_caption(raw)
                            if clean:
                                logger.info(f"Legenda gerada COM VISÃO ({model_name}): {clean[:60]}...")
                                return clean
                    elif res.status_code == 429:
                        logger.warning(f"Groq RateLimit no modelo {model_name}. Tentando próximo...")
                        continue
                    else:
                        logger.debug(f"Modelo {model_name} recusou visão (HTTP {res.status_code}). Tentando modo texto puro...")
                except Exception as e:
                    logger.debug(f"Falha na tentativa com visão ({model_name}): {e}")

            # 2. Fallback de texto puro (se não tiver imagem ou se o modelo rejeitar imagem)
            payload_text = {
                "model": model_name,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Crie a legenda provocante ideal para esta mídia com base no contexto: {clean_ctx}" if clean_ctx else "Crie a legenda provocante ideal para esta mídia:"}
                ],
                "temperature": 0.55,
                "max_tokens": 100,
            }
            try:
                res = await client.post(GROQ_ENDPOINT, headers=headers, json=payload_text)
                if res.status_code == 200:
                    data = res.json()
                    choices = data.get("choices", [])
                    if choices:
                        raw = choices[0].get("message", {}).get("content", "").strip()
                        clean = _sanitize_caption(raw)
                        if clean:
                            logger.info(f"Legenda gerada MODO TEXTO ({model_name}): {clean[:60]}...")
                            return clean
                elif res.status_code == 429:
                    logger.warning(f"Groq RateLimit no modelo {model_name}. Tentando próximo...")
                    continue
            except Exception as e:
                logger.warning(f"Falha no modo texto ({model_name}): {e}")

    logger.warning("Todas as tentativas na API da Groq falharam. Ativando legenda de reserva do acervo.")
    return get_random_backup_caption(style)
