"""Sincronização bidirecional SQLite <-> Supabase."""
from __future__ import annotations

from datetime import datetime
from typing import Any
import json
from pathlib import Path

from config.settings import settings
from utils.database._conexao import TABELAS_SYNC, conectar, agora_sync, registrar_sync, criar_tabela_sync_conflitos
from utils.supabase_db import SupabaseClient, SupabaseNaoConfiguradoError, SupabaseSchemaError
from utils.logger import get_logger
from services.auditoria_service import (
    auditoria_service, ACAO_SYNC_INICIADA, ACAO_SYNC_CONCLUIDA,
    ACAO_SYNC_CONFLITO, ACAO_SYNC_ERRO,
)

logger = get_logger(__name__)

# Pais antes de filhos para reduzir conflitos de relacionamento durante o pull.
ORDEM_SYNC = [
    "clientes", "manifestos", "caminhoes", "funcionarios", "contas",
    "abastecimentos", "manutencoes", "operacoes_sp", "notas", "viagens",
    "folha_funcionarios", "viagem_notas",
]


class SyncService:
    def __init__(self):
        self.sincronizando = False
        self.ultimo_resultado: dict[str, Any] = {}

    def _reparar_fila(self, forcar_todos: bool = False) -> int:
        adicionados = 0
        conn = conectar()
        try:
            cur = conn.cursor()
            for tabela in TABELAS_SYNC:
                if forcar_todos:
                    cur.execute(f"SELECT id FROM {tabela}")
                else:
                    try:
                        cur.execute(f"SELECT id FROM {tabela} WHERE COALESCE(sincronizado,0)=0 OR atualizado_em IS NULL OR sync_id IS NULL")
                    except Exception:
                        # Bancos legados podem ainda não possuir as colunas de sync.
                        # O registro será enfileirado mesmo assim; o envio usa o
                        # payload real da tabela e não depende dessas colunas.
                        cur.execute(f"SELECT id FROM {tabela}")
                for (registro_id,) in cur.fetchall():
                    before = cur.execute("SELECT COUNT(*) FROM sync_log WHERE tabela=? AND registro_id=? AND status='PENDENTE'", (tabela, str(registro_id))).fetchone()[0]
                    registrar_sync(cur, tabela, registro_id)
                    if before == 0:
                        adicionados += 1
            conn.commit()
        finally:
            conn.close()
        return adicionados

    @staticmethod
    def _timestamp(valor: Any) -> str:
        if valor is None:
            return ""
        return str(valor).replace("T", " ").replace("Z", "")

    @staticmethod
    def _linhas_diferentes(local: dict[str, Any], cloud: dict[str, Any]) -> bool:
        """Compara somente dados persistentes compartilhados, ignorando metadados locais."""
        ignorar = {"sincronizado", "sync_log_id"}
        chaves = set(local) | set(cloud)
        return any(
            str(local.get(chave)) != str(cloud.get(chave))
            for chave in chaves
            if chave not in ignorar
        )

    def _local_row(self, tabela: str, referencia):
        conn = conectar()
        try:
            conn.row_factory = __import__("sqlite3").Row
            try:
                row = conn.execute(f"SELECT * FROM {tabela} WHERE id=?", (int(referencia),)).fetchone()
            except (ValueError, TypeError):
                row = conn.execute(f"SELECT * FROM {tabela} WHERE sync_id=?", (str(referencia),)).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def _marcar_enviado(self, tabela: str, registro_id: int):
        conn = conectar()
        try:
            conn.execute(f"UPDATE {tabela} SET sincronizado=1 WHERE id=?", (registro_id,))
            conn.execute("UPDATE sync_log SET status='OK', erro=NULL, sincronizado_em=CURRENT_TIMESTAMP WHERE tabela=? AND registro_id IN (?, (SELECT sync_id FROM %s WHERE id=?))" % tabela, (tabela, str(registro_id), registro_id))
            conn.commit()
        finally:
            conn.close()

    def _marcar_erro(self, sync_id: int, erro: Exception):
        conn = conectar()
        try:
            conn.execute("UPDATE sync_log SET status='ERRO', tentativas=COALESCE(tentativas,0)+1, erro=? WHERE id=?", (str(erro)[:1000], sync_id))
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _obter_marcador_sync() -> str | None:
        conn = conectar()
        try:
            row = conn.execute("SELECT valor FROM sync_estado WHERE chave='ultima_pull_inicio'").fetchone()
            return str(row[0]) if row and row[0] else None
        finally:
            conn.close()

    @staticmethod
    def _salvar_marcador_sync(valor: str) -> None:
        conn = conectar()
        try:
            conn.execute(
                "INSERT INTO sync_estado(chave,valor) VALUES('ultima_pull_inicio',?) "
                "ON CONFLICT(chave) DO UPDATE SET valor=excluded.valor",
                (valor,),
            )
            conn.commit()
        finally:
            conn.close()

    def _pendencias(self) -> list[dict[str, Any]]:
        conn = conectar()
        conn.row_factory = __import__("sqlite3").Row
        try:
            rows = conn.execute("SELECT id,tabela,registro_id,operacao,atualizado_em FROM sync_log WHERE status IN ('PENDENTE','ERRO') ORDER BY id ASC LIMIT 1000").fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def _registrar_conflito(self, tabela: str, registro_id: Any, local_ts: str, cloud_ts: str, detalhes: str):
        """Persiste conflitos de versão para diagnóstico e suporte entre máquinas."""
        conn = conectar()
        try:
            criar_tabela_sync_conflitos(conn)
            conn.execute(
                """INSERT INTO sync_conflitos
                (tabela, registro_id, versao_local, versao_nuvem, decisao, detalhes)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (tabela, str(registro_id), local_ts or None, cloud_ts or None,
                 "NUVEM_VENCEU", detalhes[:2000]),
            )
            conn.commit()
        finally:
            conn.close()
        auditoria_service.registrar(
            ACAO_SYNC_CONFLITO, "Sincronização",
            registro_afetado=f"{tabela}/{registro_id}",
            tabela=tabela, registro_id=registro_id,
            versao_local=local_ts, versao_nuvem=cloud_ts, decisao="NUVEM_VENCEU",
        )

    def _enviar(self, client: SupabaseClient) -> tuple[int, int, list[str], dict[str, int]]:
        enviados = 0
        erros = 0
        mensagens: list[str] = []
        enviados_por_tabela: dict[str, int] = {}
        pendencias = self._pendencias()
        ordem = {tabela: i for i, tabela in enumerate(ORDEM_SYNC)}
        # Filhos precisam sair antes dos pais. Isso evita que uma exclusão
        # local válida seja bloqueada pelos triggers relacionais do SQLite
        # quando ambos os registros estão pendentes no mesmo ciclo.
        pendencias.sort(key=lambda item: (
            0 if str(item.get("operacao", "")).upper() == "DELETE" else 1,
            -ordem.get(str(item.get("tabela")), -1) if str(item.get("operacao", "")).upper() == "DELETE" else ordem.get(str(item.get("tabela")), 999999),
            int(item.get("id") or 0),
        ))
        for item in pendencias:
            sid = int(item["id"])
            tabela = item["tabela"]
            referencia = item["registro_id"]
            try:
                row = self._local_row(tabela, referencia)
                try:
                    rid = int(row.get("id")) if row else int(referencia)
                except (ValueError, TypeError):
                    rid = None
                if str(item["operacao"]).upper() == "DELETE":
                    # Exclusões também participam da resolução de conflitos.
                    # Sem esta verificação, um notebook que ficou dias offline
                    # poderia enviar um tombstone antigo e apagar na nuvem uma
                    # alteração mais nova feita por outro computador.
                    atualizado = str(item.get("atualizado_em") or agora_sync())
                    sync_id = None
                    if row:
                        atualizado = str(row.get("atualizado_em") or atualizado)
                        sync_id = row.get("sync_id")
                    if rid is None:
                        raise ValueError(f"Não foi possível determinar o ID local para {tabela}: {referencia}")
                    cloud = client.get_row(tabela, rid)
                    local_ts = self._timestamp(atualizado)
                    cloud_ts = self._timestamp(cloud.get("atualizado_em")) if cloud else ""
                    # Se a nuvem já possui versão mais nova, inclusive quando
                    # os timestamps forem iguais e o conteúdo não for o mesmo,
                    # a nuvem vence. Empates não podem ser resolvidos de forma
                    # destrutiva pelo DELETE local.
                    if cloud and cloud_ts and local_ts and (
                        cloud_ts > local_ts or cloud_ts == local_ts
                    ):
                        detalhes = (
                            "A nuvem possui versão igual ou mais recente; "
                            "exclusão local cancelada para preservar o dado. "
                            f"local={local_ts} nuvem={cloud_ts}"
                        )
                        logger.warning(
                            "[SYNC] conflito DELETE %s/%s: nuvem venceu (%s >= %s)",
                            tabela, rid, cloud_ts, local_ts,
                        )
                        self._registrar_conflito(tabela, rid, local_ts, cloud_ts, detalhes)
                        self._aplicar_cloud(tabela, cloud, permitir_empate=True)
                    else:
                        client.mark_deleted(tabela, rid, sync_id or str(referencia), atualizado)
                else:
                    if not row:
                        raise ValueError(f"Registro local não encontrado: {tabela}/{referencia}")
                    rid = int(row["id"])
                    # Antes de enviar, compare com a versão que já está na
                    # nuvem. Se outra máquina tiver uma alteração mais nova,
                    # ela ganha e será baixada na etapa seguinte.
                    cloud = client.get_row(tabela, rid)
                    local_ts = self._timestamp(row.get("atualizado_em"))
                    cloud_ts = self._timestamp(cloud.get("atualizado_em")) if cloud else ""
                    if cloud and cloud_ts and local_ts and (
                        cloud_ts > local_ts or (cloud_ts == local_ts and self._linhas_diferentes(row, cloud))
                    ):
                        detalhes = (
                            "A nuvem possui versão mais recente ou empate de versão com conteúdo divergente; "
                            "envio local cancelado. "
                            f"local={local_ts} nuvem={cloud_ts}"
                        )
                        logger.warning(
                            "[SYNC] conflito %s/%s: nuvem mais nova (%s > %s); preservando versão da nuvem",
                            tabela, rid, cloud_ts, local_ts,
                        )
                        self._registrar_conflito(tabela, rid, local_ts, cloud_ts, detalhes)
                        # Materializa imediatamente a versão vencedora. Em empate
                        # divergente, permitir_empate é obrigatório para não limpar
                        # a fila deixando o PC local com a versão errada.
                        self._aplicar_cloud(tabela, cloud, permitir_empate=True)
                    else:
                        client.upsert(tabela, row)
                conn = conectar()
                try:
                    if row:
                        conn.execute(f"UPDATE {tabela} SET sincronizado=1 WHERE id=?", (rid,))
                    conn.execute("UPDATE sync_log SET status='OK', erro=NULL, sincronizado_em=CURRENT_TIMESTAMP WHERE id=?", (sid,))
                    conn.commit()
                finally:
                    conn.close()
                enviados += 1
                enviados_por_tabela[tabela] = enviados_por_tabela.get(tabela, 0) + 1
            except Exception as exc:
                self._marcar_erro(sid, exc)
                erros += 1
                mensagens.append(f"{tabela} {referencia}: {exc}")
        return enviados, erros, mensagens, enviados_por_tabela

    @staticmethod
    def _resolver_fila_apos_vitoria_cloud(conn, tabela: str, rid: int, sync_id: str | None = None):
        """Cancela pendências locais quando a versão da nuvem venceu.

        Sem isso, um tombstone/alteração mais novo baixado poderia ser seguido
        por um UPSERT antigo que ainda estivesse na fila local.
        """
        refs = [str(rid)]
        if sync_id:
            refs.append(str(sync_id))
        placeholders = ",".join("?" for _ in refs)
        conn.execute(
            f"UPDATE sync_log SET status='OK', erro=NULL, sincronizado_em=CURRENT_TIMESTAMP "
            f"WHERE tabela=? AND registro_id IN ({placeholders}) AND status IN ('PENDENTE','ERRO')",
            [tabela, *refs],
        )

    def _aplicar_cloud(self, tabela: str, cloud_row: dict[str, Any], permitir_empate: bool = False) -> bool:
        rid = cloud_row.get("id")
        if rid is None:
            return False
        local = self._local_row(tabela, int(rid))
        cloud_ts = self._timestamp(cloud_row.get("atualizado_em"))
        local_ts = self._timestamp(local.get("atualizado_em")) if local else ""
        if local and cloud_ts and local_ts and cloud_ts < local_ts:
            return False
        if local and cloud_ts and local_ts and cloud_ts == local_ts and not permitir_empate:
            return False

        conn = conectar()
        try:
            if bool(cloud_row.get("deletado")):
                # Um tombstone antigo nunca pode apagar uma alteração local mais
                # nova. Só aplicamos a exclusão quando a nuvem é realmente mais
                # recente (ou quando não existe registro local).
                if local:
                    if cloud_ts and local_ts and cloud_ts < local_ts:
                        conn.rollback()
                        return False
                    if cloud_ts and local_ts and cloud_ts == local_ts and not permitir_empate:
                        conn.rollback()
                        return False
                    conn.execute(f"DELETE FROM {tabela} WHERE id=?", (rid,))
                    self._resolver_fila_apos_vitoria_cloud(conn, tabela, int(rid), cloud_row.get("sync_id"))
                    conn.commit()
                    return True
                conn.rollback()
                return False

            cur = conn.cursor()
            cols = [r[1] for r in cur.execute(f"PRAGMA table_info({tabela})").fetchall()]
            payload = {k: v for k, v in cloud_row.items() if k in cols}
            payload["sincronizado"] = 1
            payload["deletado"] = 0
            if "atualizado_em" in cols and not payload.get("atualizado_em"):
                payload["atualizado_em"] = agora_sync()
            names = list(payload.keys())
            placeholders = ",".join("?" for _ in names)
            if local:
                sets = ",".join(f"{c}=?" for c in names if c != "id")
                vals = [payload[c] for c in names if c != "id"] + [rid]
                conn.execute(f"UPDATE {tabela} SET {sets} WHERE id=?", vals)
            else:
                conn.execute(f"INSERT INTO {tabela} ({','.join(names)}) VALUES ({placeholders})", [payload[c] for c in names])
            self._resolver_fila_apos_vitoria_cloud(conn, tabela, int(rid), cloud_row.get("sync_id"))
            conn.commit()
            return True
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _baixar(self, client: SupabaseClient, updated_after: str | None = None) -> tuple[int, list[str]]:
        """Baixa a nuvem em duas passagens para respeitar relacionamentos.

        Em bases antigas é possível que um filho (ex.: viagem_notas) seja
        retornado antes de o pai estar materializado localmente. Não tratamos
        esse caso como falha definitiva na primeira tentativa: guardamos o
        registro e tentamos novamente depois de todos os pais.

        Se a própria nuvem possuir um órfão (pai inexistente), ele fica apenas
        como aviso e não bloqueia o login. O dado inválido não é inventado nem
        aplicado ao SQLite.
        """
        baixados = 0
        erros: list[str] = []
        pendentes: list[tuple[str, dict[str, Any], str]] = []
        rows_por_tabela: dict[str, list[dict[str, Any]]] = {}

        # Primeiro coleta tudo. Assim uma falha em uma tabela não impede as
        # demais de serem baixadas e podemos fazer a segunda passagem.
        for tabela in ORDEM_SYNC:
            try:
                rows_por_tabela[tabela] = client.list_rows(tabela, updated_after=updated_after)
            except Exception as exc:
                erros.append(f"{tabela}: {exc}")
                rows_por_tabela[tabela] = []

        # Exclusões são aplicadas de filho para pai. Upserts continuam de pai
        # para filho. Isso mantém o SQLite consistente quando uma viagem e seus
        # vínculos/nota são removidos na mesma rodada.
        linhas_delete = [(tabela, row) for tabela in reversed(ORDEM_SYNC) for row in rows_por_tabela.get(tabela, []) if bool(row.get("deletado"))]
        linhas_upsert = [(tabela, row) for tabela in ORDEM_SYNC for row in rows_por_tabela.get(tabela, []) if not bool(row.get("deletado"))]

        for tabela, row in linhas_delete + linhas_upsert:
            try:
                if self._aplicar_cloud(tabela, row):
                    baixados += 1
            except Exception as exc:
                msg = str(exc)
                if msg.startswith("Relacionamento inválido:"):
                    pendentes.append((tabela, row, msg))
                else:
                    erros.append(f"{tabela} #{row.get('id')}: {exc}")

        # Segunda passagem: pais que só ficaram disponíveis após a primeira
        # rodada agora permitem materializar os filhos.
        for tabela, row, primeira_msg in pendentes:
            try:
                if self._aplicar_cloud(tabela, row):
                    baixados += 1
            except Exception as exc:
                msg = str(exc)
                if msg.startswith("Relacionamento inválido:"):
                    # Órfão real na nuvem: não aplicar lixo ao banco local e
                    # não derrubar toda a sincronização por causa dele.
                    logger.warning(
                        "[SYNC] registro órfão ignorado: %s #%s -> %s",
                        tabela, row.get("id"), msg,
                    )
                else:
                    erros.append(f"{tabela} #{row.get('id')}: {exc}")
        return baixados, erros

    def executar(self, reparar_fila=True):
        if self.sincronizando:
            return self.ultimo_resultado or {"status":"partial", "mensagem":"Sincronização já em andamento."}
        self.sincronizando = True
        inicio = datetime.now()
        client = None
        auditoria_service.registrar(ACAO_SYNC_INICIADA, "Sincronização",
                                    pendencias_antes=self.contar_pendencias())
        try:
            if not settings.supabase_enabled:
                resultado = {
                    "status": "error",
                    "mensagem": "Conexão com a nuvem não configurada. O CW não permite operar sem sincronização.",
                    "offline": True,
                    "pendencias": self.contar_pendencias(),
                }
                self.ultimo_resultado = resultado
                return resultado

            logger.info("[SYNC] iniciando sincronização; supabase_enabled=%s", settings.supabase_enabled)
            client = SupabaseClient()
            logger.info("[SYNC] REST base=%s", client.rest_url)
            try:
                meta = client.health_check()
            except SupabaseSchemaError as exc:
                # Não tratar como “offline”: o endpoint está alcançável, mas a
                # tabela/meta não está acessível. Isso normalmente significa
                # token de sincronização diferente do token gravado no SQL/RLS.
                logger.error("[SYNC] health_check recusado/incompleto: %s", exc)
                raise
            logger.info("[SYNC] health_check OK: bootstrap_required=%s schema=%s", meta.get("bootstrap_required"), meta.get("schema_version"))
            force = bool(meta.get("bootstrap_required"))
            # O marcador é o instante do início desta rodada. Só avançamos
            # depois de uma rodada sem erros, evitando perder alterações que
            # tenham acontecido enquanto a sincronização estava em andamento.
            marcador_anterior = None if force else self._obter_marcador_sync()
            marcador_rodada = agora_sync()
            # Nunca faça uma varredura/re-enfileiramento completo a cada login.
            # Em bases grandes isso pode deixar o gate de entrada aparentemente
            # travado antes mesmo de aparecer o log de envio. A reconstrução
            # completa da fila fica reservada ao bootstrap inicial; no uso normal
            # o sync_log já contém somente as alterações pendentes.
            reparadas = self._reparar_fila(forcar_todos=True) if force else 0
            if force:
                logger.info("[SYNC] bootstrap: fila completa reconstruída (%s registros)", reparadas)
            else:
                logger.info("[SYNC] modo incremental: fila existente será processada")
            enviados, erros_envio, mensagens_envio, enviados_por_tabela = self._enviar(client)
            logger.info("[SYNC] envio concluído: enviados=%s erros=%s por_tabela=%s", enviados, erros_envio, enviados_por_tabela)
            baixados, mensagens_baixa = self._baixar(client, updated_after=marcador_anterior)
            logger.info("[SYNC] download concluído: baixados=%s erros=%s", baixados, len(mensagens_baixa))
            erros = erros_envio + len(mensagens_baixa)
            if erros == 0:
                client.set_bootstrap_done()
                self._salvar_marcador_sync(marcador_rodada)
            pendencias = self.contar_pendencias()
            duracao = (datetime.now() - inicio).total_seconds()
            if erros and enviados:
                status = "partial"
                mensagem = f"Sincronização parcial: {enviados} enviados, {baixados} baixados, {pendencias} pendentes."
            elif erros:
                status = "error"
                detalhe = (mensagens_envio + mensagens_baixa)[:3]
                mensagem = "Falha na sincronização. " + " | ".join(detalhe)
            else:
                status = "success"
                mensagem = f"Nuvem sincronizada: {enviados} enviados, {baixados} baixados, {pendencias} pendentes."
            # Diagnóstico local útil sem expor credenciais.
            diagnostico_local = {}
            conn_diag = conectar()
            try:
                for tabela in TABELAS_SYNC:
                    try:
                        diagnostico_local[tabela] = int(conn_diag.execute(f"SELECT COUNT(*) FROM {tabela}").fetchone()[0] or 0)
                    except Exception:
                        diagnostico_local[tabela] = -1
            finally:
                conn_diag.close()
            if mensagens_envio:
                logger.error("[SYNC] Erros de envio: %s", " | ".join(mensagens_envio[:10]))
            if mensagens_baixa:
                logger.error("[SYNC] Erros de download: %s", " | ".join(mensagens_baixa[:10]))

            # Diagnóstico amigável: mostra quanto foi enviado por tabela e,
            # principalmente, quais registros ainda ficaram pendentes.
            diagnostico = []
            for tabela in ORDEM_SYNC:
                qtd = int(enviados_por_tabela.get(tabela, 0))
                if qtd:
                    diagnostico.append(f"✓ {tabela}: {qtd} enviado(s)")
            pendentes_detalhados = self._pendencias()
            if pendentes_detalhados:
                grupos: dict[str, list[str]] = {}
                for item in pendentes_detalhados[:50]:
                    tabela = str(item.get("tabela") or "?")
                    grupos.setdefault(tabela, []).append(f"#{item.get('registro_id')}")
                for tabela, ids in grupos.items():
                    diagnostico.append(f"⚠ {tabela}: {', '.join(ids[:10])}" + (" …" if len(ids) > 10 else ""))

            resultado = {
                "status": status,
                "mensagem": mensagem,
                "offline": False,
                "enviados": enviados,
                "baixados": baixados,
                "erros": erros,
                "pendencias": pendencias,
                "reparadas": reparadas,
                "duracao": duracao,
                "ultima_sync": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
                "detalhes": (mensagens_envio + mensagens_baixa)[:10],
                "diagnostico": diagnostico[:30],
                "enviados_por_tabela": enviados_por_tabela,
                "local": diagnostico_local,
            }
            self.ultimo_resultado = resultado
            auditoria_service.registrar(
                ACAO_SYNC_CONCLUIDA if status == "success" else ACAO_SYNC_ERRO,
                "Sincronização", enviados=enviados, baixados=baixados,
                erros=erros, pendencias=pendencias, status=status, duracao=duracao,
            )
            return resultado
        except SupabaseNaoConfiguradoError as exc:
            resultado = {"status":"error", "offline":True, "pendencias":self.contar_pendencias(), "mensagem":str(exc), "ultima_sync":None, "detalhes":[str(exc)]}
            self.ultimo_resultado = resultado
            auditoria_service.registrar(ACAO_SYNC_ERRO, "Sincronização", status="erro", tipo="nao_configurado", detalhes=str(exc))
            return resultado
        except SupabaseSchemaError as exc:
            logger.error("[SYNC] Supabase acessível, mas schema/autorização não validou: %s", exc)
            resultado = {
                "status":"error",
                "offline":False,
                "pendencias":self.contar_pendencias(),
                "mensagem":"Supabase configurado, porém o acesso à estrutura de sincronização foi recusado ou está incompleto.",
                "ultima_sync":None,
                "detalhes":[str(exc)],
                "diagnostico": [],
            }
            self.ultimo_resultado = resultado
            auditoria_service.registrar(ACAO_SYNC_ERRO, "Sincronização", status="erro", tipo="schema", detalhes=str(exc))
            return resultado
        except Exception as exc:
            logger.exception("[SYNC] Falha na sincronização")
            resultado = {"status":"error", "offline":False, "pendencias":self.contar_pendencias(), "mensagem":str(exc), "ultima_sync":None}
            self.ultimo_resultado = resultado
            auditoria_service.registrar(ACAO_SYNC_ERRO, "Sincronização", status="erro", tipo="inesperado", detalhes=str(exc))
            return resultado
        finally:
            if client:
                client.close()
            self.sincronizando = False

    def exportar_nuvem_backup(self) -> Path:
        """Exporta um snapshot JSON da nuvem antes de um reset destrutivo."""
        if not settings.supabase_enabled:
            raise SupabaseNaoConfiguradoError("Supabase não configurado. Não é possível criar backup da nuvem.")
        client = SupabaseClient()
        try:
            client.health_check()
            tabelas = [
                "manifestos", "clientes", "funcionarios", "folha_funcionarios",
                "notas", "caminhoes", "viagens", "viagem_notas", "operacoes_sp",
                "contas", "abastecimentos", "manutencoes",
            ]
            snapshot = {t: client.list_rows(t) for t in tabelas}
            pasta = Path(settings.backup_dir)
            pasta.mkdir(parents=True, exist_ok=True)
            destino = pasta / f"cw_supabase_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            destino.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            return destino
        finally:
            client.close()

    def limpar_nuvem_para_reset(self) -> dict[str, int]:
        """Limpa a base operacional do Supabase para acompanhar um reset total local."""
        if not settings.supabase_enabled:
            raise SupabaseNaoConfiguradoError("Supabase não configurado. Não é possível limpar os dados da nuvem.")
        client = SupabaseClient()
        try:
            client.health_check()
            return client.limpar_dados_operacionais()
        finally:
            client.close()

    @staticmethod
    def contar_pendencias() -> int:
        conn = conectar()
        try:
            existe = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='sync_log'").fetchone()
            if not existe:
                return 0
            return int(conn.execute("SELECT COUNT(*) FROM sync_log WHERE status IN ('PENDENTE','ERRO')").fetchone()[0] or 0)
        finally:
            conn.close()


sync_service = SyncService()
