"""Regras de disponibilidade operacional da frota."""

from enum import Enum


class StatusVeiculo(str, Enum):
    ATIVO = "ATIVO"
    MANUTENCAO = "MANUTENÇÃO"
    INATIVO = "INATIVO"


def normalizar_status(valor):
    texto = str(valor or "").strip().lower()
    aliases = {
        "ativo": StatusVeiculo.ATIVO,
        "manutencao": StatusVeiculo.MANUTENCAO,
        "manutenção": StatusVeiculo.MANUTENCAO,
        "inativo": StatusVeiculo.INATIVO,
    }
    try:
        return aliases[texto]
    except KeyError as exc:
        raise ValueError(f"Status de veículo inválido: {valor!r}.") from exc


def validar_uso_em_viagem(status):
    status = normalizar_status(status)
    if status is not StatusVeiculo.ATIVO:
        raise ValueError(
            f"Veículo {status.value.lower()} não pode ser utilizado em uma nova viagem."
        )
    return True
