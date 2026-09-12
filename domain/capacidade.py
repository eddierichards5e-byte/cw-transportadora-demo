"""Validação de carga sem dependência de banco ou interface."""


def validar_capacidade(*, peso_total=0, capacidade_kg=0, cubagem_total=0, capacidade_m3=0, tipo_carga=None, tipos_permitidos=None):
    peso_total = float(peso_total or 0)
    capacidade_kg = float(capacidade_kg or 0)
    cubagem_total = float(cubagem_total or 0)
    capacidade_m3 = float(capacidade_m3 or 0)

    if peso_total < 0 or cubagem_total < 0:
        raise ValueError("Peso e cubagem da carga não podem ser negativos.")
    if capacidade_kg > 0 and peso_total > capacidade_kg:
        raise ValueError(f"Peso {peso_total:,.0f} kg excede a capacidade de {capacidade_kg:,.0f} kg.")
    if capacidade_m3 > 0 and cubagem_total > capacidade_m3:
        raise ValueError(f"Cubagem {cubagem_total:,.2f} m³ excede a capacidade de {capacidade_m3:,.2f} m³.")
    if tipos_permitidos and tipo_carga:
        permitidos = {str(v).strip().lower() for v in tipos_permitidos}
        if str(tipo_carga).strip().lower() not in permitidos:
            raise ValueError(f"Tipo de carga não permitido para este veículo: {tipo_carga}.")
    return True
