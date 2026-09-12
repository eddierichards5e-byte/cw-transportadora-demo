"""
Servico de gerenciamento de usuarios do sistema CW Transportadora.

Responsavel por:
- CRUD de usuarios (criar, listar, editar, excluir)
- Ativacao / desativacao de contas
- Alteracao de nivel de acesso
- Redefinicao de senha (pelo mestre)
- Alteracao da propria senha
- Gerenciamento de permissoes por modulo e acao
"""

from __future__ import annotations

import secrets
import string
from datetime import datetime
from typing import Any, Dict, List, Optional

from services.auth_service import (
    AuthService,
    MODULOS_PERMISSOES,
    SenhaFracaError,
    auth_service,
    validar_forca_senha,
)
from utils.database import conectar
from utils.logger import get_logger

logger = get_logger(__name__)


class UsuarioService:
    @staticmethod
    def _exigir(acao: str):
        if not auth_service.usuario_atual:
            raise PermissionError("É necessário estar autenticado para executar esta operação.")
        if not auth_service.pode("usuarios", acao):
            try:
                from services.auditoria_service import auditoria_service, ACAO_ACESSO_NEGADO
                u = auth_service.usuario_atual
                auditoria_service.registrar(ACAO_ACESSO_NEGADO, "usuarios", usuario=u.get("usuario"), usuario_id=u.get("id"), usuario_nome=u.get("nome_completo"), acao_solicitada=acao)
            except Exception:
                pass
            raise PermissionError("Seu perfil não possui permissão para esta operação administrativa.")

    @staticmethod
    def _auditar(acao: str, usuario_id=None, **detalhes):
        try:
            from services.auditoria_service import auditoria_service
            u = auth_service.usuario_atual or {}
            auditoria_service.registrar(acao, "usuarios", usuario=u.get("usuario") or "Sistema", usuario_id=u.get("id"), usuario_nome=u.get("nome_completo"), registro_afetado=usuario_id, **detalhes)
        except Exception:
            pass

    """Servico para operacoes administrativas de usuarios."""

    # ── Criar usuario ─────────────────────────────────────────────────────────

    def criar_usuario(
        self,
        nome_completo: str,
        usuario: str,
        senha: str,
        nivel_acesso: str,
        criado_por: int,
        permissoes: Optional[Dict[str, Dict[str, bool]]] = None,
    ) -> int:
        """
        Cria um novo usuario. Retorna o ID criado.

        Args:
            nome_completo: Nome exibido no sistema.
            usuario: Login unico (sera normalizado para lowercase).
            senha: Senha inicial (validada quanto a forca).
            nivel_acesso: 'mestre', 'operacional' ou 'comum'.
            criado_por: ID do usuario que esta criando (mestre).
            permissoes: Dict opcional {modulo: {acao: bool}} para usuarios comuns.

        Raises:
            ValueError: Dados invalidos ou usuario ja existente.
            SenhaFracaError: Senha nao atende requisitos.
        """
        self._exigir("criar")
        usuario_norm = usuario.strip().lower()
        if not usuario_norm:
            raise ValueError("Nome de usuario nao pode ser vazio.")
        if not nome_completo.strip():
            raise ValueError("Nome completo nao pode ser vazio.")
        if nivel_acesso not in ("mestre", "operacional", "comum"):
            raise ValueError(f"Nivel de acesso invalido: {nivel_acesso}")

        erro_senha = validar_forca_senha(senha)
        if erro_senha:
            raise SenhaFracaError(erro_senha)

        conn = conectar()
        cursor = conn.cursor()
        try:
            # Verificar se usuario ja existe
            cursor.execute(
                "SELECT id FROM usuarios WHERE usuario = ?", (usuario_norm,)
            )
            if cursor.fetchone():
                raise ValueError(f"Usuario '{usuario_norm}' ja existe.")

            salt = AuthService.gerar_salt()
            senha_hash = AuthService.hash_senha(senha, salt)
            agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            cursor.execute(
                """
                INSERT INTO usuarios (
                    nome_completo, usuario, senha_hash, senha_salt,
                    nivel_acesso, ativo, deve_alterar_senha,
                    tentativas_falhas, criado_por, criado_em, atualizado_em
                )
                VALUES (?, ?, ?, ?, ?, 1, 0, 0, ?, ?, ?)
                """,
                (
                    nome_completo.strip(),
                    usuario_norm,
                    senha_hash,
                    salt.hex(),
                    nivel_acesso,
                    criado_por,
                    agora,
                    agora,
                ),
            )
            novo_id = cursor.lastrowid

            # Salvar permissoes para usuarios comuns
            if nivel_acesso == "comum" and permissoes:
                self._salvar_permissoes_cursor(cursor, novo_id, permissoes)

            conn.commit()
            self._auditar("USUARIO_CRIADO", novo_id, usuario_criado=usuario_norm, nivel_acesso=nivel_acesso)
            logger.info(f"Usuario '{usuario_norm}' (ID {novo_id}) criado por ID {criado_por}.")
            return novo_id

        finally:
            conn.close()

    # ── Listar usuarios ────────────────────────────────────────────────────────

    def listar_usuarios(self) -> List[Dict[str, Any]]:
        """Retorna lista de todos os usuarios (para tela de gerenciamento)."""
        conn = conectar()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                SELECT id, nome_completo, usuario, nivel_acesso, ativo,
                       deve_alterar_senha, tentativas_falhas, bloqueado_ate,
                       ultimo_login, criado_por, criado_em
                FROM usuarios
                ORDER BY id
                """
            )
            resultado = []
            for row in cursor.fetchall():
                resultado.append(
                    {
                        "id": row[0],
                        "nome_completo": row[1],
                        "usuario": row[2],
                        "nivel_acesso": row[3],
                        "ativo": bool(row[4]),
                        "deve_alterar_senha": bool(row[5]),
                        "tentativas_falhas": row[6],
                        "bloqueado_ate": row[7],
                        "ultimo_login": row[8],
                        "criado_por": row[9],
                        "criado_em": row[10],
                    }
                )
            return resultado
        finally:
            conn.close()

    def obter_usuario(self, usuario_id: int) -> Optional[Dict[str, Any]]:
        """Retorna dados de um usuario especifico."""
        conn = conectar()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                SELECT id, nome_completo, usuario, nivel_acesso, ativo,
                       deve_alterar_senha, ultimo_login, criado_por, criado_em
                FROM usuarios WHERE id = ?
                """,
                (usuario_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return {
                "id": row[0],
                "nome_completo": row[1],
                "usuario": row[2],
                "nivel_acesso": row[3],
                "ativo": bool(row[4]),
                "deve_alterar_senha": bool(row[5]),
                "ultimo_login": row[6],
                "criado_por": row[7],
                "criado_em": row[8],
            }
        finally:
            conn.close()

    # ── Ativar / Desativar ────────────────────────────────────────────────────

    def ativar_usuario(self, usuario_id: int) -> None:
        self._exigir("editar")
        agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn = conectar()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                UPDATE usuarios SET ativo = 1, atualizado_em = ? WHERE id = ?
                """,
                (agora, usuario_id),
            )
            conn.commit()
            self._auditar("USUARIO_ATIVADO", usuario_id)
            logger.info(f"Usuario ID {usuario_id} ativado.")
        finally:
            conn.close()

    def desativar_usuario(self, usuario_id: int) -> None:
        self._exigir("editar")
        agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn = conectar()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                UPDATE usuarios SET ativo = 0, atualizado_em = ? WHERE id = ?
                """,
                (agora, usuario_id),
            )
            conn.commit()
            self._auditar("USUARIO_DESATIVADO", usuario_id)
            logger.info(f"Usuario ID {usuario_id} desativado.")
        finally:
            conn.close()

    # ── Nivel de acesso ────────────────────────────────────────────────────────

    def alterar_nivel_acesso(self, usuario_id: int, novo_nivel: str) -> None:
        self._exigir("editar")
        if novo_nivel not in ("mestre", "operacional", "comum"):
            raise ValueError(f"Nivel invalido: {novo_nivel}")

        agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn = conectar()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                UPDATE usuarios
                SET nivel_acesso = ?, atualizado_em = ?
                WHERE id = ?
                """,
                (novo_nivel, agora, usuario_id),
            )
            conn.commit()
            self._auditar("USUARIO_ATUALIZADO", usuario_id, novo_nivel=novo_nivel)
            logger.info(f"Usuario ID {usuario_id} alterado para nivel '{novo_nivel}'.")
        finally:
            conn.close()

    # ── Senha ─────────────────────────────────────────────────────────────────

    def redefinir_senha(self, usuario_id: int) -> str:
        self._exigir("editar")
        """
        Redefine a senha de um usuario (acao do mestre).
        Retorna a senha temporaria gerada.
        """
        senha_temp = self._gerar_senha_temporaria()
        salt = AuthService.gerar_salt()
        senha_hash = AuthService.hash_senha(senha_temp, salt)
        agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        conn = conectar()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                UPDATE usuarios
                SET senha_hash = ?, senha_salt = ?,
                    deve_alterar_senha = 1,
                    tentativas_falhas = 0, bloqueado_ate = NULL,
                    atualizado_em = ?
                WHERE id = ?
                """,
                (senha_hash, salt.hex(), agora, usuario_id),
            )
            conn.commit()
            self._auditar("USUARIO_ATUALIZADO", usuario_id, alteracao="senha_redefinida")
            logger.info(f"Senha do usuario ID {usuario_id} redefinida pelo mestre.")
            return senha_temp
        finally:
            conn.close()

    def alterar_propria_senha(
        self, usuario_id: int, senha_atual: str, nova_senha: str
    ) -> None:
        """
        Permite que qualquer usuario altere sua propria senha.

        Raises:
            ValueError: Senha atual incorreta.
            SenhaFracaError: Nova senha nao atende requisitos.
        """
        erro = validar_forca_senha(nova_senha)
        if erro:
            raise SenhaFracaError(erro)

        conn = conectar()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "SELECT senha_hash, senha_salt FROM usuarios WHERE id = ?",
                (usuario_id,),
            )
            row = cursor.fetchone()
            if not row:
                raise ValueError("Usuario nao encontrado.")

            if not AuthService.verificar_senha(senha_atual, row[0], row[1]):
                raise ValueError("Senha atual incorreta.")

            if senha_atual == nova_senha:
                raise ValueError("A nova senha deve ser diferente da atual.")

            salt = AuthService.gerar_salt()
            senha_hash = AuthService.hash_senha(nova_senha, salt)
            agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            cursor.execute(
                """
                UPDATE usuarios
                SET senha_hash = ?, senha_salt = ?,
                    deve_alterar_senha = 0, atualizado_em = ?
                WHERE id = ?
                """,
                (senha_hash, salt.hex(), agora, usuario_id),
            )
            conn.commit()
            logger.info(f"Usuario ID {usuario_id} alterou propria senha.")

            # A troca obrigatoria de primeiro acesso deve ser persistida.
            # O marcador adicional impede que o bootstrap volte a gerar uma
            # senha temporaria caso o banco seja substituido/perdido.
            try:
                from pathlib import Path
                Path(auth_service.arquivo_status_primeiro_acesso).parent.mkdir(parents=True, exist_ok=True)
                Path(auth_service.arquivo_status_primeiro_acesso).write_text(
                    "CONCLUIDO", encoding="utf-8"
                )
            except OSError:
                logger.warning("Nao foi possivel atualizar o marcador de primeiro acesso.")

            # Remover sessao salva pois a senha mudou
            auth_service._remover_sessao()

        finally:
            conn.close()

    # ── Excluir usuario ────────────────────────────────────────────────────────

    def excluir_usuario(self, usuario_id: int) -> None:
        self._exigir("excluir")
        conn = conectar()
        cursor = conn.cursor()
        try:
            # Impedir exclusao do proprio mestre logado
            if auth_service.usuario_atual and auth_service.usuario_atual["id"] == usuario_id:
                raise ValueError("Nao e possivel excluir o proprio usuario logado.")

            cursor.execute(
                "DELETE FROM permissoes_usuario WHERE usuario_id = ?", (usuario_id,)
            )
            cursor.execute("DELETE FROM usuarios WHERE id = ?", (usuario_id,))
            conn.commit()
            self._auditar("USUARIO_EXCLUIDO", usuario_id)
            logger.info(f"Usuario ID {usuario_id} excluido.")
        finally:
            conn.close()

    # ── Permissoes ─────────────────────────────────────────────────────────────

    def obter_permissoes(self, usuario_id: int) -> Dict[str, Dict[str, bool]]:
        """
        Retorna dict de permissoes do usuario:
        {
            "dashboard": {"visualizar": True, "criar": False, ...},
            ...
        }
        """
        conn = conectar()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                SELECT modulo, pode_visualizar, pode_criar, pode_editar,
                       pode_excluir, pode_exportar, pode_sincronizar
                FROM permissoes_usuario
                WHERE usuario_id = ?
                """,
                (usuario_id,),
            )
            resultado: Dict[str, Dict[str, bool]] = {}
            for row in cursor.fetchall():
                resultado[row[0]] = {
                    "visualizar": bool(row[1]),
                    "criar": bool(row[2]),
                    "editar": bool(row[3]),
                    "excluir": bool(row[4]),
                    "exportar": bool(row[5]),
                    "sincronizar": bool(row[6]),
                }

            # Preencher modulos sem permissao explicita com tudo False
            for modulo in MODULOS_PERMISSOES:
                if modulo not in resultado:
                    resultado[modulo] = {
                        "visualizar": False,
                        "criar": False,
                        "editar": False,
                        "excluir": False,
                        "exportar": False,
                        "sincronizar": False,
                    }

            return resultado
        finally:
            conn.close()

    def salvar_permissoes(
        self, usuario_id: int, permissoes: Dict[str, Dict[str, bool]]
    ) -> None:
        """Salva (substitui) todas as permissoes de um usuario."""
        self._exigir("editar")
        conn = conectar()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "DELETE FROM permissoes_usuario WHERE usuario_id = ?", (usuario_id,)
            )
            self._salvar_permissoes_cursor(cursor, usuario_id, permissoes)
            conn.commit()
            self._auditar("PERMISSAO_ALTERADA", usuario_id)
            logger.info(f"Permissoes do usuario ID {usuario_id} atualizadas.")
        finally:
            conn.close()

    # ── Helpers privados ───────────────────────────────────────────────────────

    @staticmethod
    def _salvar_permissoes_cursor(
        cursor, usuario_id: int, permissoes: Dict[str, Dict[str, bool]]
    ) -> None:
        for modulo, acoes in permissoes.items():
            if modulo not in MODULOS_PERMISSOES:
                continue
            cursor.execute(
                """
                INSERT OR REPLACE INTO permissoes_usuario
                    (usuario_id, modulo, pode_visualizar, pode_criar,
                     pode_editar, pode_excluir, pode_exportar, pode_sincronizar)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    usuario_id,
                    modulo,
                    int(acoes.get("visualizar", False)),
                    int(acoes.get("criar", False)),
                    int(acoes.get("editar", False)),
                    int(acoes.get("excluir", False)),
                    int(acoes.get("exportar", False)),
                    int(acoes.get("sincronizar", False)),
                ),
            )

    @staticmethod
    def _gerar_senha_temporaria(tamanho: int = 12) -> str:
        """Gera senha temporaria forte para redefinicao."""
        letras_maiusculas = string.ascii_uppercase
        letras_minusculas = string.ascii_lowercase
        digitos = string.digits
        especiais = "!@#$%&*"
        # Garante pelo menos um de cada tipo
        senha = [
            secrets.choice(letras_maiusculas),
            secrets.choice(letras_minusculas),
            secrets.choice(digitos),
            secrets.choice(especiais),
        ]
        todos = letras_maiusculas + letras_minusculas + digitos + especiais
        senha += [secrets.choice(todos) for _ in range(tamanho - 4)]
        # Embaralhar
        senha_list = list(senha)
        secrets.SystemRandom().shuffle(senha_list)
        return "".join(senha_list)


    def atualizar_dados(self, usuario_id: int, nome_completo: str, nivel_acesso: str) -> None:
        self._exigir("editar")
        if not nome_completo.strip():
            raise ValueError("Nome completo não pode ser vazio.")
        if nivel_acesso not in ("mestre", "operacional", "comum"):
            raise ValueError(f"Nivel invalido: {nivel_acesso}")
        agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn = conectar()
        try:
            conn.execute("UPDATE usuarios SET nome_completo=?, nivel_acesso=?, atualizado_em=? WHERE id=?", (nome_completo.strip(), nivel_acesso, agora, usuario_id))
            conn.commit()
            self._auditar("USUARIO_ATUALIZADO", usuario_id, nivel_acesso=nivel_acesso)
        finally:
            conn.close()

usuario_service = UsuarioService()
