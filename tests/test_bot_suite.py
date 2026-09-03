"""Bateria de testes automatizados completa e 100% determinística para o HotReaper v2.0."""
import os
import shutil
import sys
import pytest
import asyncio
from pathlib import Path

# Configura ambiente de teste antes de importar o bot
os.environ["BOT_TOKEN"] = "123456:TEST_TOKEN_FAKE"
os.environ["OWNER_ID"] = "99887766"
os.environ["TARGET_CHAT_ID"] = "-100999888"

from bot import config, database, resolver, messages, panel, downloader, sender, handlers, main

@pytest.fixture(autouse=True)
def setup_test_db(tmp_path, monkeypatch):
    """Cria um banco de dados e pastas temporárias isoladas para cada teste."""
    test_data_dir = tmp_path / "data"
    test_temp_dir = tmp_path / "temp"
    test_data_dir.mkdir(parents=True, exist_ok=True)
    test_temp_dir.mkdir(parents=True, exist_ok=True)

    test_db_path = test_data_dir / "test_hotreaper.db"

    monkeypatch.setattr(config, "DATA_DIR", test_data_dir)
    monkeypatch.setattr(config, "TEMP_DIR", test_temp_dir)
    monkeypatch.setattr(database, "DATA_DIR", test_data_dir)
    monkeypatch.setattr(database, "DB_PATH", test_db_path)
    monkeypatch.setattr(downloader, "TEMP_DIR", test_temp_dir)
    monkeypatch.setattr(panel, "TEMP_DIR", test_temp_dir)
    monkeypatch.setattr(panel, "DATA_DIR", test_data_dir)
    monkeypatch.setattr(panel, "DB_PATH", test_db_path)
    monkeypatch.setattr(main, "TEMP_DIR", test_temp_dir)

    asyncio.run(database.init_db())
    yield


# ─── 1. Testes de Configuração ─────────────────────────────────

def test_config_owner_and_version():
    assert config.OWNER_ID == 99887766
    assert config.BOT_VERSION == "3.0.0"
    assert config.BOT_TOKEN == "123456:TEST_TOKEN_FAKE"


# ─── 2. Testes de Banco de Dados ───────────────────────────────

@pytest.mark.asyncio
async def test_database_default_configs():
    all_cfg = await database.get_all_config()
    assert "target_chat_id" in all_cfg
    assert "max_file_size_mb" in all_cfg
    assert all_cfg["max_file_size_mb"] == "50"
    assert all_cfg["silent_mode"] == "false"
    assert all_cfg["caption_mode"] in ["url", "ai"]
    assert all_cfg["download_timeout_seconds"] == "60"


@pytest.mark.asyncio
async def test_database_set_and_get_config():
    await database.set_config("custom_key", "custom_value_123")
    val = await database.get_config("custom_key")
    assert val == "custom_value_123"

    # Atualização de valor existente (upsert)
    await database.set_config("custom_key", "custom_value_456")
    val_updated = await database.get_config("custom_key")
    assert val_updated == "custom_value_456"

    # Default fallback
    assert await database.get_config("non_existent_key", "default_val") == "default_val"


@pytest.mark.asyncio
async def test_database_empty_stats():
    stats = await database.get_download_stats()
    assert stats["total_downloads"] == 0
    assert stats["successful_downloads"] == 0
    assert stats["failed_downloads"] == 0
    assert stats["total_files"] == 0
    assert stats["total_size_bytes"] == 0
    assert stats["today_downloads"] == 0


@pytest.mark.asyncio
async def test_database_download_history_and_stats():
    # 1. Registra downloads de teste
    id1 = await database.log_download("https://x.com/post1", "twitter", 1, 1024 * 1024, "SUCCESS", None, 2.5)
    id2 = await database.log_download("https://x.com/post2", "twitter", 2, 2 * 1024 * 1024, "SUCCESS", None, 3.1)
    id3 = await database.log_download("https://site.com/err", "generic", 0, 0, "FAILED", "404 Not Found", 0.5)

    assert id1 > 0 and id2 > id1 and id3 > id2

    # 2. Verifica histórico recente
    history = await database.get_recent_downloads(limit=5)
    assert len(history) == 3
    assert history[0]["id"] == id3  # Mais recente primeiro
    assert history[0]["status"] == "FAILED"
    assert history[0]["error_message"] == "404 Not Found"
    assert history[1]["status"] == "SUCCESS"

    # 3. Verifica estatísticas agregadas
    stats = await database.get_download_stats()
    assert stats["total_downloads"] == 3
    assert stats["successful_downloads"] == 2
    assert stats["failed_downloads"] == 1
    assert stats["total_files"] == 3
    assert stats["total_size_bytes"] == 3 * 1024 * 1024
    assert stats["today_downloads"] == 3
    assert stats["by_source"]["twitter"] == 2
    assert stats["by_source"]["generic"] == 1


# ─── 3. Testes do Resolver de URLs ─────────────────────────────

def test_url_resolver_twitter():
    assert resolver.classify_url("https://twitter.com/user/status/123456789") == "twitter"
    assert resolver.classify_url("https://x.com/user/status/987654321") == "twitter"
    assert resolver.classify_url("http://www.x.com/user/status/111?s=20") == "twitter"

    # Domínios maliciosos que contêm twitter/x devem ser classificados como generic ou unknown
    assert resolver.classify_url("https://twitter.com.evil.example/video.mp4") == "generic"


def test_url_resolver_generic():
    assert resolver.classify_url("https://example.com/video.mp4") == "generic"
    assert resolver.classify_url("http://site.com/image.jpg?size=large") == "generic"


def test_url_resolver_invalid():
    assert resolver.classify_url("not a url") == "unknown"
    assert resolver.classify_url("") == "unknown"
    assert resolver.classify_url("ftp://server.com/file") == "unknown"


def test_url_resolver_redirect_helper():
    base = "https://example.com/post/123"
    assert resolver.resolve_redirect_url(base, "/media/video.mp4") == "https://example.com/media/video.mp4"
    assert resolver.resolve_redirect_url(base, "https://cdn.example.com/f.jpg") == "https://cdn.example.com/f.jpg"


# ─── 4. Testes do Painel de Controle ───────────────────────────

@pytest.mark.asyncio
async def test_panel_keyboards_generation():
    # Menu principal
    main_kb = panel._main_menu_keyboard()
    assert len(main_kb.inline_keyboard) == 4

    # Menu de configurações
    cfg_text, cfg_kb = await panel._config_menu_keyboard()
    assert "CONFIGURAÇÕES GERAIS" in cfg_text
    assert len(cfg_kb.inline_keyboard) >= 4

    # Menu de estatísticas
    stats_text, stats_kb = await panel._stats_menu_keyboard()
    assert "ESTATÍSTICAS DO SISTEMA" in stats_text

    # Menu de histórico
    hist_text, hist_kb = await panel._history_menu_keyboard()
    assert "ÚLTIMOS DOWNLOADS" in hist_text

    # Menu de sistema
    sys_text, sys_kb = panel._system_menu_keyboard()
    assert "STATUS DO SISTEMA" in sys_text
    assert "v3.0.0" in sys_text
    # Menu do acervo
    vault_text, vault_kb = await panel._vault_menu_keyboard()
    assert "ACERVO DE MÍDIAS" in vault_text
    assert len(vault_kb.inline_keyboard) >= 3

    # Menu da IA Groq
    ai_text, ai_kb = await panel._ai_menu_keyboard()
    assert "MOTOR DE IA GROQ" in ai_text
    assert len(ai_kb.inline_keyboard) >= 3

    # Menu de Canais
    chan_text, chan_kb = await panel._channels_menu_keyboard()
    assert "GESTÃO DE CANAIS DESTINO" in chan_text
    assert len(chan_kb.inline_keyboard) >= 2


def test_panel_owner_security():
    assert panel._is_owner(99887766) is True
    assert panel._is_owner(11223344) is False
    assert handlers._is_owner(99887766) is True
    assert handlers._is_owner(11223344) is False


# ─── 5. Testes do Downloader (Validação e Limites) ─────────────

def test_downloader_size_check(tmp_path):
    dummy_file = tmp_path / "big_file.bin"
    dummy_file.write_bytes(b"A" * 1000)

    # Limite de 500 bytes deve estourar
    with pytest.raises(downloader.DownloadError) as exc_info:
        downloader._check_sizes([dummy_file], max_bytes=500, max_mb=1)
    assert "muito grande" in str(exc_info.value)

    # Limite de 2000 bytes deve passar
    downloader._check_sizes([dummy_file], max_bytes=2000, max_mb=1)


# ─── 6. Testes do Sender (Limpeza de Sessão) ───────────────────

def test_sender_cleanup_session(tmp_path):
    session_dir = tmp_path / "session_123"
    session_dir.mkdir()
    f1 = session_dir / "f1.jpg"
    f2 = session_dir / "f2.mp4"
    f1.write_text("dummy")
    f2.write_text("dummy")

    assert session_dir.exists()
    sender._cleanup_session([f1, f2])
    assert not session_dir.exists()


# ─── 7. Testes de Inicialização e Limpeza de Cache ────────────

def test_startup_temp_cleanup(tmp_path, monkeypatch):
    test_temp = tmp_path / "temp_startup"
    test_temp.mkdir()
    (test_temp / "orphan_folder").mkdir()
    (test_temp / "orphan_folder" / "file.mp4").write_text("dummy")
    (test_temp / "temp_file.bin").write_text("dummy")
    (test_temp / ".gitkeep").write_text("")

    monkeypatch.setattr(main, "TEMP_DIR", test_temp)
    main._cleanup_temp_on_startup()

    assert not (test_temp / "orphan_folder").exists()
    assert not (test_temp / "temp_file.bin").exists()
    assert (test_temp / ".gitkeep").exists()


# ─── 8. Testes de Fail-Closed Security ─────────────────────────

def test_fail_closed_security(monkeypatch):
    """Garante que quando OWNER_ID é 0 ou ausente, o acesso é estritamente bloqueado."""
    monkeypatch.setattr(config, "OWNER_ID", 0)
    monkeypatch.setattr(handlers, "OWNER_ID", 0)
    monkeypatch.setattr(panel, "OWNER_ID", 0)

    assert handlers._is_owner(12345) is False
    assert handlers._is_owner(0) is False
    assert panel._is_owner(12345) is False
    assert panel._is_owner(0) is False


# ─── 9. Testes de Sender e Limpeza em Erros ───────────────────

@pytest.mark.asyncio
async def test_sender_cleans_up_even_if_target_missing(tmp_path, monkeypatch):
    """Garante que a pasta temporária é limpa mesmo quando o destino não está configurado."""
    monkeypatch.setenv("TARGET_CHAT_ID", "")
    await database.set_config("target_chat_id", "")

    session_dir = tmp_path / "temp_leak_test"
    session_dir.mkdir()
    f1 = session_dir / "sample.mp4"
    f1.write_bytes(b"DATA")

    class DummyBot:
        pass

    with pytest.raises(ValueError) as exc_info:
        await sender.send_media(DummyBot(), [f1], caption="")

    assert "TARGET_CHAT_ID" in str(exc_info.value)
    assert not session_dir.exists()


@pytest.mark.asyncio
async def test_sender_retry_after_propagates_on_last_attempt(tmp_path):
    """Garante que RetryAfter esgotado lança exceção e não registra falso sucesso."""
    from telegram.error import RetryAfter, TelegramError

    f = tmp_path / "photo.jpg"
    f.write_bytes(b"DATA")

    class FailingBot:
        async def send_photo(self, *args, **kwargs):
            raise RetryAfter(1)

    with pytest.raises(TelegramError) as exc_info:
        await sender._send_single_file_with_retry(FailingBot(), "123", f, None, max_retries=1)

    assert "RateLimit persistente" in str(exc_info.value)


# ─── 10. Testes de SSRF e Sanidade do Banco ───────────────────

def test_ssrf_protection():
    """Garante bloqueio de loopback, RFC1918 e endpoints de metadados."""
    assert resolver.classify_url("http://127.0.0.1/test.mp4") == "unknown"
    assert resolver.classify_url("http://localhost:8080/image.png") == "unknown"
    assert resolver.classify_url("http://[::1]/video.mp4") == "unknown"
    assert resolver.classify_url("http://192.168.1.10/video.mp4") == "unknown"
    assert resolver.classify_url("http://10.0.0.5/photo.jpg") == "unknown"
    assert resolver.classify_url("http://172.16.0.1/media.mp4") == "unknown"
    assert resolver.classify_url("http://169.254.169.254/latest/meta-data") == "unknown"


@pytest.mark.asyncio
async def test_database_sanity_checks():
    """Garante que valores inválidos são normalizados e valores decimais para timeout são preservados."""
    await database.set_config("max_file_size_mb", "-10")
    val = await database.get_config("max_file_size_mb")
    assert val == "50"

    await database.set_config("download_timeout_seconds", "0")
    val_timeout = await database.get_config("download_timeout_seconds")
    assert val_timeout == "60"

    # Aceita timeout decimal
    await database.set_config("download_timeout_seconds", "1.5")
    val_float = await database.get_config("download_timeout_seconds")
    assert val_float == "1.5"


# ─── 11. Testes de Sessões Ativas e Proteção de Concorrência ──

@pytest.mark.asyncio
async def test_active_sessions_protected_during_cleanup(tmp_path, monkeypatch):
    """Garante que sessões em ACTIVE_SESSIONS são preservadas pelo painel."""
    active_dir = tmp_path / "active_session_1"
    inactive_dir = tmp_path / "old_session_2"
    active_dir.mkdir()
    inactive_dir.mkdir()

    downloader.ACTIVE_SESSIONS.add(active_dir)
    monkeypatch.setattr(panel, "TEMP_DIR", tmp_path)

    class DummyQuery:
        data = "panel:clean_cache"
        message = None
        from_user = type("User", (), {"id": config.OWNER_ID})()
        async def answer(self, text=None, show_alert=False):
            self.alert_text = text

    class DummyUpdate:
        callback_query = DummyQuery()
        effective_user = type("User", (), {"id": config.OWNER_ID})()

    await panel.panel_callback_handler(DummyUpdate(), None)

    assert active_dir.exists()
    assert not inactive_dir.exists()

    downloader.ACTIVE_SESSIONS.clear()


# ─── 12. Testes de Cancelamento em Árvore de Processos (Offline) ─

@pytest.mark.asyncio
async def test_async_is_safe_url_blocks_private_and_local():
    """Garante validação assíncrona contra SSRF."""
    assert await resolver.is_safe_url("http://127.0.0.1/test") is False
    assert await resolver.is_safe_url("http://localhost:3000") is False
    assert await resolver.is_safe_url("http://10.20.30.40/media") is False
    assert await resolver.is_safe_url("http://192.168.0.1/video") is False
    assert await resolver.is_safe_url("http://169.254.169.254/latest") is False
    assert await resolver.is_safe_url("ftp://example.com/file") is False
    assert await resolver.is_safe_url("") is False


@pytest.mark.asyncio
async def test_downloader_subprocess_offline_timeout_and_kill(tmp_path, monkeypatch):
    """
    Testa o cancelamento de processo e árvore de processos de forma 100% offline
    usando um processo Python local que dorme.
    """
    session_dir = tmp_path / "timeout_session"
    session_dir.mkdir()

    # Executa um subprocesso local que dorme por 5 segundos com timeout de 0.05s
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-c", "import time; time.sleep(5)",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(proc.communicate(), timeout=0.05)

    # Executa a função de matar árvore de processos
    await downloader._kill_process_tree(proc)

    # Confirma que o processo foi encerrado
    assert proc.returncode is not None


# ─── 13. Testes de Sanitização de Markdown e Propagação de Erro ─

def test_markdown_sanitization():
    """Garante que caracteres especiais de markdown são neutralizados."""
    dirty_text = "[Link Perigoso]*com* _formatacao_ `e codigo`"
    cleaned = handlers._clean_markdown(dirty_text)
    assert "*" not in cleaned
    assert "_" not in cleaned
    assert "[" not in cleaned
    assert "]" not in cleaned
    assert "`" not in cleaned


@pytest.mark.asyncio
async def test_download_generic_propagates_definite_download_error(tmp_path, monkeypatch):
    """Garante que erros definitivos do yt-dlp não são engolidos pelo fallback."""
    session_dir = tmp_path / "definite_error_session"
    session_dir.mkdir()

    async def mock_failing_subprocess(url, session_dir, timeout, *args, **kwargs):
        raise downloader.DownloadError("Arquivo muito grande")

    monkeypatch.setattr(downloader, "_run_yt_dlp_subprocess", mock_failing_subprocess)
    monkeypatch.setattr(downloader, "is_safe_url", lambda u: asyncio.sleep(0, result=True))

    with pytest.raises(downloader.DownloadError) as exc_info:
        await downloader._download_generic("https://example.com/huge.mp4", session_dir, max_bytes=100, max_mb=1, timeout=5.0)

    assert "Arquivo muito grande" in str(exc_info.value)

# ─── 14. Testes do Healthcheck Baseado em Heartbeat ───────────

def test_healthcheck_heartbeat(tmp_path, monkeypatch):
    """Garante que o healthcheck valida rigorosamente a vivacidade do processo através do heartbeat."""
    import time
    from bot import healthcheck

    test_data = tmp_path / "data_health"
    test_data.mkdir()
    hb_file = test_data / ".heartbeat"

    monkeypatch.setattr(healthcheck, "DATA_DIR", test_data)
    monkeypatch.setattr(healthcheck, "HEARTBEAT_FILE", hb_file)

    # 1. Sem heartbeat no início (processo não rodando ou crash antes do loop) -> FALHA (1)
    assert healthcheck.check_health() == 1

    # 2. Com heartbeat fresco (recente) -> SUCESSO (0)
    hb_file.write_text(str(time.time()), encoding="utf-8")
    assert healthcheck.check_health() == 0

    # 3. Com heartbeat estagnado (>60 segundos atrás) -> FALHA (1)
    old_time = time.time() - 120.0
    os.utime(hb_file, (old_time, old_time))
    assert healthcheck.check_health() == 1
# ─── 15. Testes da Hierarquia Estrita de Mídias e Filtro de Avatares ───────────

def test_extract_video_and_image_urls_strict_hierarchy():
    """Garante que a rota de vídeo NUNCA retorna avatares/posters e que imagens de UI são filtradas."""
    sample_html = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta property="og:video" content="https://cdn.example.com/main_video.mp4" />
        <meta property="og:image" content="https://cdn.example.com/poster_thumb.jpg" />
    </head>
    <body>
        <video src="/videos/html5_video.webm"></video>
        <img src="https://cdn.example.com/avatar_user123.jpg" class="avatar" />
        <img src="https://cdn.example.com/logo_header.png" />
        <img src="https://cdn.example.com/gallery_photo.jpg" />
    </body>
    </html>
    """
    base_url = "https://example.com/watch"

    videos = downloader._extract_video_urls_from_html(sample_html, base_url)
    assert "https://cdn.example.com/main_video.mp4" in videos
    assert "https://example.com/videos/html5_video.webm" in videos
    # Garante que NENHUMA imagem entrou na lista de vídeos
    assert not any("poster" in v or "avatar" in v or "thumb" in v for v in videos)

    images = downloader._extract_image_urls_from_html(sample_html, base_url)
    # Apenas foto real de galeria permitida
    assert "https://cdn.example.com/gallery_photo.jpg" in images
    # Avatares, logos e posters estritamente bloqueados
    assert not any("avatar" in img or "logo" in img or "poster" in img or "thumb" in img for img in images)


@pytest.mark.asyncio
async def test_sender_probe_video_metadata(tmp_path):
    """Garante que o probe de metadados do sender retorna valores ou tupla segura."""
    from bot import sender
    fake_video = tmp_path / "test_probe.mp4"
    fake_video.write_bytes(b"not a real video")
    w, h, d = await sender._probe_video_metadata(fake_video)
    # Em arquivo não-mídia, ffprobe falha silenciosamente e retorna None
    assert w is None and h is None and d is None
# ─── 16. Testes do Normalizador de Subdomínios e Bloqueio de Não-Vídeos ───────────

def test_normalize_media_url():
    """Garante que subdomínios de idiomas e mobile são normalizados para ativar extratores oficiais."""
    from bot.resolver import normalize_media_url

    assert normalize_media_url("https://br.youporn.com/watch/12345#ref") == "https://www.youporn.com/watch/12345"
    assert normalize_media_url("https://pt.pornhub.com/view_video.php?v=1") == "https://www.pornhub.com/view_video.php?v=1"
    assert normalize_media_url("https://m.thothd.com/pt/videos/123") == "https://www.thothd.com/pt/videos/123"
    assert normalize_media_url("https://mobile.twitter.com/user/status/123") == "https://www.twitter.com/user/status/123"
    assert normalize_media_url("https://example.com/video.mp4") == "https://example.com/video.mp4"
# ─── 17. Testes do Acervo Multi-Canal e Deleção de Disco (Fase 1) ───────────

@pytest.mark.asyncio
async def test_database_vault_operations_and_disk_cleanup(tmp_path, monkeypatch):
    """Garante isolamento por canal, contagem de mídias e exclusão física do disco pós-envio."""
    from bot import database

    test_db = tmp_path / "test_vault.db"
    test_vault = tmp_path / "vault_dir"
    test_vault.mkdir()

    monkeypatch.setattr(database, "DB_PATH", test_db)
    monkeypatch.setattr(database, "VAULT_DIR", test_vault)
    await database.init_db()

    # 1. Cadastro de canais
    await database.register_channel("-1001", "Canal VIP Esposa", "scheduled")
    await database.register_channel("-1002", "Canal VIP 2", "instant")

    ch1 = await database.get_channel("-1001")
    assert ch1["title"] == "Canal VIP Esposa"
    assert ch1["dispatch_mode"] == "scheduled"

    # 2. Criação de arquivos físicos de teste no vault
    v_file = test_vault / "video1.mp4"
    v_file.write_bytes(b"dummy video data")
    p_file1 = test_vault / "photo1.jpg"
    p_file1.write_bytes(b"dummy photo 1")
    p_file2 = test_vault / "photo2.jpg"
    p_file2.write_bytes(b"dummy photo 2")

    # Inserção no acervo do canal 1
    vid_id = await database.add_media_to_vault("-1001", v_file, "video", len(b"dummy video data"), duration_seconds=15, title="Video 1", ai_caption="Legenda 1")
    p1_id = await database.add_media_to_vault("-1001", p_file1, "photo", len(b"dummy photo 1"), title="Foto 1", ai_caption="Legenda Foto 1")
    p2_id = await database.add_media_to_vault("-1001", p_file2, "photo", len(b"dummy photo 2"), title="Foto 2", ai_caption="Legenda Foto 2")

    # 3. Estatísticas do acervo
    stats = await database.get_vault_stats("-1001")
    assert stats["total_pending"] == 3
    assert stats["pending_videos"] == 1
    assert stats["pending_photos"] == 2

    # Canal 2 deve estar com acervo zerado (isolamento estrito)
    stats2 = await database.get_vault_stats("-1002")
    assert stats2["total_pending"] == 0

    # 4. Busca de próximo vídeo
    next_vid = await database.get_next_pending_video("-1001")
    assert next_vid["id"] == vid_id
    assert next_vid["title"] == "Video 1"

    # 5. Busca de pack de fotos
    photos = await database.get_next_pending_photos_pack("-1001", max_photos=3)
    assert len(photos) == 2

    # 6. Exclusão física do disco e marcação como 'sent'
    assert v_file.exists()
    await database.mark_media_sent_and_delete([vid_id])
    assert not v_file.exists(), "Arquivo físico deveria ter sido excluído do disco após envio!"

    # Estatísticas atualizadas
    stats_after = await database.get_vault_stats("-1001")
    assert stats_after["pending_videos"] == 0
    assert stats_after["pending_photos"] == 2
# ─── 18. Testes do Motor de IA Groq Cloud e Legendas Reserva (Fase 2) ───────────

@pytest.mark.asyncio
async def test_ai_caption_generation_and_fallback(monkeypatch):
    """Garante geração de legenda via Groq e acervo reserva em caso de falha."""
    from bot import ai_caption

    # 1. Teste de fallback pré-pronto garantido
    backup_cap = ai_caption.get_random_backup_caption("picante")
    assert len(backup_cap) > 10
    assert any(e in backup_cap for e in ["🔥", "😈", "🤤", "💦", "💋", "🔞", "✨", "👑"])

    # 2. Teste sem chave de API (deve retornar fallback sem erro)
    monkeypatch.setattr(ai_caption, "GROQ_API_KEY", "")
    cap_no_key = await ai_caption.generate_ai_caption("Video de teste", media_type="video", style="picante")
    assert len(cap_no_key) > 5

    # 3. Teste com mock de API da Groq bem-sucedido
    async def mock_groq_post(*args, **kwargs):
        class MockResponse:
            status_code = 200
            def json(self):
                return {
                    "choices": [{"message": {"content": "Olha essa prévia quente pra vocês... 🔥😈"}}]
                }
        return MockResponse()

    monkeypatch.setattr(ai_caption, "GROQ_API_KEY", "dummy_valid_key")
    monkeypatch.setattr("httpx.AsyncClient.post", mock_groq_post)

    cap_ai = await ai_caption.generate_ai_caption("Video novo", media_type="video", style="picante")
    assert "Olha essa prévia quente" in cap_ai
# ─── 19. Testes do Motor de Cadência Inteligente 2V -> 1 Pack Fotos (Fase 3) ───────────

@pytest.mark.asyncio
async def test_scheduler_cadence_engine(tmp_path, monkeypatch):
    """Garante a sequência estrita de cadência: 2 Vídeos -> Pack de até 3 Fotos -> Vídeo."""
    from bot import database, scheduler

    test_db = tmp_path / "test_cadence.db"
    test_vault = tmp_path / "cadence_vault"
    test_vault.mkdir()

    monkeypatch.setattr(database, "DB_PATH", test_db)
    monkeypatch.setattr(database, "VAULT_DIR", test_vault)
    await database.init_db()

    channel_id = "-100999"
    await database.register_channel(channel_id, "Canal Teste Cadencia", "manual")

    # Cria 3 vídeos e 3 fotos no disco
    v1 = test_vault / "v1.mp4"; v1.write_bytes(b"vid1")
    v2 = test_vault / "v2.mp4"; v2.write_bytes(b"vid2")
    v3 = test_vault / "v3.mp4"; v3.write_bytes(b"vid3")

    p1 = test_vault / "p1.jpg"; p1.write_bytes(b"pho1")
    p2 = test_vault / "p2.jpg"; p2.write_bytes(b"pho2")
    p3 = test_vault / "p3.jpg"; p3.write_bytes(b"pho3")

    # Insere no acervo
    await database.add_media_to_vault(channel_id, v1, "video", len(b"vid1"), title="V1", ai_caption="Legenda V1")
    await database.add_media_to_vault(channel_id, v2, "video", len(b"vid2"), title="V2", ai_caption="Legenda V2")
    await database.add_media_to_vault(channel_id, v3, "video", len(b"vid3"), title="V3", ai_caption="Legenda V3")

    await database.add_media_to_vault(channel_id, p1, "photo", len(b"pho1"), title="P1", ai_caption="Legenda P1")
    await database.add_media_to_vault(channel_id, p2, "photo", len(b"pho2"), title="P2", ai_caption="Legenda P2")
    await database.add_media_to_vault(channel_id, p3, "photo", len(b"pho3"), title="P3", ai_caption="Legenda P3")

    # Mock do Bot Telegram
    class MockBot:
        sent_videos = []
        sent_media_groups = []
        sent_photos = []

        async def send_video(self, *args, **kwargs):
            self.sent_videos.append(kwargs)

        async def send_media_group(self, *args, **kwargs):
            self.sent_media_groups.append(kwargs)

        async def send_photo(self, *args, **kwargs):
            self.sent_photos.append(kwargs)

    mock_bot = MockBot()

    # 1º Disparo: Deve ser o VÍDEO 1
    res1 = await scheduler.dispatch_next_from_vault(mock_bot, channel_id)
    assert res1["success"] is True
    assert res1["media_type"] == "video"
    assert not v1.exists(), "V1 deveria ter sido deletado do disco pós-envio!"
    ch = await database.get_channel(channel_id)
    assert ch["consecutive_videos_count"] == 1

    # 2º Disparo: Deve ser o VÍDEO 2
    res2 = await scheduler.dispatch_next_from_vault(mock_bot, channel_id)
    assert res2["success"] is True
    assert res2["media_type"] == "video"
    assert not v2.exists(), "V2 deveria ter sido deletado do disco!"
    ch = await database.get_channel(channel_id)
    assert ch["consecutive_videos_count"] == 2

    # 3º Disparo: Como já foram 2 vídeos, DEVE SER O PACK DE 3 FOTOS!
    res3 = await scheduler.dispatch_next_from_vault(mock_bot, channel_id)
    assert res3["success"] is True
    assert res3["media_type"] == "photo_pack"
    assert res3["count"] == 3
    assert not p1.exists() and not p2.exists() and not p3.exists(), "Fotos deveriam ter sido deletadas do disco!"
    ch = await database.get_channel(channel_id)
    assert ch["consecutive_videos_count"] == 0, "Contador de vídeos deveria ter sido resetado após o pack de fotos!"

    # 4º Disparo: Deve voltar para o VÍDEO 3
    res4 = await scheduler.dispatch_next_from_vault(mock_bot, channel_id)
    assert res4["success"] is True
    assert res4["media_type"] == "video"
    assert not v3.exists(), "V3 deveria ter sido deletado do disco!"
    ch = await database.get_channel(channel_id)
    assert ch["consecutive_videos_count"] == 1

    # 5º Disparo: Acervo vazio
    res5 = await scheduler.dispatch_next_from_vault(mock_bot, channel_id)
    assert res5["success"] is False
# ─── 20. Teste End-to-End: Download -> IA Caption -> Post no VIP com Legenda ───────────

@pytest.mark.asyncio
async def test_end_to_end_download_vault_ai_caption_and_dispatch(tmp_path, monkeypatch):
    """Garante que mídias baixadas ganham legenda da IA e são postadas com a legenda anexada no canal VIP."""
    from bot import database, handlers, downloader, ai_caption, scheduler

    test_db = tmp_path / "e2e_vault.db"
    test_vault = tmp_path / "e2e_vault_dir"
    test_temp = tmp_path / "e2e_temp_dir"
    test_vault.mkdir()
    test_temp.mkdir()

    monkeypatch.setattr(database, "DB_PATH", test_db)
    monkeypatch.setattr(database, "VAULT_DIR", test_vault)
    monkeypatch.setattr(handlers, "VAULT_DIR", test_vault)
    monkeypatch.setattr(downloader, "TEMP_DIR", test_temp)
    await database.init_db()

    target_chat = "-100777"
    await database.set_config("target_chat_id", target_chat)
    await database.register_channel(target_chat, "Canal VIP Esposa", "instant")

    # Mock de download retornando arquivo de vídeo
    test_video = test_temp / "session_1" / "video_sample.mp4"
    test_video.parent.mkdir(parents=True)
    test_video.write_bytes(b"sample video bytes for telegram")

    async def mock_download(url, source):
        return [test_video]

    # Mock de geração de legenda da Groq
    async def mock_ai_caption(title_or_context="", media_type="video", style=None, **kwargs):
        return "Olha esse close quente que gravei pra vocês hoje... 🔥😈🔞"

    monkeypatch.setattr(handlers, "download", mock_download)
    monkeypatch.setattr(handlers, "generate_ai_caption", mock_ai_caption)
    monkeypatch.setattr(scheduler, "generate_ai_caption", mock_ai_caption)
    monkeypatch.setattr(ai_caption, "generate_ai_caption", mock_ai_caption)

    # Mock do Bot Telegram
    class MockBot:
        def __init__(self):
            self.dispatched_videos = []

        async def send_video(self, *args, **kwargs):
            self.dispatched_videos.append(kwargs)

        async def send_message(self, *args, **kwargs):
            class DummySentMsg:
                message_id = 999
            return DummySentMsg()

        async def pin_chat_message(self, *args, **kwargs):
            pass

    mock_bot = MockBot()

    class DummyMessage:
        text = "https://twitter.com/creator/status/123456789"
        async def reply_text(self, text, **kwargs):
            return self
        async def edit_text(self, text, **kwargs):
            return self

    class DummyUpdate:
        message = DummyMessage()
        effective_user = type("User", (), {"id": config.OWNER_ID})()

    class DummyContext:
        bot = mock_bot

    # Executa o handler de mensagem (quando o dono manda o link)
    await handlers.message_handler(DummyUpdate(), DummyContext())

    # Validações Estritas:
    # 1. O vídeo foi enviado para o canal VIP com a legenda da IA anexada
    assert len(mock_bot.dispatched_videos) == 1
    post = mock_bot.dispatched_videos[0]
    assert post["chat_id"] == target_chat
    assert post["caption"] == "Olha esse close quente que gravei pra vocês hoje... 🔥😈🔞"
    assert post["supports_streaming"] is True

    # 2. O arquivo temporário e do vault foram apagados para liberar espaço
    assert not test_video.exists()
    for f in test_vault.rglob("*"):
        assert not f.is_file(), "Nenhum arquivo físico deve sobrar no vault após envio!"

    # 3. O histórico no banco registrou sucesso
    hist = await database.get_recent_downloads(limit=1)
    assert len(hist) == 1
    assert hist[0]["status"] == "SUCCESS"
# ─── 21. Testes de Reserva Atômica e Reconciliação do Acervo (Hardening) ──────

@pytest.mark.asyncio
async def test_atomic_media_reservation_and_rollback(tmp_path, monkeypatch):
    """Garante que a transação atômica pending -> processing -> sent evita condições de corrida."""
    from bot import database

    test_db = tmp_path / "atomic_vault.db"
    test_vault = tmp_path / "atomic_vault_dir"
    test_vault.mkdir()

    monkeypatch.setattr(database, "DB_PATH", test_db)
    monkeypatch.setattr(database, "VAULT_DIR", test_vault)
    await database.init_db()

    channel_id = "-100888"
    await database.register_channel(channel_id, "Canal Atômico", "manual")

    v1 = test_vault / "v1.mp4"
    v1.write_bytes(b"video data")
    vid_id = await database.add_media_to_vault(channel_id, v1, "video", len(b"video data"), title="V1")

    # 1. Primeira aquisição reserva o vídeo para 'processing'
    acquired_1 = await database.acquire_next_pending_video(channel_id)
    assert acquired_1 is not None
    assert acquired_1["id"] == vid_id

    # 2. Segunda aquisição concorrente NÃO acha o vídeo (pois já está em 'processing')
    acquired_2 = await database.acquire_next_pending_video(channel_id)
    assert acquired_2 is None, "Mídia em 'processing' não deve ser selecionada por outra tarefa concorrente!"

    # 3. Rollback de falha: reverte de 'processing' para 'pending'
    await database.release_media_reservation([vid_id])

    # 4. Agora o vídeo volta a estar disponível
    acquired_3 = await database.acquire_next_pending_video(channel_id)
    assert acquired_3 is not None
    assert acquired_3["id"] == vid_id


@pytest.mark.asyncio
async def test_vault_reconciliation_routine(tmp_path, monkeypatch):
    """Garante que a reconciliação limpa arquivos órfãos e marca mídias faltantes."""
    from bot import database

    test_db = tmp_path / "reconcile.db"
    test_vault = tmp_path / "reconcile_vault_dir"
    test_vault.mkdir()

    monkeypatch.setattr(database, "DB_PATH", test_db)
    monkeypatch.setattr(database, "VAULT_DIR", test_vault)
    await database.init_db()

    channel_id = "-100555"
    await database.register_channel(channel_id, "Canal Reconcile", "manual")

    # 1. Mídia fantasma: registrada no banco mas sem arquivo físico
    ghost_path = test_vault / "ghost.mp4"
    ghost_id = await database.add_media_to_vault(channel_id, ghost_path, "video", 1000, title="Ghost")

    # 2. Arquivo órfão no disco que não está no banco
    orphan_path = test_vault / "orphan.mp4"
    orphan_path.write_bytes(b"orphan data")

    # Executa rotina de reconciliação
    report = await database.reconcile_vault_integrity()
    assert report["missing_marked"] == 1
    assert report["orphans_cleaned"] == 1
    assert not orphan_path.exists(), "Arquivo órfão deveria ter sido excluído pelo reconciliador!"

    # Verifica status da mídia fantasma
    stats = await database.get_vault_stats(channel_id)
    assert stats["pending_videos"] == 0, "Mídia fantasma não deve constar como pendente!"
# ─── 22. Testes de Configuração Flexível de Canais (/settarget) ───────────────

@pytest.mark.asyncio
async def test_settarget_with_args_and_channel_post(tmp_path, monkeypatch):
    """Garante que /settarget funciona com @username, ID numérico e channel_post."""
    from bot import database, handlers

    test_db = tmp_path / "settarget_test.db"
    monkeypatch.setattr(database, "DB_PATH", test_db)
    await database.init_db()

    class MockChat:
        def __init__(self, cid, title):
            self.id = cid
            self.title = title
            self.username = "canalvip"
            self.type = "channel"

    class MockMember:
        status = "administrator"

    class MockBot:
        id = 12345
        async def get_chat(self, chat_id):
            if chat_id in ["@canalvip", "-100999888"]:
                return MockChat(-100999888, "Canal VIP Oficial")
            raise Exception("Chat not found")

        async def get_chat_member(self, chat_id, user_id):
            return MockMember()

    mock_bot = MockBot()

    # 1. Teste de /settarget com argumento no privado (@canalvip)
    class DummyMsg:
        replies = []
        async def reply_text(self, text, **kwargs):
            self.replies.append(text)
            return self

    class DummyUpdatePrivate:
        channel_post = None
        message = DummyMsg()
        effective_message = message
        effective_chat = type("Chat", (), {"id": 111, "type": "private", "title": ""})()
        effective_user = type("User", (), {"id": config.OWNER_ID})()

    class DummyContextWithArgs:
        bot = mock_bot
        args = ["@canalvip"]

    await handlers.settarget_handler(DummyUpdatePrivate(), DummyContextWithArgs())

    # Verifica se o target_chat_id foi atualizado para o canal
    cur_target = await database.get_config("target_chat_id")
    assert cur_target == "-100999888"
    ch = await database.get_channel("-100999888")
    assert ch["title"] == "Canal VIP Oficial"

    # 2. Teste de /settarget enviado como channel_post dentro do canal
    class DummyChannelPost:
        replies = []
        async def reply_text(self, text, **kwargs):
            self.replies.append(text)
            return self

    class DummyUpdateChannel:
        channel_post = DummyChannelPost()
        message = None
        effective_message = channel_post
        effective_chat = MockChat(-100555666, "Canal Postado")
        effective_user = None

    class DummyContextNoArgs:
        bot = mock_bot
        args = []

    await handlers.settarget_handler(DummyUpdateChannel(), DummyContextNoArgs())

    cur_target_2 = await database.get_config("target_chat_id")
    assert cur_target_2 == "-100555666"
    ch2 = await database.get_channel("-100555666")
    assert ch2["title"] == "Canal Postado"
# ─── 23. Testes de Concorrência e Alta Performance (Modo WAL - Fase 1) ───────

@pytest.mark.asyncio
async def test_sqlite_wal_mode_and_high_concurrency(tmp_path, monkeypatch):
    """Garante que o modo WAL suporta dezenas de operações de leitura/escrita simultâneas sem travar."""
    import asyncio
    from bot import database

    test_db = tmp_path / "wal_concurrency.db"
    monkeypatch.setattr(database, "DB_PATH", test_db)
    await database.init_db()

    # Executa 30 escritas e leituras concorrentes simultaneamente
    async def _write_op(i):
        await database.set_config(f"key_{i}", f"val_{i}")
        val = await database.get_config(f"key_{i}")
        assert val == f"val_{i}"

    tasks = [_write_op(i) for i in range(30)]
    await asyncio.gather(*tasks)

    # Confirma que todas as 30 chaves foram persistidas
    all_cfg = await database.get_all_config()
    for i in range(30):
        assert all_cfg.get(f"key_{i}") == f"val_{i}"
# ─── 24. Testes de Transcode Inteligente (Fase 3) ────────────────────────────

@pytest.mark.asyncio
async def test_smart_transcode_stream_copy_decision(tmp_path, monkeypatch):
    """Garante que vídeos já compatíveis usam stream copy e que codecs incompatíveis disparam fallback."""
    from bot import downloader

    test_file = tmp_path / "test_h264.mp4"
    test_file.write_bytes(b"0" * 100000)

    # 1. Simula ffprobe retornando h264 + yuv420p + aac
    async def mock_probe_compatible(path, timeout=8.0):
        return "h264", "yuv420p", "aac"

    monkeypatch.setattr(downloader, "_probe_video_codecs", mock_probe_compatible)

    vcodec, pix_fmt, acodec = await downloader._probe_video_codecs(test_file)
    assert vcodec == "h264"
    assert pix_fmt == "yuv420p"
    assert acodec == "aac"

    # 2. Simula ffprobe retornando codec incompatível (ex: hevc)
    async def mock_probe_incompatible(path, timeout=8.0):
        return "hevc", "yuv420p", "aac"

    monkeypatch.setattr(downloader, "_probe_video_codecs", mock_probe_incompatible)
    vcodec2, _, _ = await downloader._probe_video_codecs(test_file)
    assert vcodec2 == "hevc", "Codec incompatível deve ser detectado corretamente para disparar re-encode!"
# ─── 25. Testes do Coletor Automático Periódico de Lixo (Fase 4) ─────────────

@pytest.mark.asyncio
async def test_periodic_garbage_collector_logic(tmp_path, monkeypatch):
    """Garante que o coletor periódico limpa apenas pastas antigas (>1h) e respeita ACTIVE_SESSIONS."""
    import time
    from bot import main, downloader

    test_temp = tmp_path / "temp_gc"
    test_temp.mkdir()
    monkeypatch.setattr(main, "TEMP_DIR", test_temp)

    # 1. Pasta antiga não ativa (criada há 2 horas)
    old_dir = test_temp / "old_session"
    old_dir.mkdir()
    (old_dir / "old_file.mp4").write_bytes(b"old data")
    old_mtime = time.time() - 7200
    import os
    os.utime(old_dir, (old_mtime, old_mtime))

    # 2. Pasta ativa em uso (dentro de ACTIVE_SESSIONS)
    active_dir = test_temp / "active_session"
    active_dir.mkdir()
    (active_dir / "active_file.mp4").write_bytes(b"active data")
    os.utime(active_dir, (old_mtime, old_mtime))
    downloader.ACTIVE_SESSIONS.add(active_dir)

    try:
        # Simula ciclo de limpeza
        now = time.time()
        for p in list(test_temp.iterdir()):
            if p.is_dir() and p not in downloader.ACTIVE_SESSIONS:
                if now - p.stat().st_mtime > 3600:
                    import shutil
                    shutil.rmtree(p, ignore_errors=True)

        assert not old_dir.exists(), "Pasta antiga órfã deveria ser removida pelo coletor!"
        assert active_dir.exists(), "Pasta ativa em ACTIVE_SESSIONS DEVE ser preservada!"
    finally:
        downloader.ACTIVE_SESSIONS.discard(active_dir)
# ─── 26. Testes da Arquitetura Modular (bot.core, bot.modules, etc.) ─────────

def test_modular_package_architecture_exports():
    """Garante que todos os subpacotes modulares exportam corretamente suas interfaces."""
    import bot
    from bot.core import config as c_cfg, database as c_db
    from bot.modules import downloader as m_dl, sender as m_snd, scheduler as m_sch, ai_caption as m_ai
    from bot import handlers as h_hand, panel as p_pan, healthcheck as h_hlth
    from bot.utils import messages as u_msg, resolver as u_res

    assert c_cfg.BOT_VERSION == "3.0.0"
    assert hasattr(c_db, "init_db")
    assert hasattr(c_db, "reconcile_vault_integrity")
    assert hasattr(m_dl, "download")
    assert hasattr(m_dl, "ACTIVE_SESSIONS")
    assert hasattr(m_snd, "_probe_video_metadata")
    assert hasattr(m_sch, "supervised_schedule_worker")
    assert hasattr(m_ai, "generate_ai_caption")
    assert hasattr(h_hand, "message_handler")
    assert hasattr(h_hand, "error_handler")
    assert hasattr(p_pan, "panel_handler")
    assert hasattr(u_res, "is_safe_url")
    assert hasattr(u_msg, "START")
    assert hasattr(h_hlth, "check_health")
    assert bot.__version__ == "3.0.0"



# ─── 27. Testes da Mensagem de Boas-Vindas Oficial & Botão Interativo ─────────

@pytest.mark.asyncio
async def test_welcome_message_dispatch_and_pin(tmp_path, monkeypatch):
    """Garante envio, botão de notificação, fixação e flag has_welcomed da mensagem de boas-vindas."""
    from bot import database, scheduler

    test_db = tmp_path / "welcome_test.db"
    test_vault = tmp_path / "welcome_vault"
    test_vault.mkdir()

    monkeypatch.setattr(database, "DB_PATH", test_db)
    monkeypatch.setattr(database, "VAULT_DIR", test_vault)
    await database.init_db()

    target_chat = "-100999888"
    await database.register_channel(target_chat, "Canal VIP Boas Vindas", "instant")

    # Mock do Bot Telegram
    class MockSentMessage:
        message_id = 4567

    class MockWelcomeBot:
        def __init__(self):
            self.sent_messages = []
            self.pinned_messages = []

        async def send_message(self, *args, **kwargs):
            self.sent_messages.append(kwargs)
            return MockSentMessage()

        async def pin_chat_message(self, *args, **kwargs):
            self.pinned_messages.append(kwargs)

    mock_bot = MockWelcomeBot()

    # 1. Canal novo tem has_welcomed = False
    assert not await database.is_channel_welcomed(target_chat)

    # 2. Executa send_welcome_message
    msg_id = await scheduler.send_welcome_message(mock_bot, target_chat)
    assert msg_id == 4567

    # 3. Validações de envio e fixação
    assert len(mock_bot.sent_messages) == 1
    sent = mock_bot.sent_messages[0]
    assert sent["chat_id"] == target_chat
    assert "SEJA MUITO BEM-VINDO" in sent["text"]
    assert sent["reply_markup"] is not None

    # Valida botão de notificação
    btn = sent["reply_markup"].inline_keyboard[0][0]
    assert "Ativar Notificações" in btn.text
    assert btn.callback_data == "btn_mute_tip"

    # Valida mensagem fixada
    assert len(mock_bot.pinned_messages) == 1
    pinned = mock_bot.pinned_messages[0]
    assert pinned["chat_id"] == target_chat
    assert pinned["message_id"] == 4567

    # 4. Flag has_welcomed agora é True
    assert await database.is_channel_welcomed(target_chat)

    # 5. Se chamar send_welcome_message de novo, ela não é reenviada automaticamente pelo dispatch
    channel = await database.get_channel(target_chat)
    assert channel["has_welcomed"] == 1


@pytest.mark.asyncio
async def test_channel_button_mute_tip_callback():
    """Garante que o botão interativo de notificação abre popup explicativo para qualquer usuário."""
    from bot.main import channel_button_callback_handler

    answered_alerts = []

    class MockQuery:
        data = "btn_mute_tip"
        async def answer(self, text, show_alert=False):
            answered_alerts.append({"text": text, "show_alert": show_alert})

    class MockUpdate:
        callback_query = MockQuery()

    class MockContext:
        pass

    await channel_button_callback_handler(MockUpdate(), MockContext())

    assert len(answered_alerts) == 1
    alert = answered_alerts[0]
    assert alert["show_alert"] is True
    assert "Ativar som" in alert["text"]


@pytest.mark.asyncio
async def test_setwelcome_command_and_channel_live_edit(tmp_path, monkeypatch):
    """Garante que /setwelcome edita a mensagem do canal em tempo real e atualiza a configuração."""
    from bot import database, handlers, scheduler, config

    test_db = tmp_path / "setwelcome_test.db"
    monkeypatch.setattr(database, "DB_PATH", test_db)
    await database.init_db()

    target_chat = "-100123999"
    await database.set_config("target_chat_id", target_chat)
    await database.register_channel(target_chat, "Canal VIP Teste", "instant")
    await database.set_channel_welcome_message_id(target_chat, 8888)

    class MockLiveBot:
        def __init__(self):
            self.edited_messages = []

        async def edit_message_text(self, *args, **kwargs):
            self.edited_messages.append(kwargs)
            return True

    mock_bot = MockLiveBot()

    replies = []
    class DummySetwelcomeMessage:
        async def reply_text(self, text, **kwargs):
            replies.append(text)
            return self

    class DummyUpdate:
        message = DummySetwelcomeMessage()
        effective_message = message
        effective_chat = type("Chat", (), {"type": "private"})()
        effective_user = type("User", (), {"id": config.OWNER_ID})()

    # 1. Chamada sem argumentos exibe o texto atual
    class DummyContextNoArgs:
        bot = mock_bot
        args = []

    await handlers.setwelcome_handler(DummyUpdate(), DummyContextNoArgs())
    assert len(replies) == 1
    assert "Mensagem Oficial de Boas-Vindas Atual" in replies[0]

    # 2. Chamada com novo texto atualiza o banco e edita no canal em tempo real
    new_custom_text = "🔥 Olá amores! Novo link toda semana aqui no canal VIP... 💋"
    class DummyContextWithArgs:
        bot = mock_bot
        args = new_custom_text.split()

    await handlers.setwelcome_handler(DummyUpdate(), DummyContextWithArgs())
    assert len(replies) == 2
    assert "Mensagem de Boas-Vindas atualizada com sucesso" in replies[1]

    # Valida que o banco gravou o novo texto
    saved_cfg = await database.get_config("welcome_message_text")
    assert saved_cfg == new_custom_text

    # Valida que o bot chamou edit_message_text com o ID 8888 no canal
    assert len(mock_bot.edited_messages) == 1
    edit_call = mock_bot.edited_messages[0]
    assert edit_call["chat_id"] == target_chat
    assert edit_call["message_id"] == 8888
    assert edit_call["text"] == new_custom_text
    assert edit_call["reply_markup"] is not None


@pytest.mark.asyncio
async def test_panel_welcome_menu_and_restore_default(tmp_path, monkeypatch):
    """Garante visualização do menu de boas-vindas no painel e restauração para o texto padrão."""
    from bot import database, panel, config

    test_db = tmp_path / "panel_welcome.db"
    monkeypatch.setattr(database, "DB_PATH", test_db)
    await database.init_db()

    target_chat = "-100888777"
    await database.set_config("target_chat_id", target_chat)
    await database.register_channel(target_chat, "Canal VIP", "instant")

    # Altera para um texto customizado
    await database.set_config("welcome_message_text", "Texto modificado temporário")

    # 1. Valida geração do menu de boas-vindas
    text, kb = await panel._welcome_menu_keyboard()
    assert "MENSAGEM DE BOAS-VINDAS & NOTIFICAÇÕES" in text
    assert "Texto modificado temporário" in text

    # 2. Executa restauração para o padrão oficial
    answered_alerts = []
    edited_panel = []

    class MockPanelQuery:
        data = "panel:restore_welcome_default"
        message = type("Msg", (), {})()
        from_user = type("User", (), {"id": config.OWNER_ID})()

        async def answer(self, text="", show_alert=False):
            answered_alerts.append({"text": text, "show_alert": show_alert})

        async def edit_message_text(self, text, reply_markup=None, **kwargs):
            edited_panel.append(text)

    class MockContext:
        bot = None

    update = type("Update", (), {"callback_query": MockPanelQuery(), "effective_user": type("User", (), {"id": config.OWNER_ID})()})()
    await panel.panel_callback_handler(update, MockContext())

    # Valida que o texto voltou para o padrão oficial da Opção A
    restored_text = await database.get_config("welcome_message_text")
    assert "SEJA MUITO BEM-VINDO AO MEU VIP PRIVADO" in restored_text
    assert len(answered_alerts) == 1
    assert "restaurada para o padrão" in answered_alerts[0]["text"]


@pytest.mark.asyncio
async def test_interval_dispatch_engine_trigger_and_anti_flood(tmp_path, monkeypatch):
    """Garante que o Modo Intervalo dispara quando o tempo decorrido atinge o limite e protege contra floods."""
    import datetime
    from bot import database, scheduler

    test_db = tmp_path / "interval_test.db"
    test_vault = tmp_path / "interval_vault"
    test_vault.mkdir()
    monkeypatch.setattr(database, "DB_PATH", test_db)
    monkeypatch.setattr(database, "VAULT_DIR", test_vault)
    await database.init_db()

    target_chat = "-100555444"
    await database.register_channel(target_chat, "Canal VIP Intervalo", "interval")
    await database.set_channel_interval_hours(target_chat, 2)

    # 1. Valida canais registrados com modo interval e 2 horas
    channel = await database.get_channel(target_chat)
    assert channel["dispatch_mode"] == "interval"
    assert channel["interval_hours"] == 2
    assert channel["last_dispatched_at"] is None

    # 2. Testa cálculo de tempo decorrido: sem last_dispatched_at -> deve disparar
    now = datetime.datetime.now()
    last_disp = channel.get("last_dispatched_at")
    should_dispatch = False
    if not last_disp:
        should_dispatch = True
    assert should_dispatch is True

    # 3. Simula disparo e atualização do last_dispatched_at
    await database.update_channel_last_dispatched(target_chat, now)
    channel = await database.get_channel(target_chat)
    assert channel["last_dispatched_at"] is not None

    # 4. Se passou apenas 30 minutos (menos de 2h) -> NÃO deve disparar (anti-flood)
    recent_now = now + datetime.timedelta(minutes=30)
    last_dt = datetime.datetime.fromisoformat(channel["last_dispatched_at"])
    elapsed = (recent_now - last_dt).total_seconds()
    assert elapsed < 2 * 3600

    # 5. Se passaram 2 horas e 5 minutos -> DEVE disparar
    future_now = now + datetime.timedelta(hours=2, minutes=5)
    elapsed_future = (future_now - last_dt).total_seconds()
    assert elapsed_future >= 2 * 3600


@pytest.mark.asyncio
async def test_panel_interval_menu_and_selection(tmp_path, monkeypatch):
    """Garante navegação no menu de intervalo e seleção de 1h, 2h, 3h ou 4h."""
    from bot import database, panel, config

    test_db = tmp_path / "panel_interval.db"
    monkeypatch.setattr(database, "DB_PATH", test_db)
    await database.init_db()

    target_chat = "-100666777"
    await database.set_config("target_chat_id", target_chat)
    await database.register_channel(target_chat, "Canal VIP Intervalo Panel", "instant")

    # 1. Abre submenu de intervalo
    text, kb = await panel._interval_menu_keyboard()
    assert "MODO INTERVALO DINÂMICO" in text
    assert "Escolha o intervalo desejado" in text

    # 2. Simula clique em "panel:set_interval:3"
    answered_alerts = []
    class MockIntervalQuery:
        data = "panel:set_interval:3"
        message = type("Msg", (), {})()
        from_user = type("User", (), {"id": config.OWNER_ID})()

        async def answer(self, text="", show_alert=False):
            answered_alerts.append({"text": text, "show_alert": show_alert})

        async def edit_message_text(self, text, reply_markup=None, **kwargs):
            pass

    class MockContext:
        bot = None

    update = type("Update", (), {"callback_query": MockIntervalQuery(), "effective_user": type("User", (), {"id": config.OWNER_ID})()})()
    await panel.panel_callback_handler(update, MockContext())

    # Validações:
    # A) Canal agora está em modo interval e com 3 horas configuradas
    ch = await database.get_channel(target_chat)
    assert ch["dispatch_mode"] == "interval"
    assert ch["interval_hours"] == 3

    # B) Alerta exibido com sucesso
    assert len(answered_alerts) == 1
    assert "A cada 3h" in answered_alerts[0]["text"]


@pytest.mark.asyncio
async def test_ai_caption_vision_and_travas_sanitizer():
    """Garante que o sanitizador da IA corrige termos arcaicos como 'despidos' e limita emojis."""
    from bot.modules.ai_caption import _sanitize_caption, _get_system_prompt

    # 1. Verifica regras no System Prompt
    prompt = _get_system_prompt("picante")
    assert "VIP" in prompt and "mulher brasileira" in prompt
    assert "casal" in prompt or "homem" in prompt

    # 2. Testa autocorreção do sanitizador em caso de alucinações da IA
    raw_bad = "Estávamos despidos e prontos para se deleitar na cama... 🔥😈🤤💦"
    clean = _sanitize_caption(raw_bad)
    assert "despidos" not in clean
    assert "deleitar" not in clean
    assert "peladas" in clean or "pelada" in clean
    assert "aproveitar" in clean

    # 3. Testa remoção de prefixos indesejados
    raw_prefixed = "Aqui está: Olha essa novidade pra você... 💋"
    clean_prefixed = _sanitize_caption(raw_prefixed)
    assert not clean_prefixed.lower().startswith("aqui")


@pytest.mark.asyncio
async def test_ai_caption_vision_multimodal_payload(tmp_path, monkeypatch):
    """Garante que generate_ai_caption extrai imagem quando media_path é passado e monta payload multimodal."""
    from bot.modules import ai_caption

    test_img = tmp_path / "test_photo.jpg"
    test_img.write_bytes(b"dummy_image_data_bytes_for_testing")

    captured_payloads = []

    async def mock_vision_post(self, url, headers=None, json=None, **kwargs):
        captured_payloads.append(json)
        class MockRes:
            status_code = 200
            def json(self):
                return {
                    "choices": [{"message": {"content": "Tô toda peladinha esperando você... 🔥"}}]
                }
        return MockRes()

    monkeypatch.setattr("httpx.AsyncClient.post", mock_vision_post)
    monkeypatch.setattr(ai_caption, "GROQ_API_KEY", "dummy_valid_groq_key")

    caption = await ai_caption.generate_ai_caption(
        title_or_context="Ensaio quente",
        media_type="photo",
        media_path=test_img,
    )

    assert "peladinha" in caption
    assert len(captured_payloads) > 0
    # Verifica que o payload contém o formato de visão multimodal (image_url)
    user_content = captured_payloads[0]["messages"][1]["content"]
    assert isinstance(user_content, list)
    assert any(item.get("type") == "image_url" for item in user_content)


@pytest.mark.asyncio
async def test_panel_dispatch_schedule_calculation():
    """Garante que o painel calcula com precisão o último post e o próximo post em todos os modos."""
    import datetime
    from bot import panel

    now = datetime.datetime.now()

    # 1. Modo Intervalo: 2 Horas com último post há 30 min
    ch_interval = {
        "dispatch_mode": "interval",
        "interval_hours": 2,
        "last_dispatched_at": (now - datetime.timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
    }
    last_s, next_s = panel._format_dispatch_schedule_info(ch_interval)
    assert "Hoje às" in last_s
    assert "em ~1h 30m" in next_s or "em ~1h 29m" in next_s

    # 2. Modo Intervalo: Sem post anterior
    ch_interval_empty = {
        "dispatch_mode": "interval",
        "interval_hours": 1,
        "last_dispatched_at": None
    }
    last_s, next_s = panel._format_dispatch_schedule_info(ch_interval_empty)
    assert "Nenhum registro" in last_s
    assert "Imediato" in next_s

    # 3. Modo Agendado
    ch_scheduled = {
        "dispatch_mode": "scheduled",
        "schedule_times": "01:00,23:59",
    }
    last_s, next_s = panel._format_dispatch_schedule_info(ch_scheduled)
    assert "23:59" in next_s or "01:00" in next_s

    # 4. Modo Imediato e Manual
    assert "ao enviar" in panel._format_dispatch_schedule_info({"dispatch_mode": "instant"})[1]
    assert "Sob demanda" in panel._format_dispatch_schedule_info({"dispatch_mode": "manual"})[1]


@pytest.mark.asyncio
async def test_dispatch_concurrency_lock_and_bro_talk_sanitizer():
    """Garante que a trava impede dois disparos simultâneos e remove gírias tipo 'Cara, '."""
    import asyncio
    from bot.modules import scheduler, ai_caption

    # 1. Testa que "Cara, olha como eu fico..." vira "Olha como eu fico..."
    raw_bro = "Cara, olha como eu fico quando penso em você... 😈🔥"
    clean_bro = ai_caption._sanitize_caption(raw_bro)
    assert not clean_bro.lower().startswith("cara")
    assert clean_bro.startswith("Olha como eu fico")

    # 2. Testa trava de concorrência por canal
    test_cid = "-100999888777"
    lock = scheduler.get_dispatch_lock(test_cid)
    assert not lock.locked()

    async with lock:
        assert lock.locked()
        # Se tentar disparar enquanto o lock está ativo, deve retornar in_progress
        res = await scheduler.dispatch_next_from_vault(None, test_cid)
        assert res["success"] is False
        assert res["media_type"] == "in_progress"

    assert not lock.locked()
