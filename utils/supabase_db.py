"""Cliente REST do Supabase para o CW Transportadora.

O V54 usa a Data API/PostgREST em vez de uma conexão PostgreSQL direta.
Isso evita exigir psycopg2/driver nativo no Windows e permite trabalhar offline.
"""
from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import quote, urlparse

import requests
from dotenv import load_dotenv

from config.settings import settings

load_dotenv(override=True)


class SupabaseNaoConfiguradoError(RuntimeError):
    """Configuração da nuvem ausente."""


class SupabaseSchemaError(RuntimeError):
    """Projeto Supabase ainda não recebeu o schema de sincronização esperado."""


class SupabaseApiError(RuntimeError):
    """Erro HTTP retornado pela Data API."""

    def __init__(self, status_code: int, message: str, details: str = ""):
        self.status_code = status_code
        self.details = details
        super().__init__(message)


def _normalizar_url(url: str) -> str:
    url = (url or "").strip().rstrip("/")
    if url.startswith("postgresql://") or url.startswith("postgres://"):
        m = re.search(r"@db\.([a-z0-9-]+)\.supabase\.co", url, re.I)
        if m:
            return f"https://{m.group(1)}.supabase.co"
        raise SupabaseNaoConfiguradoError(
            "SUPABASE_URL antiga (PostgreSQL) detectada, mas não foi possível "
            "identificar o projeto. Use a URL da API do projeto."
        )
    m = re.match(r"^https?://supabase\.com/dashboard/project/([a-z0-9-]+)(?:/.*)?$", url, re.I)
    if m:
        return f"https://{m.group(1)}.supabase.co"
    parsed = urlparse(url)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    return url




CLOUD_COLUMNS = {
    "manifestos": {"id","nome_arquivo","data_importacao","sync_id","sincronizado","atualizado_em","deletado"},
    "clientes": {"id","nome","cnpj","cidade","uf","razao_social","fantasia","cpf","telefone","codigo","prioridade","criado_em","sync_id","sincronizado","atualizado_em","deletado"},
    "funcionarios": {"id","nome","cargo","status","salario","telefone","data_admissao","vale_refeicao","criado_em","sync_id","sincronizado","atualizado_em","deletado"},
    "folha_funcionarios": {"id","funcionario_id","mes","ano","salario","vale_refeicao","hora_extra","outros","total","qtd_horas_extra","valor_hora_extra","criado_em","sync_id","sincronizado","atualizado_em","deletado"},
    "notas": {"id","manifesto_id","chave_nfe","numero_cte","remetente_id","destinatario_id","valor_mercadoria","valor_frete","peso","origem","destino","status","cubagem_m3","tipo_carga","criado_em","sync_id","sincronizado","atualizado_em","deletado"},
    "caminhoes": {"id","placa","modelo","motorista","capacidade_kg","media_km_l","status","capacidade_m3","tipos_carga_permitidos","sync_id","sincronizado","atualizado_em","deletado"},
    "viagens": {"id","caminhao_id","data_saida","data_retorno","motorista","status","peso_total","frete_total","custo_total","lucro_total","custo_combustivel","custo_pedagio","custo_motorista","custo_outros","margem_percentual","sync_id","sincronizado","atualizado_em","deletado"},
    "viagem_notas": {"id","viagem_id","nota_id","sync_id","sincronizado","atualizado_em","deletado"},
    "operacoes_sp": {"id","data_operacao","nome_caminhao","placa","motorista","valor_notas","frete_carreta","pedagio_carreta","outros_custos","custo_total","liquido","criado_em","sync_id","sincronizado","atualizado_em","deletado"},
    "contas": {"id","tipo","descricao","pessoa","categoria","valor","vencimento","pagamento","status","observacao","viagem_id","criado_em","sync_id","sincronizado","atualizado_em","deletado"},
    "abastecimentos": {"id","data_abastecimento","veiculo","motorista","km_atual","litros","valor_litro","valor_total","media_km_l","custo_km","posto","observacao","viagem_id","criado_em","sync_id","sincronizado","atualizado_em","deletado"},
    "manutencoes": {"id","data_manutencao","veiculo","km_atual","tipo","descricao","oficina","valor","proxima_revisao_km","status","observacao","viagem_id","sync_id","sincronizado","atualizado_em","deletado"},
}

def supabase_habilitado() -> bool:
    return bool(settings.supabase_enabled)


def conectar_supabase():
    """Mantido por compatibilidade: retorna uma sessão HTTP, não psycopg2."""
    return SupabaseClient().session


class SupabaseClient:
    def __init__(self, timeout: int = 15):
        if not supabase_habilitado():
            raise SupabaseNaoConfiguradoError(
                "Supabase não configurado. Informe URL, chave publishable e token de sincronização."
            )
        self.base_url = _normalizar_url(settings.supabase_url)
        self.rest_url = f"{self.base_url}/rest/v1"
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "apikey": settings.supabase_key,
            "Authorization": f"Bearer {settings.supabase_key}",
            "x-cw-sync-token": settings.supabase_sync_token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        })

    def _url(self, tabela: str) -> str:
        return f"{self.rest_url}/{quote(tabela, safe='')}"

    @staticmethod
    def _erro(resp: requests.Response) -> SupabaseApiError:
        try:
            payload = resp.json()
            if isinstance(payload, dict):
                msg = payload.get("message") or payload.get("hint") or payload.get("details") or resp.text
                details = payload.get("details") or payload.get("hint") or ""
            else:
                msg, details = str(payload), ""
        except Exception:
            msg, details = resp.text or resp.reason, ""
        return SupabaseApiError(resp.status_code, f"Supabase HTTP {resp.status_code}: {msg}", details)

    def request(self, method: str, tabela: str, **kwargs):
        # requests permite que headers= substitua completamente os headers da
        # Session. Isso quebrava POST/PATCH que passavam Prefer e removiam
        # inadvertidamente apikey/Authorization/x-cw-sync-token.
        headers = dict(self.session.headers)
        headers.update(kwargs.pop("headers", {}) or {})
        kwargs["headers"] = headers
        try:
            resp = self.session.request(method, self._url(tabela), timeout=self.timeout, **kwargs)
        except requests.RequestException as exc:
            raise ConnectionError(f"Não foi possível conectar ao Supabase: {exc}") from exc
        if not resp.ok:
            raise self._erro(resp)
        if not resp.content:
            return None
        try:
            return resp.json()
        except ValueError:
            return None

    def health_check(self) -> dict[str, Any]:
        meta = self.request("GET", "cw_sync_meta", params={"select":"id,schema_version,bootstrap_required", "id":"eq.1", "limit":"1"})
        if not meta:
            raise SupabaseSchemaError(
                "Supabase acessível, mas cw_sync_meta não retornou a linha id=1. "
                "Isso normalmente indica que o token de sincronização salvo no programa "
                "não é o mesmo token configurado no SQL/RLS do projeto, ou que a linha "
                "id=1 ainda não foi criada. Execute novamente o SQL de configuração usando "
                "o MESMO token persistido em Configurações > Nuvem Supabase; não é necessário "
                "alterar a chave do projeto."
            )
        return dict(meta[0])

    def get_row(self, tabela: str, registro_id: int) -> dict[str, Any] | None:
        """Busca um único registro antes de um UPSERT local.

        Isso permite que dois PCs trabalhem ao mesmo tempo sem uma máquina
        simplesmente sobrescrever uma alteração mais nova feita por outra.
        """
        rows = self.request("GET", tabela, params={
            "select": "*",
            "id": f"eq.{int(registro_id)}",
            "limit": "1",
        }) or []
        return dict(rows[0]) if rows else None

    def list_rows(self, tabela: str, page_size: int = 1000, updated_after: str | None = None) -> list[dict[str, Any]]:
        """Lista registros com paginação estável; pode limitar por atualização.

        O filtro incremental reduz drasticamente o tráfego após o primeiro
        bootstrap. O chamador deve guardar um marcador anterior ao início da
        sincronização para não perder alterações ocorridas durante a rodada.
        """
        rows: list[dict[str, Any]] = []
        offset = 0
        while True:
            params = {
                "select": "*",
                "order": "id.asc",
                "limit": str(page_size),
                "offset": str(offset),
            }
            if updated_after:
                params["atualizado_em"] = f"gt.{updated_after}"
            page = self.request("GET", tabela, params=params) or []
            rows.extend(page)
            if len(page) < page_size:
                break
            offset += page_size
        return rows

    def upsert(self, tabela: str, row: dict[str, Any]) -> None:
        allowed = CLOUD_COLUMNS.get(tabela)
        payload = {k: v for k, v in dict(row).items() if not allowed or k in allowed}
        payload.pop("sincronizado", None)
        payload["deletado"] = bool(payload.get("deletado"))
        # O campo local 'deletado' continua existindo na nuvem como tombstone.
        self.request("POST", tabela, params={"on_conflict": "id"}, headers={"Prefer": "resolution=merge-duplicates,return=minimal"}, json=payload)

    def mark_deleted(self, tabela: str, registro_id: int, sync_id: str | None, atualizado_em: str) -> None:
        payload = {"id": int(registro_id), "deletado": True, "atualizado_em": atualizado_em}
        if sync_id:
            payload["sync_id"] = sync_id
        self.request("POST", tabela, params={"on_conflict": "id"}, headers={"Prefer": "resolution=merge-duplicates,return=minimal"}, json=payload)

    def set_bootstrap_done(self) -> None:
        self.request("PATCH", "cw_sync_meta", params={"id":"eq.1"}, headers={"Prefer":"return=minimal"}, json={"bootstrap_required": False})

    def limpar_dados_operacionais(self) -> dict[str, int]:
        """Apaga explicitamente os dados operacionais da nuvem para um reset total.

        Só deve ser chamado a partir do fluxo de reset total, após confirmação
        explícita do usuário. A conta de meta/sincronização não é removida.
        """
        tabelas = [
            "viagem_notas", "viagens", "operacoes_sp", "notas",
            "manifestos", "abastecimentos", "manutencoes", "contas",
            "caminhoes", "folha_funcionarios", "funcionarios", "clientes",
        ]
        removidos = {}
        for tabela in tabelas:
            rows = self.list_rows(tabela)
            total = len(rows)
            if total:
                # IDs são usados individualmente para respeitar RLS e evitar
                # filtros de DELETE excessivamente amplos.
                for row in rows:
                    rid = row.get("id")
                    if rid is not None:
                        self.request("DELETE", tabela, params={"id": f"eq.{rid}"})
            removidos[tabela] = total
        self.request("PATCH", "cw_sync_meta", params={"id":"eq.1"}, headers={"Prefer":"return=minimal"}, json={"bootstrap_required": True})
        return removidos

    def bootstrap_required(self) -> bool:
        return bool(self.health_check().get("bootstrap_required"))

    def close(self):
        self.session.close()
