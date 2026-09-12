"""
Funções auxiliares compartilhadas para formatação e validação.
Centraliza lógica repetida em múltiplas telas.
"""

from typing import Union, Optional
from datetime import datetime


def formatar_moeda(valor: Union[float, int, str, None]) -> str:
    """
    Formata valor para formato de moeda brasileiro (R$).
    
    Args:
        valor: Valor numérico ou string
        
    Returns:
        String formatada como moeda brasileira
    """
    try:
        valor_float = float(valor or 0)
        return f"R$ {valor_float:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (ValueError, TypeError):
        return "R$ 0,00"


def formatar_peso(valor: Union[float, int, str, None]) -> str:
    """
    Formata valor para formato de peso em kg.
    
    Args:
        valor: Valor numérico ou string
        
    Returns:
        String formatada como peso em kg
    """
    try:
        valor_float = float(valor or 0)
        return f"{valor_float:,.2f} kg".replace(",", "X").replace(".", ",").replace("X", ".")
    except (ValueError, TypeError):
        return "0,00 kg"


def formatar_data(data: Union[str, datetime, None], formato: str = "%d/%m/%Y") -> str:
    """
    Formata data para string brasileira.
    
    Args:
        data: Data como string ou datetime
        formato: Formato de saída (padrão: %d/%m/%Y)
        
    Returns:
        String formatada como data brasileira
    """
    if not data:
        return "-"
    
    if isinstance(data, str):
        try:
            data = datetime.strptime(data, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            try:
                data = datetime.strptime(data, "%d/%m/%Y")
            except ValueError:
                return data
    
    if isinstance(data, datetime):
        return data.strftime(formato)
    
    return str(data)


def formatar_data_hora(data: Union[str, datetime, None]) -> str:
    """
    Formata data e hora para string brasileira.
    
    Args:
        data: Data como string ou datetime
        
    Returns:
        String formatada como data e hora brasileira
    """
    return formatar_data(data, "%d/%m/%Y %H:%M")


def parse_numero(valor: str, default: float = 0.0) -> float:
    """
    Converte string para número float, tratando vírgula como separador decimal.
    
    Args:
        valor: String numérica (pode ter vírgula ou ponto)
        default: Valor padrão em caso de erro
        
    Returns:
        Valor float convertido
    """
    if not valor:
        return default
    
    try:
        valor_limpo = str(valor).strip().replace(" ", "")

        if "," in valor_limpo and "." in valor_limpo:
            valor_limpo = valor_limpo.replace(".", "").replace(",", ".")
        elif "," in valor_limpo:
            valor_limpo = valor_limpo.replace(",", ".")

        return float(valor_limpo)
    except (ValueError, TypeError):
        return default


def parse_inteiro(valor: str, default: int = 0) -> int:
    """
    Converte string para inteiro.
    
    Args:
        valor: String numérica
        default: Valor padrão em caso de erro
        
    Returns:
        Valor inteiro convertido
    """
    if not valor:
        return default
    
    try:
        return int(str(valor).strip())
    except (ValueError, TypeError):
        return default


def validar_cnpj(cnpj: str) -> bool:
    """
    Valida CNPJ brasileiro (inclui dígitos verificadores).
    """
    from utils.validators import validate_cnpj

    valido, _ = validate_cnpj(cnpj)
    return valido


def validar_placa(placa: str) -> bool:
    """
    Valida formato básico de placa de veículo.
    
    Args:
        placa: String da placa
        
    Returns:
        True se formato válido, False caso contrário
    """
    if not placa:
        return False
    
    placa = placa.upper().strip()
    
    # Formato antigo: ABC-1234
    if len(placa) == 8 and placa[3] == "-":
        return True
    
    # Formato novo Mercosul: ABC1D23
    if len(placa) == 7:
        return True
    
    # Formato sem traço: ABC1234
    if len(placa) == 7 and placa[3].isdigit():
        return True
    
    return False


def truncar_texto(texto: str, max_len: int = 50, sufixo: str = "...") -> str:
    """
    Trunca texto se exceder tamanho máximo.
    
    Args:
        texto: Texto a truncar
        max_len: Tamanho máximo
        sufixo: Sufixo a adicionar quando truncado
        
    Returns:
        Texto truncado ou original
    """
    if not texto:
        return ""
    
    if len(texto) <= max_len:
        return texto
    
    return texto[:max_len - len(sufixo)] + sufixo


def normalizar_texto(texto: str) -> str:
    """
    Normaliza texto: remove espaços extras e converte para título.
    
    Args:
        texto: Texto a normalizar
        
    Returns:
        Texto normalizado
    """
    if not texto:
        return ""
    
    return " ".join(texto.strip().split()).title()


def calcular_porcentagem(parte: float, total: float) -> float:
    """
    Calcula porcentagem de parte em relação ao total.
    
    Args:
        parte: Valor da parte
        total: Valor total
        
    Returns:
        Porcentagem calculada
    """
    if total == 0:
        return 0.0
    
    return (parte / total) * 100


def formatar_porcentagem(valor: float, casas: int = 1) -> str:
    """
    Formata valor como porcentagem.
    
    Args:
        valor: Valor numérico
        casas: Número de casas decimais
        
    Returns:
        String formatada como porcentagem
    """
    return f"{valor:.{casas}f}%"


def obter_iniciais(nome: str, max_iniciais: int = 2) -> str:
    """
    Obtém iniciais de um nome.
    
    Args:
        nome: Nome completo
        max_iniciais: Máximo de iniciais
        
    Returns:
        Iniciais do nome
    """
    if not nome:
        return ""
    
    partes = nome.strip().split()
    iniciais = [p[0].upper() for p in partes if p]
    
    return "".join(iniciais[:max_iniciais])


def mascara_cnpj(cnpj: str) -> str:
    """
    Aplica máscara de formatação ao CNPJ.
    
    Args:
        cnpj: CNPJ sem máscara
        
    Returns:
        CNPJ com máscara (XX.XXX.XXX/XXXX-XX)
    """
    if not cnpj:
        return ""
    
    cnpj_limpo = "".join(filter(str.isdigit, cnpj))
    
    if len(cnpj_limpo) != 14:
        return cnpj
    
    return f"{cnpj_limpo[:2]}.{cnpj_limpo[2:5]}.{cnpj_limpo[5:8]}/{cnpj_limpo[8:12]}-{cnpj_limpo[12:]}"


def mascara_placa(placa: str) -> str:
    """
    Aplica máscara de formatação à placa.
    
    Args:
        placa: Placa sem máscara
        
    Returns:
        Placa com máscara (ABC-1234)
    """
    if not placa:
        return ""
    
    placa = placa.upper().strip()
    placa_limpa = "".join(filter(str.isalnum, placa))
    
    if len(placa_limpa) == 7:
        # Formato Mercosul ou sem traço
        if placa_limpa[3].isdigit():
            return f"{placa_limpa[:3]}-{placa_limpa[3:]}"
        else:
            return placa_limpa.upper()
    
    return placa.upper()


def status_para_cor(status: str) -> str:
    """
    Retorna cor baseada no status.
    
    Args:
        status: String do status
        
    Returns:
        Código hex da cor
    """
    cores = {
        "Disponível": "#16A34A",
        "Em viagem": "#F59E0B",
        "Entregue": "#2563EB",
        "Finalizada": "#16A34A",
        "Pendente": "#6B7280",
        "Cancelada": "#DC2626",
        "Ativo": "#16A34A",
        "Inativo": "#6B7280"
    }
    
    return cores.get(status, "#6B7280")
