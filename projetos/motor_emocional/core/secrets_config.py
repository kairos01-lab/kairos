"""Configuração externa de segredos do Kairós (K-19).

Regras:

- nenhum segredo é embutido no código ou nos testes;
- o caminho do arquivo é configurável por variável de ambiente;
- variáveis de ambiente têm precedência sobre arquivos;
- arquivos de segredo devem ser regulares, do próprio usuário e sem
  permissões de grupo/outros (`0600` ou mais restrito);
- symlinks são rejeitados para reduzir troca de alvo (TOCTOU);
- mensagens de erro nunca incluem o valor do segredo;
- ausência, ilegibilidade e formato inválido são estados identificáveis.

Não há chamada de rede neste módulo.
"""
from __future__ import annotations

import os
import re
import stat
from typing import Iterable, List, Optional, Tuple

GROQ_API_KEY_ENV = "GROQ_API_KEY"
GROQ_KEY_FILE_ENV = "KAIROS_GROQ_KEY_FILE"
API_SECRET_FILE_ENV = "KAIROS_API_SECRET_FILE"

DEFAULT_GROQ_KEY_FILE = "~/.groq_key"
DEFAULT_API_SECRET_FILE = "~/.secret/segredos.env"

MAX_SECRET_BYTES = 16 * 1024
MAX_KEY_CHARS = 4096
MIN_KEY_CHARS = 8

_API_KEY_NAME = re.compile(r"^(GOOGLE|GEMINI)_API_KEY(?:_[1-9][0-9]*)?$")
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_CONTROL_OR_SPACE = re.compile(r"[\s\x00-\x1f\x7f]")


class SecretConfigError(Exception):
    """Falha de configuração de segredo; nunca contém o valor do segredo."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


def resolve_secret_path(
    explicit_path: Optional[str] = None,
    *,
    env_var: str = "",
    default_path: str = "",
) -> str:
    """Resolve caminho explícito, variável de ambiente e default portável."""
    candidate = explicit_path
    if candidate is None or candidate == "":
        candidate = os.environ.get(env_var) if env_var else None
    if candidate is None or candidate == "":
        candidate = default_path
    if not isinstance(candidate, str) or not candidate.strip():
        raise SecretConfigError("secret_path_invalid", "caminho de segredo inválido")
    return os.path.abspath(os.path.expanduser(candidate))


def _check_private_file(path: str) -> None:
    """Verifica metadados de arquivo regular privado, sem ler o conteúdo."""
    try:
        info = os.lstat(path)
    except FileNotFoundError as error:
        raise SecretConfigError(
            "secret_file_missing", "arquivo de segredo não encontrado"
        ) from error
    except OSError as error:
        raise SecretConfigError(
            "secret_file_unreadable", "arquivo de segredo inacessível"
        ) from error

    if stat.S_ISLNK(info.st_mode):
        raise SecretConfigError(
            "secret_file_symlink", "symlink de segredo não é aceito"
        )
    if not stat.S_ISREG(info.st_mode):
        raise SecretConfigError(
            "secret_file_type", "segredo deve ser arquivo regular"
        )
    if info.st_uid != os.geteuid():
        raise SecretConfigError(
            "secret_file_owner", "arquivo de segredo deve pertencer ao usuário atual"
        )
    if info.st_mode & 0o077:
        raise SecretConfigError(
            "secret_file_permissions",
            "arquivo de segredo deve ter permissões 0600 ou mais restritas",
        )
    if info.st_size > MAX_SECRET_BYTES:
        raise SecretConfigError(
            "secret_file_too_large", "arquivo de segredo excede o limite"
        )


def _read_private_text(path: str) -> str:
    """Abre sem seguir symlink e revalida o file descriptor."""
    _check_private_file(path)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as error:
        raise SecretConfigError(
            "secret_file_unreadable", "arquivo de segredo inacessível"
        ) from error

    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise SecretConfigError(
                "secret_file_type", "segredo deve ser arquivo regular"
            )
        if info.st_uid != os.geteuid():
            raise SecretConfigError(
                "secret_file_owner",
                "arquivo de segredo deve pertencer ao usuário atual",
            )
        if info.st_mode & 0o077:
            raise SecretConfigError(
                "secret_file_permissions",
                "arquivo de segredo deve ter permissões 0600 ou mais restritas",
            )
        if info.st_size > MAX_SECRET_BYTES:
            raise SecretConfigError(
                "secret_file_too_large", "arquivo de segredo excede o limite"
            )
        data = os.read(fd, MAX_SECRET_BYTES + 1)
    finally:
        os.close(fd)

    if len(data) > MAX_SECRET_BYTES:
        raise SecretConfigError(
            "secret_file_too_large", "arquivo de segredo excede o limite"
        )
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise SecretConfigError(
            "secret_file_encoding", "arquivo de segredo não é UTF-8 válido"
        ) from error


def validate_key(value: str, *, field: str = "api_key") -> str:
    """Valida formato básico sem registrar o valor."""
    if not isinstance(value, str):
        raise SecretConfigError("secret_value_invalid", f"{field} não é textual")
    key = value.strip()
    if not key:
        raise SecretConfigError("secret_value_empty", f"{field} vazio")
    if len(key) < MIN_KEY_CHARS:
        raise SecretConfigError("secret_value_short", f"{field} curto demais")
    if len(key) > MAX_KEY_CHARS:
        raise SecretConfigError("secret_value_long", f"{field} longo demais")
    if _CONTROL_OR_SPACE.search(key):
        raise SecretConfigError(
            "secret_value_whitespace", f"{field} contém espaço ou caractere de controle"
        )
    return key


def _single_value(text: str, *, field: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        raise SecretConfigError("secret_file_empty", "arquivo de segredo vazio")
    if len(lines) != 1:
        raise SecretConfigError(
            "secret_file_multiple_values",
            "arquivo de chave única deve conter exatamente uma linha não vazia",
        )
    candidate = lines[0]
    if candidate.startswith("#"):
        raise SecretConfigError("secret_file_empty", "arquivo de segredo vazio")
    if "=" in candidate:
        name, value = candidate.split("=", 1)
        if name.strip() != field:
            raise SecretConfigError(
                "secret_file_name", "nome de variável inesperado no arquivo"
            )
        candidate = value.strip().strip('"').strip("'")
    return validate_key(candidate, field=field)


def load_groq_api_key(
    *,
    explicit_key: Optional[str] = None,
    read_external: bool = True,
) -> Tuple[Optional[str], str]:
    """Carrega a chave Groq de argumento, ambiente ou arquivo privado.

    Retorna `(chave, origem)`, onde origem é `explicit`, `env`, `file`,
    `disabled` ou `none`. Levanta `SecretConfigError` para configuração
    presente porém inválida/insegura.
    """
    if explicit_key is not None:
        return validate_key(explicit_key, field="GROQ_API_KEY"), "explicit"
    if not read_external:
        return None, "disabled"

    env_value = os.environ.get(GROQ_API_KEY_ENV)
    if env_value is not None and env_value.strip():
        return validate_key(env_value, field=GROQ_API_KEY_ENV), "env"

    path = resolve_secret_path(
        None,
        env_var=GROQ_KEY_FILE_ENV,
        default_path=DEFAULT_GROQ_KEY_FILE,
    )
    if not os.path.lexists(path):
        return None, "none"
    return _single_value(_read_private_text(path), field="GROQ_API_KEY"), "file"


def _env_api_keys(expected_projects: int) -> List[str]:
    keys: List[str] = []
    prefixes = ("GOOGLE_API_KEY", "GEMINI_API_KEY")
    for prefix in prefixes:
        value = os.environ.get(prefix)
        if value and value.strip():
            keys.append(validate_key(value, field=prefix))
    for index in range(1, expected_projects + 1):
        for prefix in prefixes:
            value = os.environ.get(f"{prefix}_{index}")
            if value and value.strip():
                keys.append(validate_key(value, field=f"{prefix}_{index}"))
                break
    return keys


def load_api_keys_from_file(path: str) -> List[str]:
    """Lê apenas variáveis `GOOGLE_API_KEY`/`GEMINI_API_KEY` reconhecidas.

    Qualquer outra variável do arquivo é ignorada. Isso evita que um arquivo
    de segredos genérico envie senhas ou tokens alheios como Bearer.
    """
    text = _read_private_text(path)
    keys: List[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            continue
        name, value = stripped.split("=", 1)
        name = name.strip()
        if not _IDENTIFIER.match(name) or not _API_KEY_NAME.match(name):
            continue
        candidate = value.strip().strip('"').strip("'")
        if candidate:
            keys.append(validate_key(candidate, field=name))
    if not keys:
        raise SecretConfigError(
            "secret_file_no_supported_keys",
            "arquivo de segredo não contém GOOGLE_API_KEY/GEMINI_API_KEY",
        )
    return keys


def load_api_router_keys(
    *,
    explicit_keys: Optional[Iterable[str]] = None,
    secret_file: Optional[str] = None,
    expected_projects: int = 4,
) -> Tuple[List[str], str]:
    """Carrega chaves do router por argumento, ambiente ou arquivo privado."""
    if explicit_keys:
        return (
            [validate_key(key, field="api_key") for key in explicit_keys],
            "explicit",
        )

    env_keys = _env_api_keys(expected_projects)
    if env_keys:
        return env_keys, "env"

    path = resolve_secret_path(
        secret_file,
        env_var=API_SECRET_FILE_ENV,
        default_path=DEFAULT_API_SECRET_FILE,
    )
    if not os.path.lexists(path):
        return [], "none"
    return load_api_keys_from_file(path), "file"
