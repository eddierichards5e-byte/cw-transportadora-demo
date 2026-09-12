from __future__ import annotations

import os
import shutil
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import Dict, Any

from config.settings import settings
from utils.cache import runtime_cache
from utils.database import conectar
from utils.logger import get_logger

logger = get_logger(__name__)


class ConfigService:
    def carregar_configuracoes(self) -> Dict[str, Any]:
        def _load():
            settings.reload()
            return settings.configuracoes

        return runtime_cache.get_or_set(
            "configuracoes",
            "dados",
            _load,
            ttl_seconds=3,
        )

    def salvar_configuracoes(self, dados: Dict[str, Any]) -> Dict[str, Any]:
        resultado = settings.salvar_configuracoes(dados)
        self._invalidar_cache()
        return resultado

    def restaurar_padrao(self) -> Dict[str, Any]:
        resultado = settings.restaurar_padrao()
        self._invalidar_cache()
        return resultado

    def abrir_pasta_sistema(self) -> str:
        return str(settings.project_dir)

    def _resolver_pasta_relatorios(self, pasta_relatorios: str | None = None):
        nome = str(pasta_relatorios or settings.pasta_relatorios).strip() or "relatorios_gerados"
        candidata = Path(nome)
        if candidata.is_absolute():
            return candidata
        # Nunca gravar documentos da empresa dentro da pasta da versão.
        return settings.app_data_dir / candidata

    def _migrar_relatorios_legados(self, destino: Path) -> None:
        """Copia relatórios legados para o armazenamento persistente sem apagar a origem."""
        legado = settings.project_dir / settings.pasta_relatorios
        try:
            if destino.resolve() == legado.resolve() or not legado.exists() or not legado.is_dir():
                return
            if any(destino.iterdir()) if destino.exists() else False:
                return
            destino.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(legado, destino, dirs_exist_ok=True)
            logger.warning("[DADOS] Relatórios legados copiados para área persistente: %s", destino)
        except Exception as erro:
            logger.warning("[DADOS] Não foi possível migrar relatórios legados: %s", erro)

    def abrir_pasta_relatorios(self, pasta_relatorios: str | None = None) -> str:
        pasta = self._resolver_pasta_relatorios(pasta_relatorios)
        self._migrar_relatorios_legados(pasta)
        pasta.mkdir(parents=True, exist_ok=True)
        return str(pasta)

    def fazer_backup(self, pasta_relatorios: str | None = None) -> str:
        destino = settings.backup_dir / datetime.now().strftime("%d%m%Y_%H%M%S")
        destino.mkdir(parents=True, exist_ok=True)

        # Snapshot consistente do SQLite, inclusive quando WAL estiver ativo.
        if settings.db_path.exists():
            db_destino = destino / settings.db_path.name
            origem_conn = None
            destino_conn = None
            try:
                origem_conn = sqlite3.connect(str(settings.db_path), timeout=30)
                destino_conn = sqlite3.connect(str(db_destino), timeout=30)
                with destino_conn:
                    origem_conn.backup(destino_conn)
            finally:
                if origem_conn is not None:
                    origem_conn.close()
                if destino_conn is not None:
                    destino_conn.close()

        if settings.config_path.exists():
            shutil.copy2(settings.config_path, destino / settings.config_path.name)

        origem_relatorios = self._resolver_pasta_relatorios(pasta_relatorios)
        self._migrar_relatorios_legados(origem_relatorios)
        if origem_relatorios.exists():
            shutil.copytree(
                origem_relatorios,
                destino / origem_relatorios.name,
                dirs_exist_ok=True
            )

        self._invalidar_cache()
        return str(destino)

    def info_banco(self) -> Dict[str, Any]:
        cached = runtime_cache.get("configuracoes", "info_banco")
        if cached is not None:
            return cached

        tamanho = "Não encontrado"
        tabelas = 0
        registros = 0

        if settings.db_path.exists():
            tamanho_bytes = settings.db_path.stat().st_size
            tamanho = f"{tamanho_bytes / 1024 / 1024:.2f} MB"

        try:
            conn = conectar()
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            lista_tabelas = cursor.fetchall()
            tabelas = len(lista_tabelas)

            tabelas_principais = [
                "notas",
                "viagens",
                "funcionarios",
                "folha_funcionarios",
                "abastecimentos",
                "manutencoes",
                "contas",
            ]

            for tabela in tabelas_principais:
                try:
                    cursor.execute(f"SELECT COUNT(*) FROM {tabela}")
                    registros += cursor.fetchone()[0]
                except Exception as erro:
                    logger.debug(f"Tabela {tabela} não disponível para contagem: {erro}")
        finally:
            try:
                conn.close()
            except Exception:
                pass  # conn pode não ter sido atribuída se conectar() falhou

        ultimo_backup = "Nenhum"
        if settings.backup_dir.exists():
            backups = sorted(os.listdir(settings.backup_dir), reverse=True)
            if backups:
                ultimo_backup = backups[0]

        info = {
            "tamanho": tamanho,
            "tabelas": tabelas,
            "registros": registros,
            "ultimo_backup": ultimo_backup,
        }
        return runtime_cache.set("configuracoes", "info_banco", info, ttl_seconds=5)

    def _invalidar_cache(self) -> None:
        runtime_cache.invalidate_namespace("configuracoes")


config_service = ConfigService()
