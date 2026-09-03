"""Módulo de gerenciamento do banco de dados SQLite assíncrono (aiosqlite) com suporte a Acervo Multi-Canal, Filas e Estatísticas."""
import os
import datetime
import logging
from pathlib import Path
from typing import Any

import aiosqlite

from bot.core.config import DATA_DIR, VAULT_DIR

logger = logging.getLogger(__name__)

DB_PATH = DATA_DIR / "hotreaper.db"

DEFAULT_CONFIGS = {
    "target_chat_id": "",
    "max_file_size_mb": "50",
    "silent_mode": "false",
    "download_timeout_seconds": "60",
    "caption_mode": "ai",  # "ai" | "url" | "none"
    "ai_caption_style": "picante",  # "picante" | "sensual" | "conversao"
    "groq_model": "qwen/qwen3.8-27b",
    "welcome_message_enabled": "true",
    "welcome_message_text": (
        "🔥 *SEJA MUITO BEM-VINDO AO MEU VIP PRIVADO!* 💋\n\n"
        "Que delícia ter você aqui comigo, amor... Esse cantinho foi criado só pra quem quer me ver sem filtros, sem censura e do jeitinho que você sempre sonhou. 😈\n\n"
        "✨ *O que vai rolar por aqui:*\n"
        "• Vídeos pesados e inéditos toda semana 🎬\n"
        "• Ensaios e fotos exclusivas que não posto em lugar nenhum 📸\n"
        "• Minha intimidade sem nenhum limite... 🔥\n\n"
        "🔔 *Dica de ouro:* Fixa esse canal no topo do seu Telegram e ativa as notificações para não perder nenhuma das minhas loucuras que vão entrar no ar!\n\n"
        "_Prepara a mente (e o corpo)... o show tá só começando._ 🔞🤤"
    ),
    "default_interval_hours": "2",
}


async def init_db() -> None:
    """Inicializa as tabelas do banco de dados, cria índices e insere as configurações padrão."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    VAULT_DIR.mkdir(parents=True, exist_ok=True)

    async with aiosqlite.connect(DB_PATH) as db:
        # Otimizações de Concorrência e Performance (Fase 1: WAL Mode & Cache)
        await db.execute("PRAGMA journal_mode = WAL;")
        await db.execute("PRAGMA synchronous = NORMAL;")
        await db.execute("PRAGMA busy_timeout = 5000;")
        await db.execute("PRAGMA cache_size = -8000;")

        # 1. Tabela de configurações do bot (chave/valor)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS config (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 2. Tabela de histórico de downloads
        await db.execute("""
            CREATE TABLE IF NOT EXISTS download_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL,
                source TEXT NOT NULL,
                file_count INTEGER DEFAULT 0,
                total_size_bytes INTEGER DEFAULT 0,
                status TEXT DEFAULT 'SUCCESS',
                error_message TEXT,
                duration_seconds REAL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 3. Tabela de canais/grupos cadastrados com controle de disparo e cadência
        await db.execute("""
            CREATE TABLE IF NOT EXISTS channels (
                channel_id TEXT PRIMARY KEY,
                title TEXT DEFAULT '',
                dispatch_mode TEXT DEFAULT 'instant',
                schedule_times TEXT DEFAULT '10:00,14:00,18:00,22:00',
                consecutive_videos_count INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 1,
                has_welcomed INTEGER DEFAULT 0,
                welcome_message_id INTEGER DEFAULT 0,
                interval_hours INTEGER DEFAULT 2,
                last_dispatched_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 4. Tabela do Acervo de Mídias (Media Vault) isolado por canal
        await db.execute("""
            CREATE TABLE IF NOT EXISTS media_vault (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id TEXT NOT NULL,
                file_path TEXT NOT NULL,
                media_type TEXT NOT NULL,
                file_size_bytes INTEGER NOT NULL,
                duration_seconds INTEGER DEFAULT 0,
                width INTEGER DEFAULT 0,
                height INTEGER DEFAULT 0,
                title TEXT,
                ai_caption TEXT,
                original_url TEXT,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                sent_at TIMESTAMP
            )
        """)

        # 5. Índices para performance e consultas
        await db.execute("CREATE INDEX IF NOT EXISTS idx_download_history_created_at ON download_history(created_at DESC)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_download_history_status ON download_history(status)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_vault_channel_status ON media_vault(channel_id, status)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_vault_type ON media_vault(media_type)")

        # 6. Insere configurações padrão se ainda não existirem
        seed_configs = dict(DEFAULT_CONFIGS)
        env_target = os.getenv("TARGET_CHAT_ID", "").strip()
        if env_target:
            seed_configs["target_chat_id"] = env_target

        for key, val in seed_configs.items():
            await db.execute(
                "INSERT OR IGNORE INTO config (key, value) VALUES (?, ?)",
                (key, str(val)),
            )

        if env_target:
            await db.execute(
                "INSERT OR IGNORE INTO channels (channel_id, title, dispatch_mode) VALUES (?, ?, ?)",
                (env_target, "Canal Principal", "instant"),
            )

        # Migração defensiva caso a coluna has_welcomed ou welcome_message_id não exista
        try:
            await db.execute("ALTER TABLE channels ADD COLUMN has_welcomed INTEGER DEFAULT 0")
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE channels ADD COLUMN welcome_message_id INTEGER DEFAULT 0")
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE channels ADD COLUMN interval_hours INTEGER DEFAULT 2")
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE channels ADD COLUMN last_dispatched_at TIMESTAMP")
        except Exception:
            pass

        await db.commit()


# ─── Configurações Gerais ───────────────────────────────────────────────

async def get_config(key: str, default: str | None = None) -> str | None:
    """Lê uma configuração do banco de dados."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT value FROM config WHERE key = ?", (key,)) as cursor:
            row = await cursor.fetchone()
            if row is not None:
                return str(row["value"])
            return default


async def set_config(key: str, value: Any) -> None:
    """Define ou atualiza uma configuração no banco de dados com validação de tipos."""
    str_val = str(value).strip()

    if key == "max_file_size_mb":
        try:
            num = int(str_val)
            if num <= 0:
                str_val = "50"
        except ValueError:
            str_val = "50"
    elif key == "download_timeout_seconds":
        try:
            flt = float(str_val)
            if flt <= 0.0:
                str_val = "60"
        except ValueError:
            str_val = "60"

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO config (key, value, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = CURRENT_TIMESTAMP
        """, (key, str_val))


        await db.commit()


async def get_all_config() -> dict[str, str]:
    """Retorna todas as configurações salvas em forma de dicionário."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT key, value FROM config") as cursor:
            rows = await cursor.fetchall()
            return {row["key"]: row["value"] for row in rows}


# ─── Gestão de Canais / Grupos ──────────────────────────────────────────

async def register_channel(channel_id: str | int, title: str = "", dispatch_mode: str = "instant") -> None:
    """Cadastra ou atualiza as informações de um canal de destino."""
    cid_str = str(channel_id).strip()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO channels (channel_id, title, dispatch_mode)
            VALUES (?, ?, ?)
            ON CONFLICT(channel_id) DO UPDATE SET
                title = CASE WHEN excluded.title != '' THEN excluded.title ELSE channels.title END,
                is_active = 1
        """, (cid_str, title, dispatch_mode))


        await db.commit()


async def get_channel(channel_id: str | int) -> dict[str, Any] | None:
    """Retorna os dados cadastrais e de cadência de um canal."""
    cid_str = str(channel_id).strip()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM channels WHERE channel_id = ?", (cid_str,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def get_all_channels() -> list[dict[str, Any]]:
    """Lista todos os canais ativos cadastrados."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM channels WHERE is_active = 1 ORDER BY created_at ASC") as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]


async def set_channel_dispatch_mode(channel_id: str | int, mode: str) -> None:
    """Altera o modo de disparo do canal ('instant', 'interval', 'scheduled', 'manual')."""
    cid_str = str(channel_id).strip()
    if mode not in ["instant", "interval", "scheduled", "manual"]:
        mode = "instant"
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE channels SET dispatch_mode = ? WHERE channel_id = ?", (mode, cid_str))
        await db.commit()


async def set_channel_interval_hours(channel_id: str | int, hours: int) -> None:
    """Define o intervalo em horas entre disparos automáticos do canal."""
    cid_str = str(channel_id).strip()
    h = max(1, min(24, int(hours)))
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE channels SET interval_hours = ? WHERE channel_id = ?", (h, cid_str))
        await db.commit()


async def update_channel_last_dispatched(channel_id: str | int, dt: datetime.datetime | None = None) -> None:
    """Atualiza o timestamp do último disparo realizado no canal (em horário de Brasília)."""
    from bot.core.config import get_brazil_now
    cid_str = str(channel_id).strip()
    now_dt = dt or get_brazil_now()
    now_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE channels SET last_dispatched_at = ? WHERE channel_id = ?", (now_str, cid_str))
        await db.commit()


async def set_channel_schedule_times(channel_id: str | int, times_str: str) -> None:
    """Define a grade de horários de disparo do canal (ex: '10:00,14:00,18:00,22:00')."""
    cid_str = str(channel_id).strip()
    # Valida formato de horários
    parts = [p.strip() for p in times_str.split(",") if p.strip()]
    valid_parts = []
    for p in parts:
        if len(p) == 5 and p[2] == ":" and p[:2].isdigit() and p[3:].isdigit():
            valid_parts.append(p)
    clean_times = ",".join(valid_parts) if valid_parts else "10:00,14:00,18:00,22:00"

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE channels SET schedule_times = ? WHERE channel_id = ?", (clean_times, cid_str))


        await db.commit()


async def increment_channel_video_counter(channel_id: str | int) -> int:
    """Incrementa a contagem de vídeos consecutivos enviados no canal e retorna o novo valor."""
    cid_str = str(channel_id).strip()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE channels SET consecutive_videos_count = consecutive_videos_count + 1 WHERE channel_id = ?", (cid_str,))


        await db.commit()
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT consecutive_videos_count FROM channels WHERE channel_id = ?", (cid_str,)) as cursor:
            row = await cursor.fetchone()
            return row["consecutive_videos_count"] if row else 1


async def reset_channel_video_counter(channel_id: str | int) -> None:
    """Zera a contagem de vídeos consecutivos enviados (após o disparo de um pack de fotos)."""
    cid_str = str(channel_id).strip()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE channels SET consecutive_videos_count = 0 WHERE channel_id = ?", (cid_str,))


        await db.commit()


# ─── Gestão do Acervo de Mídias (Media Vault) com Transações Atômicas ──

async def add_media_to_vault(
    channel_id: str | int,
    file_path: Path | str,
    media_type: str,
    file_size_bytes: int,
    duration_seconds: int = 0,
    width: int = 0,
    height: int = 0,
    title: str = "",
    ai_caption: str = "",
    original_url: str = "",
) -> int:
    """Adiciona uma nova mídia ao acervo do canal no banco de dados."""
    cid_str = str(channel_id).strip()
    fpath_str = str(file_path)
    mtype = "video" if media_type.lower() in ["video", "mp4", "webm", "mov", "mkv"] else "photo"

    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            INSERT INTO media_vault (
                channel_id, file_path, media_type, file_size_bytes,
                duration_seconds, width, height, title, ai_caption, original_url, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
        """, (cid_str, fpath_str, mtype, file_size_bytes, duration_seconds, width, height, title, ai_caption, original_url))


        await db.commit()
        return cursor.lastrowid or 0


async def get_vault_stats(channel_id: str | int | None = None) -> dict[str, Any]:
    """Calcula estatísticas de itens pendentes/em processamento no acervo."""
    cid_str = str(channel_id).strip() if channel_id else None
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        query = """
            SELECT
                COUNT(*) as total_pending,
                SUM(CASE WHEN media_type = 'video' THEN 1 ELSE 0 END) as pending_videos,
                SUM(CASE WHEN media_type = 'photo' THEN 1 ELSE 0 END) as pending_photos,
                COALESCE(SUM(file_size_bytes), 0) as total_bytes
            FROM media_vault
            WHERE status IN ('pending', 'processing')
        """
        params = []
        if cid_str:
            query += " AND channel_id = ?"
            params.append(cid_str)

        async with db.execute(query, params) as cursor:
            row = await cursor.fetchone()
            if not row:
                return {"total_pending": 0, "pending_videos": 0, "pending_photos": 0, "total_mb": 0.0}
            total_b = row["total_bytes"] or 0
            return {
                "total_pending": row["total_pending"] or 0,
                "pending_videos": row["pending_videos"] or 0,
                "pending_photos": row["pending_photos"] or 0,
                "total_bytes": total_b,
                "total_mb": round(total_b / (1024 * 1024), 2),
            }


async def acquire_next_pending_video(channel_id: str | int) -> dict[str, Any] | None:
    """
    Reserva atomicamente o próximo vídeo pendente alterando seu status para 'processing'.
    Garante que duas execuções simultâneas nunca selecionem a mesma mídia.
    """
    cid_str = str(channel_id).strip()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT * FROM media_vault
            WHERE channel_id = ? AND media_type = 'video' AND status = 'pending'
            ORDER BY id ASC LIMIT 1
        """, (cid_str,)) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None

            media_id = row["id"]
            await db.execute("UPDATE media_vault SET status = 'processing' WHERE id = ?", (media_id,))
            await db.commit()
            return dict(row)


async def acquire_next_pending_photos_pack(channel_id: str | int, max_photos: int = 3) -> list[dict[str, Any]]:
    """
    Reserva atomicamente até 3 fotos pendentes alterando seus status para 'processing'.
    """
    cid_str = str(channel_id).strip()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT * FROM media_vault
            WHERE channel_id = ? AND media_type = 'photo' AND status = 'pending'
            ORDER BY id ASC LIMIT ?
        """, (cid_str, max_photos)) as cursor:
            rows = await cursor.fetchall()
            if not rows:
                return []

            media_ids = [r["id"] for r in rows]
            placeholders = ",".join("?" for _ in media_ids)
            await db.execute(f"UPDATE media_vault SET status = 'processing' WHERE id IN ({placeholders})", media_ids)
            await db.commit()
            return [dict(r) for r in rows]


# Compatibilidade com chamadas de leitura direta
get_next_pending_video = acquire_next_pending_video
get_next_pending_photos_pack = acquire_next_pending_photos_pack


async def release_media_reservation(media_ids: list[int]) -> None:
    """Reverte o status de 'processing' de volta para 'pending' caso ocorra falha de envio no Telegram."""
    if not media_ids:
        return
    placeholders = ",".join("?" for _ in media_ids)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE media_vault SET status = 'pending' WHERE id IN ({placeholders}) AND status = 'processing'", media_ids)


        await db.commit()


async def mark_media_sent_and_delete(media_ids: list[int]) -> None:
    """
    Marca mídias como enviadas no banco PRIMEIRO e só depois apaga os arquivos do disco.
    Garante integridade transacional mesmo se ocorrer falha de E/S de arquivo.
    """
    if not media_ids:
        return

    placeholders = ",".join("?" for _ in media_ids)
    files_to_delete = []

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        # 1. Coleta caminhos de arquivos antes da alteração
        async with db.execute(f"SELECT id, file_path FROM media_vault WHERE id IN ({placeholders})", media_ids) as cursor:
            rows = await cursor.fetchall()
            for r in rows:
                files_to_delete.append(Path(r["file_path"]))

        # 2. Atualiza status no banco e efetua commit
        await db.execute(f"""
            UPDATE media_vault
            SET status = 'sent', sent_at = CURRENT_TIMESTAMP
            WHERE id IN ({placeholders})
        """, media_ids)


        await db.commit()

    # 3. Exclui arquivos físicos do disco após o commit
    for p in files_to_delete:
        try:
            if p.exists() and p.is_file():
                p.unlink(missing_ok=True)
        except Exception as e:
            logger.warning(f"Aviso ao remover arquivo físico {p}: {e}")


async def reconcile_vault_integrity() -> dict[str, int]:
    """
    Rotina de reconciliação de integridade física e banco de dados:
    - Reseta registros 'processing' deixados pendentes por desligamento/crash anterior.
    - Marca como 'failed' registros 'pending' cujo arquivo físico foi apagado manualmente.
    - Exclui arquivos órfãos no disco que não constem no banco.
    """
    resets = 0
    missing_marked = 0
    orphans_cleaned = 0

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        # 1. Reseta status 'processing' pendente
        cur = await db.execute("UPDATE media_vault SET status = 'pending' WHERE status = 'processing'")
        resets = cur.rowcount or 0

        # 2. Verifica se arquivos de registros 'pending' existem no disco
        async with db.execute("SELECT id, file_path FROM media_vault WHERE status = 'pending'") as cursor:
            pending_rows = await cursor.fetchall()
            for r in pending_rows:
                p = Path(r["file_path"])
                if not p.exists() or not p.is_file():
                    await db.execute("UPDATE media_vault SET status = 'failed' WHERE id = ?", (r["id"],))
                    missing_marked += 1

        # 3. Limpeza de arquivos órfãos no diretório do vault
        valid_paths = set()
        async with db.execute("SELECT file_path FROM media_vault WHERE status IN ('pending', 'processing')") as cursor:
            rows = await cursor.fetchall()
            for r in rows:
                valid_paths.add(Path(r["file_path"]).resolve())

        if VAULT_DIR.exists():
            for f in VAULT_DIR.rglob("*"):
                if f.is_file() and f.name != ".gitkeep":
                    if f.resolve() not in valid_paths:
                        try:
                            f.unlink(missing_ok=True)
                            orphans_cleaned += 1
                        except Exception:
                            pass



        await db.commit()

    if resets or missing_marked or orphans_cleaned:
        logger.info(f"🛡️ Reconciliação do Acervo: {resets} resetados, {missing_marked} faltantes marcados, {orphans_cleaned} órfãos limpos.")

    return {
        "resets": resets,
        "missing_marked": missing_marked,
        "orphans_cleaned": orphans_cleaned,
    }


# ─── Histórico de Downloads ─────────────────────────────────────────────

async def log_download(
    url: str,
    source: str,
    file_count: int = 0,
    total_size_bytes: int = 0,
    status: str = "SUCCESS",
    error_message: str | None = None,
    duration_seconds: float = 0.0,
) -> int:
    """Registra uma operação de download no histórico."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            INSERT INTO download_history
                (url, source, file_count, total_size_bytes, status, error_message, duration_seconds)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (url, source, file_count, total_size_bytes, status, error_message, round(duration_seconds, 2)))


        await db.commit()
        return cursor.lastrowid or 0


async def get_recent_downloads(limit: int = 10) -> list[dict]:
    """Retorna a lista dos downloads mais recentes."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM download_history ORDER BY id DESC LIMIT ?",
            (limit,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]


async def get_download_stats() -> dict[str, Any]:
    """Calcula estatísticas agregadas dos downloads."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        async with db.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN status = 'SUCCESS' THEN 1 ELSE 0 END) as successes,
                SUM(CASE WHEN status = 'FAILED' THEN 1 ELSE 0 END) as failures,
                COALESCE(SUM(total_size_bytes), 0) as total_bytes,
                COALESCE(SUM(file_count), 0) as total_files
            FROM download_history
        """) as cursor:
            agg = dict(await cursor.fetchone() or {})

        async with db.execute("""
            SELECT COUNT(*) as count_today
            FROM download_history
            WHERE date(created_at) = date('now')
        """) as cursor:
            row_today = await cursor.fetchone()
            count_today = row_today["count_today"] if row_today else 0

        async with db.execute("""
            SELECT COUNT(*) as count_week
            FROM download_history
            WHERE date(created_at) >= date('now', '-7 days')
        """) as cursor:
            row_week = await cursor.fetchone()
            count_week = row_week["count_week"] if row_week else 0

        async with db.execute("""
            SELECT source, COUNT(*) as count
            FROM download_history
            GROUP BY source
        """) as cursor:
            source_rows = await cursor.fetchall()
            by_source = {row["source"]: row["count"] for row in source_rows}

        return {
            "total_downloads": agg.get("total", 0) or 0,
            "successful_downloads": agg.get("successes", 0) or 0,
            "failed_downloads": agg.get("failures", 0) or 0,
            "total_size_bytes": agg.get("total_bytes", 0) or 0,
            "total_files": agg.get("total_files", 0) or 0,
            "today_downloads": count_today,
            "week_downloads": count_week,
            "by_source": by_source,
        }



async def mark_channel_welcomed(channel_id: str | int, status: int = 1) -> None:
    """Atualiza a flag de mensagem de boas-vindas do canal (1 = enviada, 0 = pendente)."""
    cid_str = str(channel_id).strip()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE channels SET has_welcomed = ? WHERE channel_id = ?", (status, cid_str))
        await db.commit()


async def is_channel_welcomed(channel_id: str | int) -> bool:
    """Verifica se a mensagem de boas-vindas já foi enviada e fixada no canal."""
    cid_str = str(channel_id).strip()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT has_welcomed FROM channels WHERE channel_id = ?", (cid_str,)) as cursor:
            row = await cursor.fetchone()
            if row and "has_welcomed" in row.keys() and row["has_welcomed"]:
                return True
            return False


async def set_channel_welcome_message_id(channel_id: str | int, message_id: int) -> None:
    """Armazena o message_id da mensagem de boas-vindas fixada no canal."""
    cid_str = str(channel_id).strip()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE channels SET welcome_message_id = ? WHERE channel_id = ?", (message_id, cid_str))
        await db.commit()


async def get_channel_welcome_message_id(channel_id: str | int) -> int:
    """Recupera o message_id da mensagem de boas-vindas do canal."""
    cid_str = str(channel_id).strip()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT welcome_message_id FROM channels WHERE channel_id = ?", (cid_str,)) as cursor:
            row = await cursor.fetchone()
            if row and "welcome_message_id" in row.keys() and row["welcome_message_id"]:
                return int(row["welcome_message_id"])
            return 0
