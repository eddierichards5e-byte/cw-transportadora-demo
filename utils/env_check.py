"""Verificação de ambiente/configuração da nuvem."""
import os


def verificar_configuracao_env():
    """Verifica primeiro a configuração persistente do aplicativo.

    Mantém compatibilidade com .env para instalações antigas, mas não acusa
    Supabase desconectado apenas porque o executável está em outra pasta.
    """
    try:
        from config.settings import settings
        settings.reload()
        if settings.supabase_enabled:
            return True, "OK"
    except Exception:
        pass

    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    token = os.getenv("SUPABASE_SYNC_TOKEN")
    if url and key and token:
        return True, "OK"
    return False, "Supabase não configurado. Sincronização em nuvem desativada."
