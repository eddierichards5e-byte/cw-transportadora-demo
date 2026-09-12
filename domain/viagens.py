"""Máquina de estados das notas e viagens."""

from enum import Enum


class StatusNota(str, Enum):
    DISPONIVEL = "Disponível"
    EM_VIAGEM = "Em viagem"
    ENTREGUE = "Entregue"
    FINALIZADA = "Finalizada"


class StatusViagem(str, Enum):
    EM_VIAGEM = "Em viagem"
    EM_ROTA = "Em rota"
    EM_TRANSITO = "Em trânsito"
    FINALIZADA = "Finalizada"


_TRANSICOES_NOTA = {
    StatusNota.DISPONIVEL: {StatusNota.EM_VIAGEM},
    StatusNota.EM_VIAGEM: {StatusNota.ENTREGUE},
    StatusNota.ENTREGUE: {StatusNota.FINALIZADA},
    StatusNota.FINALIZADA: set(),
}

_TRANSICOES_VIAGEM = {
    StatusViagem.EM_VIAGEM: {StatusViagem.EM_ROTA, StatusViagem.EM_TRANSITO, StatusViagem.FINALIZADA},
    StatusViagem.EM_ROTA: {StatusViagem.EM_TRANSITO, StatusViagem.FINALIZADA},
    StatusViagem.EM_TRANSITO: {StatusViagem.FINALIZADA},
    StatusViagem.FINALIZADA: set(),
}


def _normalizar(valor, enum_cls):
    texto = str(valor or "").strip().lower()
    for item in enum_cls:
        if item.value.lower() == texto:
            return item
    # tolera grafia sem acento em dados históricos
    equivalencias = {
        "disponivel": "Disponível",
        "em transito": "Em trânsito",
        "finalizado": "Finalizada",
    }
    convertido = equivalencias.get(texto, valor)
    for item in enum_cls:
        if item.value.lower() == str(convertido).lower():
            return item
    raise ValueError(f"Status inválido: {valor!r}.")


def validar_transicao_nota(atual, novo):
    atual = _normalizar(atual, StatusNota)
    novo = _normalizar(novo, StatusNota)
    if atual == novo:
        return True
    if novo not in _TRANSICOES_NOTA[atual]:
        raise ValueError(f"Transição de nota não permitida: {atual.value} → {novo.value}.")
    return True


def validar_transicao_viagem(atual, novo):
    atual = _normalizar(atual, StatusViagem)
    novo = _normalizar(novo, StatusViagem)
    if atual == novo:
        return True
    if novo not in _TRANSICOES_VIAGEM[atual]:
        raise ValueError(f"Transição de viagem não permitida: {atual.value} → {novo.value}.")
    return True
