"""Guarda de autorização para operações de negócio."""
from services.auth_service import auth_service
from services.auditoria_service import auditoria_service, ACAO_ACESSO_NEGADO

def exigir_permissao(modulo: str, acao: str = "visualizar") -> None:
    if not auth_service.usuario_atual:
        raise PermissionError("Usuário não autenticado.")
    if not auth_service.pode(modulo, acao):
        u = auth_service.usuario_atual
        auditoria_service.registrar(ACAO_ACESSO_NEGADO, modulo, usuario=u.get("usuario"), usuario_id=u.get("id"), usuario_nome=u.get("nome_completo"), acao_solicitada=acao)
        raise PermissionError(f"Sem permissão para {acao} no módulo {modulo}.")
