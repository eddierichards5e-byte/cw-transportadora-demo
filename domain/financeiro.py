"""Cálculo financeiro de rentabilidade de uma viagem."""


def calcular_rentabilidade(*, frete_recebido=0, combustivel=0, pedagio=0, motorista=0, outros=0):
    receita = float(frete_recebido or 0)
    custos = {
        "combustivel": float(combustivel or 0),
        "pedagio": float(pedagio or 0),
        "motorista": float(motorista or 0),
        "outros": float(outros or 0),
    }
    if receita < 0 or any(valor < 0 for valor in custos.values()):
        raise ValueError("Receita e custos não podem ser negativos.")
    custo_total = sum(custos.values())
    lucro = receita - custo_total
    margem = (lucro / receita * 100) if receita else 0.0
    return {
        "frete_recebido": receita,
        **custos,
        "custo_total": custo_total,
        "lucro": lucro,
        "margem_percentual": margem,
    }
