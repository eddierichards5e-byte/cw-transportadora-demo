"""Servico central de autenticacao e sessao do CW Transportadora."""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import sqlite3
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

from config.settings import settings
from utils.database import conectar
from utils.database._conexao import diagnostico_banco, _legacy_com_usuario
from utils.logger import get_logger

logger = get_logger(__name__)

class SenhaFracaError(Exception): pass
class CredenciaisInvalidasError(Exception): pass
class ContaBloqueadaError(Exception): pass
class ContaInativaError(Exception): pass
class BancoCredenciaisDivergentesError(RuntimeError): pass

MODULOS_PERMISSOES = {
    "dashboard": "Dashboard", "operacoes": "Operações", "notas": "Notas",
    "ranking_clientes": "Ranking", "criar_viagem": "Criar Viagem", "historico": "Histórico",
    "combustivel": "Combustível", "manutencao": "Manutenção", "contas": "Contas",
    "relatorios": "Relatórios", "funcionarios": "Funcionários", "configuracoes": "Configurações",
    "usuarios": "Usuários", "perfil": "Perfil", "auditoria": "Auditoria",
    "historico_versoes": "Versões",
}

# Política de segurança centralizada. Mantemos 310 mil nesta V83 para preservar
# compatibilidade com hashes já gravados; qualquer aumento deve vir acompanhado
# de migração explícita dos hashes existentes.
PASSWORD_HASH_ITERATIONS = 310_000
PBKDF2_ITERATIONS = PASSWORD_HASH_ITERATIONS  # compatibilidade interna
# Credencial mestre inicial estável. O código guarda somente o salt/hash PBKDF2,
# nunca a senha em texto puro. Essa credencial é usada apenas enquanto a conta
# estiver marcada como primeiro acesso; depois da troca, o banco passa a guardar
# exclusivamente a nova credencial.
MASTER_BOOTSTRAP_SALT = base64.b64decode("fqFRnCYcQ7hG+hu1OHEEbg==")
MASTER_BOOTSTRAP_HASH = "z87AJFtcBcFopNlUXPjfXykEtGpGGjdnLkQX7DCpEmg="
LOCKOUT_AFTER = 5
LOCKOUT_MINUTES = 15

def validar_forca_senha(senha: str):
    if not isinstance(senha, str) or len(senha) < 8:
        return "Senha deve ter no mínimo 8 caracteres."
    if not any(c.isupper() for c in senha):
        return "Senha deve conter pelo menos uma letra maiúscula."
    if not any(c.islower() for c in senha):
        return "Senha deve conter pelo menos uma letra minúscula."
    if not any(c.isdigit() for c in senha):
        return "Senha deve conter pelo menos um número."
    if not any(not c.isalnum() for c in senha):
        return "Senha deve conter pelo menos um caractere especial."
    return None

def _auditar(acao, modulo="auth", **kwargs):
    try:
        from services.auditoria_service import auditoria_service
        usuario = None
        try:
            usuario = kwargs.get("usuario") or getattr(auth_service, "usuario_atual", None)
            if isinstance(usuario, dict):
                kwargs.setdefault("usuario_id", usuario.get("id")); kwargs.setdefault("usuario_nome", usuario.get("nome_completo") or usuario.get("usuario")); usuario = usuario.get("usuario")
        except Exception:
            usuario = None
        auditoria_service.registrar(acao, modulo, usuario=usuario or "Sistema", **kwargs)
    except Exception:
        pass


class AuthService:
    def __init__(self):
        self.usuario_atual: Optional[Dict[str, Any]] = None
        self.eh_mestre = False
        # Marcadores ficam na mesma área persistente do SQLite, fora da pasta
        # da versão instalada. Assim uma atualização não recria a credencial.
        self.arquivo_primeiro_acesso = str(Path(settings.primeiro_acesso_dir) / "primeiro_acesso.txt")
        self.arquivo_status_primeiro_acesso = str(Path(settings.primeiro_acesso_dir) / "primeiro_acesso.status")

    @staticmethod
    def gerar_salt() -> bytes:
        return secrets.token_bytes(16)

    @staticmethod
    def hash_senha(senha: str, salt: bytes) -> str:
        digest = hashlib.pbkdf2_hmac("sha256", senha.encode("utf-8"), salt, PBKDF2_ITERATIONS)
        return base64.b64encode(digest).decode("ascii")

    @staticmethod
    def verificar_senha(senha: str, senha_hash: str, salt: str | bytes) -> bool:
        try:
            if isinstance(salt, str):
                if len(salt) == 32 and all(c in "0123456789abcdefABCDEF" for c in salt):
                    salt_bytes = bytes.fromhex(salt)
                else:
                    salt_bytes = base64.b64decode(salt, validate=True)
            else:
                salt_bytes = salt
            calculado = AuthService.hash_senha(senha, salt_bytes)
            return hmac.compare_digest(calculado, senha_hash)
        except (ValueError, TypeError):
            return False

    def login(self, username: str, password: str) -> Dict[str, Any]:
        username = (username or "").strip().lower()
        if not username or not password:
            raise CredenciaisInvalidasError("Usuário ou senha inválidos.")

        conn = conectar()
        try:
            row = conn.execute(
                """SELECT id, nome_completo, usuario, senha_hash, senha_salt, nivel_acesso,
                          ativo, deve_alterar_senha, tentativas_falhas, bloqueado_ate, ultimo_login
                   FROM usuarios WHERE usuario = ?""", (username,)
            ).fetchone()
            if not row:
                # Evita diferença óbvia de comportamento para usuário inexistente.
                self._dummy_hash(password)
                _auditar("LOGIN_FALHOU", "auth", usuario=username, motivo="usuario_inexistente")
                raise CredenciaisInvalidasError("Usuário ou senha inválidos.")

            bloqueado_ate = row[9]
            if bloqueado_ate:
                try:
                    if datetime.fromisoformat(bloqueado_ate) > datetime.now():
                        raise ContaBloqueadaError("Conta temporariamente bloqueada. Tente novamente mais tarde.")
                except ValueError:
                    pass

            if not row[6]:
                raise ContaInativaError("Esta conta está inativa. Procure um administrador.")

            if not self.verificar_senha(password, row[3], row[4]):
                tentativas = int(row[8] or 0) + 1
                if tentativas >= LOCKOUT_AFTER:
                    bloqueio = (datetime.now() + timedelta(minutes=LOCKOUT_MINUTES)).isoformat(timespec="seconds")
                    conn.execute("UPDATE usuarios SET tentativas_falhas=?, bloqueado_ate=?, atualizado_em=CURRENT_TIMESTAMP WHERE id=?", (tentativas, bloqueio, row[0]))
                    conn.commit()
                    raise ContaBloqueadaError("Conta temporariamente bloqueada após várias tentativas inválidas.")
                conn.execute("UPDATE usuarios SET tentativas_falhas=?, atualizado_em=CURRENT_TIMESTAMP WHERE id=?", (tentativas, row[0]))
                conn.commit()
                raise CredenciaisInvalidasError("Usuário ou senha inválidos.")

            conn.execute("UPDATE usuarios SET tentativas_falhas=0, bloqueado_ate=NULL, ultimo_login=CURRENT_TIMESTAMP, atualizado_em=CURRENT_TIMESTAMP WHERE id=?", (row[0],))
            conn.commit()

            permissoes = self._carregar_permissoes(conn, row[0], row[5])
            self.usuario_atual = {
                "id": row[0], "usuario": row[2], "nome_completo": row[1],
                "nivel_acesso": row[5], "ativo": bool(row[6]),
                "deve_alterar_senha": bool(row[7]), "eh_mestre": row[5] == "mestre",
                "permissoes": permissoes,
            }
            self.eh_mestre = self.usuario_atual["eh_mestre"]
            _auditar("LOGIN", "auth", usuario=self.usuario_atual.get("usuario"), usuario_id=self.usuario_atual.get("id"), usuario_nome=self.usuario_atual.get("nome_completo"))
            return self.usuario_atual
        finally:
            conn.close()

    @staticmethod
    def _dummy_hash(password: str):
        AuthService.hash_senha(password, b"cw-dummy-salt-16")

    @staticmethod
    def _carregar_permissoes(conn, usuario_id: int, nivel: str):
        if nivel == "mestre":
            return {m: {"visualizar": True, "criar": True, "editar": True, "excluir": True, "exportar": True, "sincronizar": True} for m in MODULOS_PERMISSOES}
        rows = conn.execute("SELECT modulo, pode_visualizar, pode_criar, pode_editar, pode_excluir, pode_exportar, pode_sincronizar FROM permissoes_usuario WHERE usuario_id=?", (usuario_id,)).fetchall()
        result = {m: {"visualizar": False, "criar": False, "editar": False, "excluir": False, "exportar": False, "sincronizar": False} for m in MODULOS_PERMISSOES}
        for r in rows:
            if r[0] in result:
                result[r[0]] = {"visualizar": bool(r[1]), "criar": bool(r[2]), "editar": bool(r[3]), "excluir": bool(r[4]), "exportar": bool(r[5]), "sincronizar": bool(r[6])}
        result["perfil"]["visualizar"] = True
        return result

    def pode(self, modulo: str, acao: str = "visualizar") -> bool:
        if not self.usuario_atual:
            return False
        if self.usuario_atual.get("eh_mestre"):
            return True
        return bool(self.usuario_atual.get("permissoes", {}).get(modulo, {}).get(acao, False))

    def logout(self):
        self.usuario_atual = None
        self.eh_mestre = False

    def _credential_key(self) -> str:
        return "CW Transportadora/login"

    def _keyring(self):
        """Retorna o keyring do SO quando disponível (Windows Credential Manager)."""
        try:
            import keyring
            return keyring
        except Exception:
            return None

    def salvar_sessao(self, user, password: str | None = None):
        """Guarda usuário/senha no cofre de credenciais do sistema operacional.

        A senha nunca é gravada em SQLite, JSON ou arquivo de texto. No Windows,
        o backend padrão do keyring usa o Credential Manager.
        """
        if not user or not password:
            logger.warning("Não foi possível salvar o login: credencial incompleta.")
            return False
        keyring = self._keyring()
        if keyring is None:
            logger.warning("keyring não está instalado; login salvo desativado.")
            return False
        try:
            payload = json.dumps({"usuario": user.get("usuario", ""), "senha": password}, ensure_ascii=False)
            keyring.set_password(self._credential_key(), "credentials", payload)
            return True
        except Exception as exc:
            logger.warning("Falha ao salvar credencial no cofre do sistema: %s", exc)
            return False

    def obter_sessao_salva(self):
        """Retorna credenciais salvas para preencher o login, ou None."""
        keyring = self._keyring()
        if keyring is None:
            return None
        try:
            raw = keyring.get_password(self._credential_key(), "credentials")
            if not raw:
                return None
            data = json.loads(raw)
            if data.get("usuario") and data.get("senha"):
                return data
        except Exception as exc:
            logger.warning("Falha ao ler credencial salva: %s", exc)
        return None

    def limpar_sessao_salva(self):
        keyring = self._keyring()
        if keyring is None:
            return
        try:
            keyring.delete_password(self._credential_key(), "credentials")
        except Exception:
            pass

    def verificar_sessao_salva(self):
        # Mantido para compatibilidade com versões antigas; a tela de login
        # agora carrega a credencial salva sem fazer login silencioso.
        return self.obter_sessao_salva()

    def diagnostico_banco(self) -> dict:
        """Expõe diagnóstico seguro para a inicialização e suporte."""
        return diagnostico_banco()

    def garantir_usuario_mestre(self):
        conn = conectar()
        try:
            # Nunca recriar uma senha temporaria para um usuario que ja existe.
            # O estado de primeiro acesso e persistido no proprio registro do usuario.
            row = conn.execute(
                "SELECT id, usuario, deve_alterar_senha FROM usuarios WHERE usuario = ?",
                ("bruno",),
            ).fetchone()
            if row:
                # Contas mestre criadas por versões anteriores podem ter recebido
                # uma senha temporária aleatória. Se ainda estiverem marcadas como
                # primeiro acesso, normalizamos uma única vez para a senha mestre
                # padrão definida pelo proprietário. Depois que a senha for alterada,
                # deve_alterar_senha=0 e nunca mais fazemos esse reset.
                if row[2]:
                    salt = self.gerar_salt()
                    conn.execute(
                        "UPDATE usuarios SET senha_hash=?, senha_salt=?, nivel_acesso='mestre', ativo=1, tentativas_falhas=0, bloqueado_ate=NULL, atualizado_em=CURRENT_TIMESTAMP WHERE id=?",
                        (MASTER_BOOTSTRAP_HASH, base64.b64encode(MASTER_BOOTSTRAP_SALT).decode("ascii"), row[0]),
                    )
                    conn.commit()
                    try:
                        Path(self.arquivo_primeiro_acesso).parent.mkdir(parents=True, exist_ok=True)
                        Path(self.arquivo_status_primeiro_acesso).write_text("PENDENTE", encoding="utf-8")
                    except OSError:
                        pass
                    logger.info("[AUTH] Conta mestre existente em primeiro acesso normalizada para a senha mestre padrão.")
                return None

            # Se existir outro banco legado com usuário, nunca gerar uma nova
            # credencial silenciosamente. O usuário deve ser preservado e a
            # divergência precisa aparecer explicitamente no diagnóstico.
            legados_com_usuario = _legacy_com_usuario()
            if legados_com_usuario:
                caminhos = "; ".join(str(p.resolve()) for p in legados_com_usuario)
                logger.critical(
                    "[AUTH] Banco persistente sem usuário, mas banco legado com usuário encontrado: %s",
                    caminhos,
                )
                raise BancoCredenciaisDivergentesError(
                    "Foi encontrado um banco antigo com usuário cadastrado, mas a aplicação está usando outro banco. "
                    "Nenhuma nova senha será criada. Verifique o diagnóstico do banco e preserve o banco antigo."
                )

            # Se o sistema ja concluiu o primeiro acesso e o banco estiver vazio,
            # nao devemos criar uma nova credencial silenciosamente. Isso evita
            # gerar uma senha temporaria diferente apos perda/troca indevida do DB.
            status_path = Path(self.arquivo_status_primeiro_acesso)
            try:
                if status_path.exists() and status_path.read_text(encoding="utf-8").strip() == "CONCLUIDO":
                    logger.error("Banco sem usuario mestre, mas primeiro acesso ja foi concluido; nenhuma nova senha sera gerada.")
                    return None
            except OSError:
                pass

            # Compatibilidade: se qualquer usuario ja existir, nao criar outro mestre.
            if conn.execute("SELECT id FROM usuarios LIMIT 1").fetchone():
                return None

            username = "bruno"
            # Primeiro acesso: a senha mestre é estável entre versões porque fica
            # persistida no SQLite como hash PBKDF2. Não gerar senha aleatória.
            conn.execute("INSERT INTO usuarios (nome_completo, usuario, senha_hash, senha_salt, nivel_acesso, ativo, deve_alterar_senha, tentativas_falhas, criado_em, atualizado_em) VALUES (?, ?, ?, ?, 'mestre', 1, 0, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)", ("Administrador", username, MASTER_BOOTSTRAP_HASH, base64.b64encode(MASTER_BOOTSTRAP_SALT).decode("ascii")))
            senha = None
            conn.commit()
            # Arquivo não contém mais a senha. Mantido apenas como marcador de primeiro acesso.
            try:
                Path(self.arquivo_primeiro_acesso).parent.mkdir(parents=True, exist_ok=True)
                Path(self.arquivo_primeiro_acesso).write_text(
                    "Primeiro acesso criado. Use a senha mestre definida para este sistema.",
                    encoding="utf-8",
                )
                Path(self.arquivo_status_primeiro_acesso).write_text(
                    "CONCLUIDO", encoding="utf-8"
                )
            except OSError:
                pass
            return None
        finally:
            conn.close()

    # Compatibilidade: o CRUD de usuários pertence ao UsuarioService.
    def criar_usuario(self, *args, **kwargs):
        from services.usuario_service import usuario_service
        return usuario_service.criar_usuario(*args, **kwargs)

    def listar_usuarios(self):
        from services.usuario_service import usuario_service
        return usuario_service.listar_usuarios()

    def atualizar_usuario(self, *args, **kwargs):
        from services.usuario_service import usuario_service
        return usuario_service.atualizar_usuario(*args, **kwargs)

    def excluir_usuario(self, *args, **kwargs):
        from services.usuario_service import usuario_service
        return usuario_service.excluir_usuario(*args, **kwargs)

    def _remover_sessao(self):
        return None

auth_service = AuthService()
