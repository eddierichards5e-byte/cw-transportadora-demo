"""
Utilitários de validação e sanitização de dados.
Fornece funções para validar e limpar entradas do usuário.
"""

from __future__ import annotations

import re
from typing import Optional, Tuple
from datetime import datetime


class ValidationError(Exception):
    """Exceção lançada quando validação falha."""
    pass


def sanitize_string(text: str, max_length: int = 255) -> str:
    """
    Sanitiza uma string removendo caracteres perigosos.
    
    Args:
        text: Texto a ser sanitizado
        max_length: Comprimento máximo permitido
        
    Returns:
        String sanitizada
    """
    if not text:
        return ""
    
    # Remove caracteres de controle exceto nova linha e tabulação
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', str(text))
    
    # Remove espaços extras
    text = ' '.join(text.split())
    
    # Trunca se necessário
    if len(text) > max_length:
        text = text[:max_length]
    
    return text.strip()


def sanitize_number(value: any, default: float = 0.0) -> float:
    """
    Sanitiza um valor numérico.
    
    Args:
        value: Valor a ser sanitizado
        default: Valor padrão se inválido
        
    Returns:
        Float sanitizado
    """
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def sanitize_integer(value: any, default: int = 0) -> int:
    """
    Sanitiza um valor inteiro.
    
    Args:
        value: Valor a ser sanitizado
        default: Valor padrão se inválido
        
    Returns:
        Inteiro sanitizado
    """
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def validate_cnpj(cnpj: str) -> Tuple[bool, str]:
    """
    Valida CNPJ brasileiro.
    
    Args:
        cnpj: CNPJ a ser validado (com ou sem formatação)
        
    Returns:
        Tuple (valido, mensagem_erro)
    """
    if not cnpj:
        return False, "CNPJ não informado"
    
    # Remove caracteres não numéricos
    cnpj = re.sub(r'\D', '', cnpj)
    
    # Verifica tamanho
    if len(cnpj) != 14:
        return False, "CNPJ deve ter 14 dígitos"
    
    # Verifica se todos são iguais
    if cnpj == cnpj[0] * 14:
        return False, "CNPJ inválido"
    
    # Cálculo dos dígitos verificadores
    def calcular_digito(cnpj_num: str, pesos: list) -> int:
        total = 0
        for i in range(len(pesos)):
            total += int(cnpj_num[i]) * pesos[i]
        resto = total % 11
        return 0 if resto < 2 else 11 - resto
    
    pesos1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    pesos2 = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    
    digito1 = calcular_digito(cnpj[:12], pesos1)
    digito2 = calcular_digito(cnpj[:12] + str(digito1), pesos2)
    
    if int(cnpj[12]) != digito1 or int(cnpj[13]) != digito2:
        return False, "CNPJ inválido"
    
    return True, ""


def validate_placa(placa: str) -> Tuple[bool, str]:
    """
    Valida placa de veículo brasileiro (antigo e novo formato).
    
    Args:
        placa: Placa a ser validada
        
    Returns:
        Tuple (valido, mensagem_erro)
    """
    if not placa:
        return False, "Placa não informada"
    
    placa = placa.upper().strip()
    
    # Formato antigo: ABC-1234
    padrao_antigo = r'^[A-Z]{3}-\d{4}$'
    # Formato novo Mercosul: ABC1D23
    padrao_novo = r'^[A-Z]{3}\d[A-Z]\d{2}$'
    
    if re.match(padrao_antigo, placa):
        return True, ""
    
    if re.match(padrao_novo, placa):
        return True, ""
    
    return False, "Placa inválida (use ABC-1234 ou ABC1D23)"


def validate_email(email: str) -> Tuple[bool, str]:
    """
    Valida endereço de e-mail.
    
    Args:
        email: E-mail a ser validado
        
    Returns:
        Tuple (valido, mensagem_erro)
    """
    if not email:
        return False, "E-mail não informado"
    
    padrao = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    
    if not re.match(padrao, email):
        return False, "E-mail inválido"
    
    return True, ""


def validate_telefone(telefone: str) -> Tuple[bool, str]:
    """
    Valida número de telefone brasileiro.
    
    Args:
        telefone: Telefone a ser validado
        
    Returns:
        Tuple (valido, mensagem_erro)
    """
    if not telefone:
        return False, "Telefone não informado"
    
    # Remove caracteres não numéricos
    telefone = re.sub(r'\D', '', telefone)
    
    # Verifica tamanho (10 ou 11 dígitos)
    if len(telefone) not in (10, 11):
        return False, "Telefone deve ter 10 ou 11 dígitos"
    
    # Verifica se começa com DDD válido (11-99, exceto números especiais)
    ddd = int(telefone[:2])
    if ddd < 11 or ddd > 99:
        return False, "DDD inválido"
    
    return True, ""


def validate_cep(cep: str) -> Tuple[bool, str]:
    """
    Valida CEP brasileiro.
    
    Args:
        cep: CEP a ser validado
        
    Returns:
        Tuple (valido, mensagem_erro)
    """
    if not cep:
        return False, "CEP não informado"
    
    # Remove caracteres não numéricos
    cep = re.sub(r'\D', '', cep)
    
    # Verifica tamanho
    if len(cep) != 8:
        return False, "CEP deve ter 8 dígitos"
    
    return True, ""


def validate_peso(peso: any, min_peso: float = 0.0, max_peso: float = 100000.0) -> Tuple[bool, str]:
    """
    Valida peso em kg.
    
    Args:
        peso: Peso a ser validado
        min_peso: Peso mínimo permitido
        max_peso: Peso máximo permitido
        
    Returns:
        Tuple (valido, mensagem_erro)
    """
    try:
        peso_float = float(peso)
    except (ValueError, TypeError):
        return False, "Peso deve ser um número"
    
    if peso_float < min_peso:
        return False, f"Peso deve ser maior que {min_peso} kg"
    
    if peso_float > max_peso:
        return False, f"Peso deve ser menor que {max_peso} kg"
    
    return True, ""


def validate_valor(valor: any, min_valor: float = 0.0) -> Tuple[bool, str]:
    """
    Valida valor monetário.
    
    Args:
        valor: Valor a ser validado
        min_valor: Valor mínimo permitido
        
    Returns:
        Tuple (valido, mensagem_erro)
    """
    try:
        valor_float = float(valor)
    except (ValueError, TypeError):
        return False, "Valor deve ser um número"
    
    if valor_float < min_valor:
        return False, f"Valor deve ser maior que R$ {min_valor:.2f}"
    
    return True, ""


def validate_data(data: str, formato: str = "%d/%m/%Y") -> Tuple[bool, str, Optional[datetime]]:
    """
    Valida e converte uma data.
    
    Args:
        data: String de data a ser validada
        formato: Formato esperado da data
        
    Returns:
        Tuple (valido, mensagem_erro, data_objeto)
    """
    if not data:
        return False, "Data não informada", None
    
    try:
        data_obj = datetime.strptime(data, formato)
        return True, "", data_obj
    except ValueError:
        return False, f"Data inválida (use formato {formato})", None


def validate_nome(nome: str, min_length: int = 2, max_length: int = 100) -> Tuple[bool, str]:
    """
    Valida nome de pessoa ou empresa.
    
    Args:
        nome: Nome a ser validado
        min_length: Comprimento mínimo
        max_length: Comprimento máximo
        
    Returns:
        Tuple (valido, mensagem_erro)
    """
    if not nome:
        return False, "Nome não informado"
    
    nome = nome.strip()
    
    if len(nome) < min_length:
        return False, f"Nome deve ter pelo menos {min_length} caracteres"
    
    if len(nome) > max_length:
        return False, f"Nome deve ter no máximo {max_length} caracteres"
    
    # Verifica se contém apenas caracteres válidos
    if not re.match(r'^[a-zA-ZÀ-ÿ\s\-\'\.]+$', nome):
        return False, "Nome contém caracteres inválidos"
    
    return True, ""


def validate_cpf(cpf: str) -> Tuple[bool, str]:
    """
    Valida CPF brasileiro.
    
    Args:
        cpf: CPF a ser validado (com ou sem formatação)
        
    Returns:
        Tuple (valido, mensagem_erro)
    """
    if not cpf:
        return False, "CPF não informado"
    
    # Remove caracteres não numéricos
    cpf = re.sub(r'\D', '', cpf)
    
    # Verifica tamanho
    if len(cpf) != 11:
        return False, "CPF deve ter 11 dígitos"
    
    # Verifica se todos são iguais
    if cpf == cpf[0] * 11:
        return False, "CPF inválido"
    
    # Cálculo dos dígitos verificadores
    def calcular_digito(cpf_num: str, pesos: list) -> int:
        total = 0
        for i in range(len(pesos)):
            total += int(cpf_num[i]) * pesos[i]
        resto = total % 11
        return 0 if resto < 2 else 11 - resto
    
    pesos1 = [10, 9, 8, 7, 6, 5, 4, 3, 2]
    pesos2 = [11, 10, 9, 8, 7, 6, 5, 4, 3, 2]
    
    digito1 = calcular_digito(cpf[:9], pesos1)
    digito2 = calcular_digito(cpf[:9] + str(digito1), pesos2)
    
    if int(cpf[9]) != digito1 or int(cpf[10]) != digito2:
        return False, "CPF inválido"
    
    return True, ""


def format_cnpj(cnpj: str) -> str:
    """Formata CNPJ no padrão XX.XXX.XXX/XXXX-XX."""
    cnpj = re.sub(r'\D', '', cnpj)
    if len(cnpj) != 14:
        return cnpj
    return f"{cnpj[:2]}.{cnpj[2:5]}.{cnpj[5:8]}/{cnpj[8:12]}-{cnpj[12:]}"


def format_cpf(cpf: str) -> str:
    """Formata CPF no padrão XXX.XXX.XXX-XX."""
    cpf = re.sub(r'\D', '', cpf)
    if len(cpf) != 11:
        return cpf
    return f"{cpf[:3]}.{cpf[3:6]}.{cpf[6:9]}-{cpf[9:]}"


def format_telefone(telefone: str) -> str:
    """Formata telefone no padrão (XX) XXXXX-XXXX ou (XX) XXXX-XXXX."""
    telefone = re.sub(r'\D', '', telefone)
    if len(telefone) == 11:
        return f"({telefone[:2]}) {telefone[2:7]}-{telefone[7:]}"
    elif len(telefone) == 10:
        return f"({telefone[:2]}) {telefone[2:6]}-{telefone[6:]}"
    return telefone


def format_cep(cep: str) -> str:
    """Formata CEP no padrão XXXXX-XXX."""
    cep = re.sub(r'\D', '', cep)
    if len(cep) != 8:
        return cep
    return f"{cep[:5]}-{cep[5:]}"


def format_placa(placa: str) -> str:
    """Formata placa no padrão ABC-1234 (antigo) ou ABC1D23 (Mercosul)."""
    placa = placa.upper().strip()
    placa = re.sub(r'[^A-Z0-9]', '', placa)
    
    if len(placa) == 7:
        # Formato Mercosul: ABC1D23 ou antigo sem traço: ABC1234
        return f"{placa[:3]}-{placa[3:]}"
    elif len(placa) == 8 and placa[3] == '-':
        # Já formatado com traço: ABC-1234
        return placa
    
    return placa
