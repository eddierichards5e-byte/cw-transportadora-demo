"""Sistema de logging do CW Transportadora.

Os logs são gravados em uma pasta do usuário para funcionar mesmo quando
o aplicativo estiver instalado em uma pasta protegida pelo Windows.
"""
import logging
import os
import sys
from datetime import datetime
from pathlib import Path


def _get_log_dir():
    """Retorna uma pasta de logs gravável pelo usuário atual."""
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "CW Transportadora" / "logs"

    # Fallback para ambientes sem LOCALAPPDATA (ex.: alguns testes).
    return Path.home() / "CW Transportadora" / "logs"


class Logger:
    """Logger customizado, seguro para instalações em Program Files."""

    def __init__(self, name="SistemaAtualizacoes", log_dir=None):
        self.name = name
        self.log_dir = Path(log_dir) if log_dir else _get_log_dir()
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.DEBUG)
        self.logger.propagate = False

        if not self.logger.handlers:
            file_handler = None
            try:
                self.log_dir.mkdir(parents=True, exist_ok=True)
                file_path = self.log_dir / f"{name}_{datetime.now().strftime('%Y%m%d')}.log"
                file_handler = logging.FileHandler(file_path, encoding="utf-8")
                file_handler.setLevel(logging.DEBUG)
            except (OSError, PermissionError):
                # O log nunca deve impedir a inicialização do aplicativo.
                file_handler = None

            stream_handler = logging.StreamHandler(sys.stdout)
            stream_handler.setLevel(logging.INFO)

            formatter = logging.Formatter(
                "%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d - %(message)s"
            )
            stream_handler.setFormatter(formatter)
            self.logger.addHandler(stream_handler)

            if file_handler is not None:
                file_handler.setFormatter(formatter)
                self.logger.addHandler(file_handler)

    def log(self, message, level="info"):
        levels = {
            "debug": self.logger.debug,
            "info": self.logger.info,
            "success": self.logger.info,
            "warning": self.logger.warning,
            "error": self.logger.error,
        }
        levels.get(level, self.logger.info)(message)

    def info(self, message):
        self.logger.info(message)

    def warning(self, message):
        self.logger.warning(message)

    def error(self, message):
        self.logger.error(message)

    def debug(self, message):
        self.logger.debug(message)


# Função get_logger para compatibilidade com main_pyside6.py
_loggers = {}

def get_logger(name="SistemaAtualizacoes"):
    """Retorna um logger configurado."""
    if name not in _loggers:
        _loggers[name] = Logger(name)
    return _loggers[name].logger
