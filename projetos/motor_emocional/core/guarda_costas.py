"""Ponte Python <-> Rust para o Guarda-Costas (Arquitetura de Segurança).

O binário Rust compilado em `guarda_costas/target/release/guarda_costas` é
chamado via subprocess, recebendo/devolvendo JSON. Isso garante que a camada
de segurança (Hard Block, Kernel Constitucional, Break Glass) rode isolada
do processo Python - incorruptível por picos emocionais do Córtex (LLM) ou
bugs no lado Python, com segurança de memória a nível de compilação.

OS099 - contrato fail-closed:
- `hard_block()` nunca devolve `allowed=True` quando o Rust está ausente,
  falhou, demorou, devolveu JSON inválido ou uma decisão malformada.
- Falhas são estados explícitos (`guard_status`) e a decisão resultante é
  sempre `allowed=False`.

OS100 - Kernel Constitucional:
- `kernel_check()` usa contrato estrito e estados `KERNEL_ALLOW`,
  `KERNEL_DENY`, `KERNEL_REVIEW`, `KERNEL_UNAVAILABLE`,
  `KERNEL_INVALID_INPUT` e `KERNEL_ERROR`.
- `authorize_action()` é o ponto central: Hard Block e Kernel precisam
  autorizar. Falha, indisponibilidade ou incerteza nunca viram permissão.

OS101 - Break Glass:
- `break_glass()` usa estados `BREAK_GLASS_*` e somente aceita autorização
  quando o Rust verifica integridade dos arquivos, assinatura HMAC-SHA256,
  timestamp, vínculo de evento e nonce.
- Falha, indisponibilidade, resposta malformada ou exceção resultam em
  `autorizado=False`.
- O Break Glass não libera Hard Block nem Kernel.

OS114 - identidade do binário Rust:
- O caminho do executável não é prova de identidade. Antes de executar, o
  wrapper exige uma entrada SHA-256 explícita no manifesto versionado
  `guarda_costas/binary_sha256.txt`.
- Symlink em qualquer componente do caminho, arquivo não regular, dono
  inesperado, setuid/setgid, escrita por outros ou ausência de execução
  bloqueiam a operação.
- Os bytes lidos são hasheados e copiados para um `memfd_create` selado
  (`F_SEAL_WRITE|F_SEAL_GROW|F_SEAL_SHRINK|F_SEAL_SEAL`). A execução usa
  `/proc/self/fd/<fd>`, portanto os bytes executados são exatamente os bytes
  verificados (mitigação TOCTOU entre hash e execução).
- Manifesto ausente/malformado, hash divergente, arquivo inválido e falha de
  execução nunca autorizam. O estado específico é exposto em
  `binary_integrity.status`.
"""
import errno
import hashlib
import hmac
import json
import math
import os
import stat
import subprocess
import time

try:  # Linux; a ausência de fcntl/seals falha fechado na execução.
    import fcntl
except ImportError:  # pragma: no cover - ambiente sem fcntl
    fcntl = None

from .authorization_contract import (
    AUTHORIZATION_DENIED,
    AUTHORIZATION_INFRASTRUCTURE_FAILURE,
    AUTHORIZATION_INPUT_INVALID,
    EXECUTION_NOT_EXECUTED,
    build_authorization_record,
    build_identity_context,
    derive_authorization_status,
    new_request_id,
    validate_identifier,
)
from .policy_controls import build_policy_controls, validate_policy_result
from .policy_provenance import (
    PROVENANCE_ABSENT,
    PROVENANCE_ERROR,
    PROVENANCE_MALFORMED,
    PROVENANCE_VALID,
    verify_policy_result,
)

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_BINARY_RELEASE = os.path.join(_BASE_DIR, "guarda_costas", "target", "release", "guarda_costas")
_BINARY_DEBUG = os.path.join(_BASE_DIR, "guarda_costas", "target", "debug", "guarda_costas")
_BINARY_MANIFEST = os.path.join(_BASE_DIR, "guarda_costas", "binary_sha256.txt")

_BINARY_VERIFIED = "BINARY_VERIFIED"
_BINARY_MISSING = "BINARY_MISSING"
_BINARY_INVALID = "BINARY_INVALID"
_BINARY_HASH_MISMATCH = "BINARY_HASH_MISMATCH"
_BINARY_IDENTITY_UNAVAILABLE = "BINARY_IDENTITY_UNAVAILABLE"
_BINARY_EXECUTION_ERROR = "BINARY_EXECUTION_ERROR"
_BINARY_INTEGRITY_STATUSES = frozenset({
    _BINARY_VERIFIED,
    _BINARY_MISSING,
    _BINARY_INVALID,
    _BINARY_HASH_MISMATCH,
    _BINARY_IDENTITY_UNAVAILABLE,
    _BINARY_EXECUTION_ERROR,
})
_BINARY_INTEGRITY_FAILURES = _BINARY_INTEGRITY_STATUSES - {_BINARY_VERIFIED}
_MANIFEST_LABELS = ("release", "debug")
_MANIFEST_MAX_BYTES = 4096
_PROC_SELF_FD = "/proc/self/fd"

_TIMEOUT_S = 5
_MAX_USER_ID_CHARS = 256
_MAX_KERNEL_FIELD_CHARS = 256
_VALID_ACTIONS = frozenset({"create", "read", "update", "delete"})
_PROTECTED_ACTIONS = frozenset({"create", "update", "delete"})
_KERNEL_ALLOW = "KERNEL_ALLOW"
_KERNEL_DENY = "KERNEL_DENY"
_KERNEL_REVIEW = "KERNEL_REVIEW"
_KERNEL_UNAVAILABLE = "KERNEL_UNAVAILABLE"
_KERNEL_INVALID_INPUT = "KERNEL_INVALID_INPUT"
_KERNEL_ERROR = "KERNEL_ERROR"
_KERNEL_STATUSES = frozenset({
    _KERNEL_ALLOW,
    _KERNEL_DENY,
    _KERNEL_REVIEW,
    _KERNEL_INVALID_INPUT,
})

_BREAK_GLASS_AUTHORIZED = "BREAK_GLASS_AUTHORIZED"
_BREAK_GLASS_DENIED = "BREAK_GLASS_DENIED"
_BREAK_GLASS_INVALID_INPUT = "BREAK_GLASS_INVALID_INPUT"
_BREAK_GLASS_INVALID_EVIDENCE = "BREAK_GLASS_INVALID_EVIDENCE"
_BREAK_GLASS_INTEGRITY_FAILURE = "BREAK_GLASS_INTEGRITY_FAILURE"
_BREAK_GLASS_AUTHENTICATION_FAILURE = "BREAK_GLASS_AUTHENTICATION_FAILURE"
_BREAK_GLASS_AUTHENTICATION_UNAVAILABLE = "BREAK_GLASS_AUTHENTICATION_UNAVAILABLE"
_BREAK_GLASS_REPLAY_DETECTED = "BREAK_GLASS_REPLAY_DETECTED"
_BREAK_GLASS_UNAVAILABLE = "BREAK_GLASS_UNAVAILABLE"
_BREAK_GLASS_INTERNAL_ERROR = "BREAK_GLASS_INTERNAL_ERROR"
_BREAK_GLASS_STATUSES = frozenset({
    _BREAK_GLASS_AUTHORIZED,
    _BREAK_GLASS_DENIED,
    _BREAK_GLASS_INVALID_INPUT,
    _BREAK_GLASS_INVALID_EVIDENCE,
    _BREAK_GLASS_INTEGRITY_FAILURE,
    _BREAK_GLASS_AUTHENTICATION_FAILURE,
    _BREAK_GLASS_AUTHENTICATION_UNAVAILABLE,
    _BREAK_GLASS_REPLAY_DETECTED,
    _BREAK_GLASS_UNAVAILABLE,
    _BREAK_GLASS_INTERNAL_ERROR,
})
_BREAK_GLASS_REQUIRED_FIELDS = (
    "event_id",
    "request_id",
    "emitter_id",
    "subject_id",
    "timestamp_unix",
    "nonce",
    "key_id",
    "camera_file",
    "camera_media_type",
    "camera_sha256",
    "audio_file",
    "audio_media_type",
    "audio_sha256",
    "justificativa",
    "signature_hmac_sha256",
)


def _binary_integrity_record(
    status: str,
    *,
    path=None,
    label=None,
    expected_sha256=None,
    actual_sha256=None,
    detail=None,
    verified_before_execution: bool = False,
) -> dict:
    """Registro explícito da identidade do executável, sem inferência otimista."""
    record = {"status": status}
    if path is not None:
        record["path"] = path
    if label is not None:
        record["label"] = label
    if expected_sha256 is not None:
        record["expected_sha256"] = expected_sha256
    if actual_sha256 is not None:
        record["sha256"] = actual_sha256
    if detail is not None:
        record["detail"] = detail
    if verified_before_execution:
        record["verified_before_execution"] = True
    return record


class GuardError(RuntimeError):
    """Falha do Guarda-Costas que nunca pode virar autorização."""

    guard_status = "GUARD_UNAVAILABLE"
    blocked_by = "guard_unavailable"
    binary_integrity = None


class GuardUnavailable(GuardError):
    """Binário ausente, sem permissão de execução ou inexecutável."""

    guard_status = "GUARD_UNAVAILABLE"
    blocked_by = "guard_unavailable"


class GuardCommunicationError(GuardError):
    """Timeout, processo morto ou código de saída inesperado."""

    guard_status = "GUARD_COMMUNICATION_ERROR"
    blocked_by = "guard_communication_error"


class GuardInvalidInput(GuardError):
    """Entrada rejeitada antes ou durante a avaliação."""

    guard_status = "GUARD_INVALID_INPUT"
    blocked_by = "guard_invalid_input"


class GuardProtocolError(GuardError):
    """Resposta vazia, ilegível, sem campos ou contraditória."""

    guard_status = "GUARD_PROTOCOL_ERROR"
    blocked_by = "guard_protocol_error"


class GuardInternalError(GuardError):
    """Erro interno declarado pelo executável Rust."""

    guard_status = "GUARD_INTERNAL_ERROR"
    blocked_by = "guard_internal_error"


class GuardIntegrityError(GuardUnavailable):
    """Identidade do executável não verificada; herda o fail-closed da OS099.

    `guard_status` continua `GUARD_UNAVAILABLE` para preservar os contratos
    existentes. A causa específica fica em `binary_integrity.status`.
    """

    def __init__(self, status: str, detail: str, *, path=None,
                 expected_sha256=None, actual_sha256=None):
        if status not in _BINARY_INTEGRITY_FAILURES:
            raise ValueError(f"status de integridade inválido: {status!r}")
        super().__init__(detail)
        self.binary_integrity = _binary_integrity_record(
            status,
            path=path,
            expected_sha256=expected_sha256,
            actual_sha256=actual_sha256,
            detail=detail,
        )


class _VerifiedBinary(str):
    """Caminho verificado com o memfd selado dos bytes efetivamente hasheados.

    Continua sendo `str` para preservar chamadas de diagnóstico que usam
    `_binary_path()` como caminho. `_run_rust()` usa `.fd` e executa
    `/proc/self/fd/<fd>`; quem chama o caminho diretamente **não** recebe a
    garantia de TOCTOU e deve ser tratado como ferramenta/diagnóstico.
    """

    def __new__(cls, path: str, fd: int, sha256_hex: str, label: str):
        obj = str.__new__(cls, path)
        obj.fd = fd
        obj.sha256 = sha256_hex
        obj.label = label
        obj.integrity = _binary_integrity_record(
            _BINARY_VERIFIED,
            path=path,
            label=label,
            expected_sha256=sha256_hex,
            actual_sha256=sha256_hex,
        )
        obj._closed = False
        return obj

    def close(self) -> None:
        fd = getattr(self, "fd", None)
        if fd is not None and not getattr(self, "_closed", False):
            try:
                os.close(fd)
            except OSError:
                pass
            self._closed = True

    def __del__(self):  # pragma: no cover - fechamento defensivo
        try:
            self.close()
        except Exception:
            pass


def _load_binary_manifest(manifest_path=None) -> dict:
    """Carrega o manifesto explícito `label sha256`; qualquer anomalia bloqueia."""
    path = _BINARY_MANIFEST if manifest_path is None else manifest_path
    try:
        with open(path, "rb") as handle:
            raw = handle.read(_MANIFEST_MAX_BYTES + 1)
    except FileNotFoundError as e:
        raise GuardIntegrityError(
            _BINARY_IDENTITY_UNAVAILABLE,
            f"Manifesto SHA-256 ausente: {path}",
            path=path,
        ) from e
    except OSError as e:
        raise GuardIntegrityError(
            _BINARY_IDENTITY_UNAVAILABLE,
            f"Manifesto SHA-256 ilegível: {path}: {e}",
            path=path,
        ) from e

    if len(raw) > _MANIFEST_MAX_BYTES:
        raise GuardIntegrityError(
            _BINARY_IDENTITY_UNAVAILABLE,
            f"Manifesto SHA-256 excede {_MANIFEST_MAX_BYTES} bytes: {path}",
            path=path,
        )
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as e:
        raise GuardIntegrityError(
            _BINARY_IDENTITY_UNAVAILABLE,
            f"Manifesto SHA-256 não é UTF-8 válido: {path}",
            path=path,
        ) from e

    entries = {}
    for line_number, raw_line in enumerate(text.splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) != 2:
            raise GuardIntegrityError(
                _BINARY_IDENTITY_UNAVAILABLE,
                f"Manifesto SHA-256 malformado na linha {line_number}: {line!r}",
                path=path,
            )
        label, digest = parts
        if label not in _MANIFEST_LABELS:
            raise GuardIntegrityError(
                _BINARY_IDENTITY_UNAVAILABLE,
                f"Rótulo desconhecido no manifesto, linha {line_number}: {label!r}",
                path=path,
            )
        if label in entries:
            raise GuardIntegrityError(
                _BINARY_IDENTITY_UNAVAILABLE,
                f"Entrada duplicada no manifesto: {label!r}",
                path=path,
            )
        if not _is_sha256_hex(digest):
            raise GuardIntegrityError(
                _BINARY_IDENTITY_UNAVAILABLE,
                f"Hash malformado no manifesto, linha {line_number}: {digest!r}",
                path=path,
            )
        entries[label] = digest.lower()

    if not entries:
        raise GuardIntegrityError(
            _BINARY_IDENTITY_UNAVAILABLE,
            f"Manifesto SHA-256 sem entradas: {path}",
            path=path,
        )
    return entries


def _lstat_no_symlink(path: str):
    """Rejeita symlink em qualquer componente; retorna caminho absoluto e stat."""
    absolute = os.path.abspath(path)
    current = os.sep
    final_stat = None
    for part in absolute.split(os.sep):
        if not part:
            continue
        current = os.path.join(current, part)
        try:
            final_stat = os.lstat(current)
        except OSError as e:
            if e.errno in (errno.ENOENT, errno.ENOTDIR):
                raise GuardIntegrityError(
                    _BINARY_MISSING,
                    f"Componente ausente no caminho do executável: {current}",
                    path=absolute,
                ) from e
            raise GuardIntegrityError(
                _BINARY_INVALID,
                f"Falha ao inspecionar componente do caminho {current}: {e}",
                path=absolute,
            ) from e
        if stat.S_ISLNK(final_stat.st_mode):
            raise GuardIntegrityError(
                _BINARY_INVALID,
                f"Symlink recusado no caminho do executável: {current}",
                path=absolute,
            )
    return absolute, final_stat


def _new_verified_memfd() -> int:
    """Cria o memfd que receberá cópia selada dos bytes verificados."""
    if fcntl is None or not hasattr(os, "memfd_create") \
            or not hasattr(os, "MFD_ALLOW_SEALING"):
        raise GuardIntegrityError(
            _BINARY_EXECUTION_ERROR,
            "memfd_create/MFD_ALLOW_SEALING indisponíveis; execução verificada "
            "não pode ser garantida",
        )
    if not os.path.isdir(_PROC_SELF_FD):
        raise GuardIntegrityError(
            _BINARY_EXECUTION_ERROR,
            f"{_PROC_SELF_FD} indisponível; execução verificada não pode ser garantida",
        )
    try:
        return os.memfd_create("guarda_costas_verified", os.MFD_ALLOW_SEALING)
    except OSError as e:
        raise GuardIntegrityError(
            _BINARY_EXECUTION_ERROR,
            f"Falha ao criar memfd para o executável verificado: {e}",
        ) from e


def _seal_memfd(fd: int) -> None:
    required = ("F_ADD_SEALS", "F_SEAL_WRITE", "F_SEAL_GROW",
                "F_SEAL_SHRINK", "F_SEAL_SEAL")
    if fcntl is None or any(not hasattr(fcntl, name) for name in required):
        raise GuardIntegrityError(
            _BINARY_EXECUTION_ERROR,
            "Seals de memfd indisponíveis; execução verificada não pode ser garantida",
        )
    seals = (
        fcntl.F_SEAL_WRITE
        | fcntl.F_SEAL_GROW
        | fcntl.F_SEAL_SHRINK
        | fcntl.F_SEAL_SEAL
    )
    try:
        fcntl.fcntl(fd, fcntl.F_ADD_SEALS, seals)
    except OSError as e:
        raise GuardIntegrityError(
            _BINARY_EXECUTION_ERROR,
            f"Falha ao selar o memfd do executável verificado: {e}",
        ) from e


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        try:
            written = os.write(fd, view)
        except OSError as e:
            raise GuardIntegrityError(
                _BINARY_EXECUTION_ERROR,
                f"Falha ao copiar o executável verificado para o memfd: {e}",
            ) from e
        if written <= 0:
            raise GuardIntegrityError(
                _BINARY_EXECUTION_ERROR,
                "Escrita vazia ao copiar o executável verificado para o memfd",
            )
        view = view[written:]


def _stage_verified_binary(path: str, expected_sha256: str, label: str) -> _VerifiedBinary:
    """Valida o arquivo, hash dos bytes lidos e cópia selada para memfd."""
    absolute, inspected = _lstat_no_symlink(path)
    if not stat.S_ISREG(inspected.st_mode):
        raise GuardIntegrityError(
            _BINARY_INVALID,
            f"Executável não é arquivo regular: {absolute}",
            path=absolute,
            expected_sha256=expected_sha256,
        )
    geteuid = getattr(os, "geteuid", os.getuid)
    if inspected.st_uid not in (geteuid(), 0):
        raise GuardIntegrityError(
            _BINARY_INVALID,
            f"Executável com dono inesperado (uid={inspected.st_uid}): {absolute}",
            path=absolute,
            expected_sha256=expected_sha256,
        )
    if inspected.st_mode & (stat.S_ISUID | stat.S_ISGID):
        raise GuardIntegrityError(
            _BINARY_INVALID,
            f"Executável com setuid/setgid recusado: {absolute}",
            path=absolute,
            expected_sha256=expected_sha256,
        )
    if inspected.st_mode & stat.S_IWOTH:
        raise GuardIntegrityError(
            _BINARY_INVALID,
            f"Executável com escrita por outros recusado (modo {oct(inspected.st_mode & 0o777)}): {absolute}",
            path=absolute,
            expected_sha256=expected_sha256,
        )
    if not (inspected.st_mode & 0o111) or not os.access(absolute, os.X_OK):
        raise GuardIntegrityError(
            _BINARY_INVALID,
            f"Executável sem permissão de execução (modo {oct(inspected.st_mode & 0o777)}): {absolute}",
            path=absolute,
            expected_sha256=expected_sha256,
        )

    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        source_fd = os.open(absolute, flags)
    except FileNotFoundError as e:
        raise GuardIntegrityError(
            _BINARY_MISSING,
            f"Executável desapareceu antes da leitura: {absolute}",
            path=absolute,
            expected_sha256=expected_sha256,
        ) from e
    except OSError as e:
        raise GuardIntegrityError(
            _BINARY_INVALID,
            f"Falha ao abrir o executável para leitura: {absolute}: {e}",
            path=absolute,
            expected_sha256=expected_sha256,
        ) from e

    memfd = None
    try:
        opened = os.fstat(source_fd)
        if (opened.st_dev, opened.st_ino) != (inspected.st_dev, inspected.st_ino):
            raise GuardIntegrityError(
                _BINARY_INVALID,
                f"Executável substituído entre inspeção e abertura: {absolute}",
                path=absolute,
                expected_sha256=expected_sha256,
            )
        if not stat.S_ISREG(opened.st_mode):
            raise GuardIntegrityError(
                _BINARY_INVALID,
                f"Executável deixou de ser arquivo regular: {absolute}",
                path=absolute,
                expected_sha256=expected_sha256,
            )

        memfd = _new_verified_memfd()
        digest = hashlib.sha256()
        total = 0
        while True:
            try:
                chunk = os.read(source_fd, 1024 * 1024)
            except OSError as e:
                raise GuardIntegrityError(
                    _BINARY_INVALID,
                    f"Falha de leitura do executável: {absolute}: {e}",
                    path=absolute,
                    expected_sha256=expected_sha256,
                ) from e
            if not chunk:
                break
            total += len(chunk)
            digest.update(chunk)
            _write_all(memfd, chunk)

        if total == 0:
            raise GuardIntegrityError(
                _BINARY_INVALID,
                f"Executável vazio: {absolute}",
                path=absolute,
                expected_sha256=expected_sha256,
            )

        actual = digest.hexdigest()
        if not hmac.compare_digest(actual, expected_sha256):
            raise GuardIntegrityError(
                _BINARY_HASH_MISMATCH,
                f"Hash SHA-256 divergente para {absolute}: "
                f"esperado {expected_sha256}, obtido {actual}",
                path=absolute,
                expected_sha256=expected_sha256,
                actual_sha256=actual,
            )

        try:
            os.fchmod(memfd, 0o500)
            os.lseek(memfd, 0, os.SEEK_SET)
        except OSError as e:
            raise GuardIntegrityError(
                _BINARY_EXECUTION_ERROR,
                f"Falha ao preparar o memfd do executável verificado: {e}",
                path=absolute,
                expected_sha256=expected_sha256,
                actual_sha256=actual,
            ) from e
        _seal_memfd(memfd)

        verified = _VerifiedBinary(absolute, memfd, actual, label)
        memfd = None  # propriedade transferida para _VerifiedBinary
        return verified
    finally:
        try:
            os.close(source_fd)
        except OSError:
            pass
        if memfd is not None:
            try:
                os.close(memfd)
            except OSError:
                pass


def _binary_path() -> str:
    """Resolve e verifica o binário; retorna `_VerifiedBinary` (str com memfd).

    O release é preferido; o debug só é usado quando o release não existe.
    Se o release existir mas for inválido, symlink, hash divergente ou não
    estiver no manifesto, a operação falha fechado — não há fallback para o
    debug, pois fallback silencioso legitimaria uma substituição.
    """
    for candidate, label in ((_BINARY_RELEASE, "release"), (_BINARY_DEBUG, "debug")):
        try:
            os.lstat(candidate)
        except OSError as e:
            if e.errno in (errno.ENOENT, errno.ENOTDIR):
                continue
            raise GuardIntegrityError(
                _BINARY_INVALID,
                f"Falha ao inspecionar o binário {candidate}: {e}",
                path=candidate,
            ) from e

        expected = _load_binary_manifest().get(label)
        if expected is None:
            raise GuardIntegrityError(
                _BINARY_IDENTITY_UNAVAILABLE,
                f"Manifesto SHA-256 sem entrada '{label}' para {candidate}",
                path=candidate,
            )
        return _stage_verified_binary(candidate, expected, label)

    raise GuardIntegrityError(
        _BINARY_MISSING,
        "Binário guarda_costas não encontrado. Compile com: "
        "cd guarda_costas && cargo build --release",
        path=_BINARY_RELEASE,
    )


def _is_finite_number(value) -> bool:
    """Aceita int/float finitos; rejeita bool, strings, NaN e infinito."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return math.isfinite(float(value))


def _parse_error_payload(stdout: str):
    """Extrai error_kind/error de uma resposta de erro do Rust, se possível."""
    try:
        payload = json.loads(stdout)
    except (json.JSONDecodeError, TypeError):
        return None, ""
    if not isinstance(payload, dict) or payload.get("status") != "error":
        return None, ""
    kind = payload.get("error_kind")
    message = payload.get("error")
    return (kind if isinstance(kind, str) else None), (message if isinstance(message, str) else "")


def _validate_hard_block_response(payload: dict) -> None:
    """Rejeita decisões malformadas, com tipos errados ou contraditórias."""
    allowed = payload.get("allowed")
    if type(allowed) is not bool:
        raise GuardProtocolError(
            f"Resposta do Hard Block sem 'allowed' booleano (recebido: {type(allowed).__name__})"
        )

    blocked_by = payload.get("blocked_by")
    if blocked_by is not None and not isinstance(blocked_by, str):
        raise GuardProtocolError("Resposta com 'blocked_by' de tipo inválido")
    if allowed and blocked_by not in (None, ""):
        raise GuardProtocolError(
            "Resposta contraditória: allowed=true com blocked_by preenchido"
        )
    if not allowed and blocked_by in (None, ""):
        raise GuardProtocolError(
            "Resposta contraditória: allowed=false sem blocked_by"
        )

    for field in ("effective_threshold", "stress_level"):
        value = payload.get(field)
        if not _is_finite_number(value):
            raise GuardProtocolError(f"Resposta com '{field}' não numérico ou não finito")
        if not 0.0 <= float(value) <= 100.0:
            raise GuardProtocolError(f"Resposta com '{field}' fora da faixa 0..100")

    if not isinstance(payload.get("reasoning"), str):
        raise GuardProtocolError("Resposta do Hard Block sem 'reasoning' textual")


def _validate_kernel_response(payload: dict) -> None:
    """Rejeita veredictos do Kernel malformados ou contraditórios."""
    kernel_status = payload.get("kernel_status")
    if kernel_status not in _KERNEL_STATUSES:
        raise GuardProtocolError(
            f"Resposta do Kernel com kernel_status inválido: {kernel_status!r}"
        )

    allowed = payload.get("allowed")
    kernel_panic = payload.get("kernel_panic")
    requires_review = payload.get("requires_review")
    ring = payload.get("ring")
    from_majority_vote = payload.get("from_majority_vote")

    if type(allowed) is not bool:
        raise GuardProtocolError("Resposta do Kernel sem 'allowed' booleano")
    if type(kernel_panic) is not bool:
        raise GuardProtocolError("Resposta do Kernel sem 'kernel_panic' booleano")
    if type(requires_review) is not bool:
        raise GuardProtocolError("Resposta do Kernel sem 'requires_review' booleano")
    if type(ring) is not int or ring not in (0, 3):
        raise GuardProtocolError("Resposta do Kernel com 'ring' inválido")
    if type(from_majority_vote) is not bool:
        raise GuardProtocolError(
            "Resposta do Kernel sem 'from_majority_vote' booleano"
        )

    action = payload.get("action")
    if not isinstance(action, str) or action not in _VALID_ACTIONS:
        raise GuardProtocolError("Resposta do Kernel com 'action' inválida")

    for field in (
        "operation_class",
        "target_category",
        "intent_category",
        "matched_rule",
        "reasoning",
    ):
        if not isinstance(payload.get(field), str) or not payload.get(field):
            raise GuardProtocolError(
                f"Resposta do Kernel sem '{field}' textual não vazio"
            )

    if kernel_status == _KERNEL_ALLOW:
        if allowed is not True or kernel_panic is not False or requires_review is not False:
            raise GuardProtocolError("Resposta contraditória: KERNEL_ALLOW não autoriza")
        if ring != 3:
            raise GuardProtocolError("Resposta contraditória: KERNEL_ALLOW exige ring 3")
    elif kernel_status == _KERNEL_DENY:
        if allowed is not False or kernel_panic is not True or requires_review is not False:
            raise GuardProtocolError("Resposta contraditória: KERNEL_DENY malformado")
        if ring != 0:
            raise GuardProtocolError("Resposta contraditória: KERNEL_DENY exige ring 0")
    elif kernel_status == _KERNEL_REVIEW:
        if allowed is not False or kernel_panic is not False or requires_review is not True:
            raise GuardProtocolError("Resposta contraditória: KERNEL_REVIEW malformado")
        if ring != 0:
            raise GuardProtocolError("Resposta contraditória: KERNEL_REVIEW exige ring 0")
    elif kernel_status == _KERNEL_INVALID_INPUT:
        if allowed is not False or kernel_panic is not False or requires_review is not True:
            raise GuardProtocolError(
                "Resposta contraditória: KERNEL_INVALID_INPUT malformado"
            )
        if ring != 0:
            raise GuardProtocolError(
                "Resposta contraditória: KERNEL_INVALID_INPUT exige ring 0"
            )


def _is_sha256_hex(value) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    return all(char in "0123456789abcdefABCDEF" for char in value)


def _validate_break_glass_response(payload: dict) -> None:
    """Rejeita veredictos do Break Glass malformados ou contraditórios."""
    status = payload.get("break_glass_status")
    if status not in _BREAK_GLASS_STATUSES:
        raise GuardProtocolError(
            f"Resposta do Break Glass com status inválido: {status!r}"
        )

    autorizado = payload.get("autorizado")
    if type(autorizado) is not bool:
        raise GuardProtocolError("Resposta do Break Glass sem 'autorizado' booleano")

    for field in ("signature_verified", "nonce_consumed"):
        if type(payload.get(field)) is not bool:
            raise GuardProtocolError(
                f"Resposta do Break Glass sem '{field}' booleano"
            )

    for field in ("timestamp_unix", "server_timestamp_unix"):
        if type(payload.get(field)) is not int:
            raise GuardProtocolError(
                f"Resposta do Break Glass sem '{field}' inteiro"
            )

    for field in ("signature_algorithm", "gps_provenance",
                  "evidence_digest", "selo_criptografico"):
        if not isinstance(payload.get(field), str):
            raise GuardProtocolError(
                f"Resposta do Break Glass sem '{field}' textual"
            )

    for field in ("event_id", "request_id", "emitter_id", "subject_id", "key_id",
                  "nonce", "gps_coords", "camera_sha256", "audio_sha256"):
        value = payload.get(field)
        if value is not None and not isinstance(value, str):
            raise GuardProtocolError(
                f"Resposta do Break Glass com '{field}' de tipo inválido"
            )

    motivo = payload.get("motivo_recusa")
    if motivo is not None and not isinstance(motivo, str):
        raise GuardProtocolError(
            "Resposta do Break Glass com 'motivo_recusa' de tipo inválido"
        )

    if status == _BREAK_GLASS_AUTHORIZED:
        if autorizado is not True:
            raise GuardProtocolError(
                "Resposta contraditória: BREAK_GLASS_AUTHORIZED sem autorização"
            )
        if payload.get("signature_verified") is not True:
            raise GuardProtocolError(
                "Resposta contraditória: BREAK_GLASS_AUTHORIZED sem assinatura verificada"
            )
        if payload.get("nonce_consumed") is not True:
            raise GuardProtocolError(
                "Resposta contraditória: BREAK_GLASS_AUTHORIZED sem nonce consumido"
            )
        if motivo not in (None, ""):
            raise GuardProtocolError(
                "Resposta contraditória: autorização com motivo de recusa"
            )
        for field in ("event_id", "request_id", "emitter_id", "subject_id",
                      "key_id", "nonce", "camera_sha256", "audio_sha256"):
            if not isinstance(payload.get(field), str) or not payload.get(field):
                raise GuardProtocolError(
                    f"Resposta autorizada sem '{field}' não vazio"
                )
        for field in ("camera_sha256", "audio_sha256", "evidence_digest",
                      "selo_criptografico"):
            if not _is_sha256_hex(payload.get(field)):
                raise GuardProtocolError(
                    f"Resposta autorizada com '{field}' fora do formato SHA-256"
                )
        if payload.get("signature_algorithm") != "HMAC-SHA256":
            raise GuardProtocolError(
                "Resposta autorizada com algoritmo de assinatura inesperado"
            )
    else:
        if autorizado is not False:
            raise GuardProtocolError(
                "Resposta contraditória: status de falha com autorização"
            )
        if not isinstance(motivo, str) or not motivo.strip():
            raise GuardProtocolError(
                "Resposta de falha sem 'motivo_recusa' não vazio"
            )


def _parse_success(op: str, stdout: str) -> dict:
    text = (stdout or "").strip()
    if not text:
        raise GuardProtocolError("Resposta vazia do Guarda-Costas")

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as e:
        raise GuardProtocolError(f"Resposta inválida do Rust: {e}") from e

    if not isinstance(payload, dict):
        raise GuardProtocolError("Resposta do Rust não é um objeto JSON")
    if payload.get("status") != "ok":
        raise GuardProtocolError("Resposta do Rust sem status='ok'")

    if op == "hard_block":
        _validate_hard_block_response(payload)
    elif op == "kernel":
        _validate_kernel_response(payload)
    elif op == "break_glass":
        _validate_break_glass_response(payload)
    return payload


def _execution_integrity(binary, status: str, detail=None):
    """Monta o registro de integridade para falhas ocorridas após a verificação."""
    sha = getattr(binary, "sha256", None)
    if sha is None:
        return None
    return _binary_integrity_record(
        status,
        path=str(binary),
        label=getattr(binary, "label", None),
        expected_sha256=sha,
        actual_sha256=sha,
        detail=detail,
        verified_before_execution=(status == _BINARY_EXECUTION_ERROR),
    )


def _run_rust(op: str, data: dict) -> dict:
    """Executa o Rust e exige o contrato completo; levanta GuardError se falhar.

    O executável é o `_VerifiedBinary` devolvido por `_binary_path()`: os bytes
    em `/proc/self/fd/<fd>` são os mesmos lidos e hasheados, e o memfd está
    selado. Nenhuma resposta é lida antes da verificação.
    """
    try:
        envelope = json.dumps(
            {"op": op, "data": data}, ensure_ascii=False, allow_nan=False
        )
    except (TypeError, ValueError) as e:
        raise GuardInvalidInput(f"Payload não serializável: {e}") from e

    binary = _binary_path()
    fd = getattr(binary, "fd", None)
    if fd is not None:
        command = [f"{_PROC_SELF_FD}/{fd}"]
        run_kwargs = {"pass_fds": (fd,)}
    else:
        # Compatibilidade com testes que substituem `_binary_path` por um
        # caminho simples. Não há garantia de identidade nesse caso.
        command = [str(binary)]
        run_kwargs = {}

    try:
        try:
            result = subprocess.run(
                command,
                input=envelope,
                capture_output=True,
                text=True,
                timeout=_TIMEOUT_S,
                **run_kwargs,
            )
        except subprocess.TimeoutExpired as e:
            error = GuardCommunicationError(
                f"Guarda-Costas (Rust) timeout após {_TIMEOUT_S}s"
            )
            integrity = _execution_integrity(
                binary, _BINARY_EXECUTION_ERROR, "timeout durante a execução"
            )
            if integrity is not None:
                error.binary_integrity = integrity
            raise error from e
        except FileNotFoundError as e:
            error = GuardUnavailable("Binário guarda_costas não encontrado na execução")
            integrity = _execution_integrity(
                binary, _BINARY_EXECUTION_ERROR,
                "executável verificado não pôde ser iniciado",
            )
            if integrity is not None:
                error.binary_integrity = integrity
            raise error from e
        except OSError as e:
            error = GuardUnavailable(f"Falha ao executar o Guarda-Costas: {e}")
            integrity = _execution_integrity(
                binary, _BINARY_EXECUTION_ERROR, f"falha de execução: {e}"
            )
            if integrity is not None:
                error.binary_integrity = integrity
            raise error from e
    finally:
        close = getattr(binary, "close", None)
        if close is not None:
            close()

    stdout = result.stdout or ""
    stderr = result.stderr or ""

    if result.returncode != 0:
        kind, detail = _parse_error_payload(stdout)
        detail = detail or stderr.strip() or stdout.strip() or "sem detalhe"
        if result.returncode == 2:
            error = GuardInvalidInput(detail)
            integrity = _execution_integrity(
                binary, _BINARY_VERIFIED,
                "executável verificado rejeitou a entrada (código 2)",
            )
            if integrity is not None:
                error.binary_integrity = integrity
            raise error
        if result.returncode == 3:
            error = GuardInternalError(detail)
            integrity = _execution_integrity(
                binary, _BINARY_VERIFIED,
                "executável verificado declarou erro interno (código 3)",
            )
            if integrity is not None:
                error.binary_integrity = integrity
            raise error
        error = GuardCommunicationError(
            f"Rust terminou com código {result.returncode}: {detail}"
        )
        integrity = _execution_integrity(
            binary, _BINARY_EXECUTION_ERROR,
            f"código de saída inesperado: {result.returncode}",
        )
        if integrity is not None:
            error.binary_integrity = integrity
        raise error

    try:
        payload = _parse_success(op, stdout)
    except GuardProtocolError as e:
        integrity = _execution_integrity(
            binary, _BINARY_VERIFIED,
            "resposta malformada de executável verificado",
        )
        if integrity is not None:
            e.binary_integrity = integrity
        raise

    integrity = _execution_integrity(binary, _BINARY_VERIFIED)
    if integrity is not None:
        payload["binary_integrity"] = integrity
    return payload


def _call_rust(op: str, data: dict) -> dict:
    """Compatibilidade legada para `crud`.

    Break Glass passou ao contrato fail-closed da OS101 e não usa mais este
    retorno `{"error": ...}`.
    """
    try:
        return _run_rust(op, data)
    except GuardError as e:
        result = {"error": str(e)}
        if e.binary_integrity is not None:
            result["binary_integrity"] = e.binary_integrity
        return result


def _error_integrity(error):
    """Extrai o registro de integridade de uma falha, sem inventar sucesso."""
    integrity = getattr(error, "binary_integrity", None)
    if integrity is None and isinstance(error, GuardUnavailable):
        integrity = _binary_integrity_record(
            _BINARY_IDENTITY_UNAVAILABLE, detail=str(error)
        )
    return integrity


def _fail_closed(error: GuardError) -> dict:
    result = {
        "allowed": False,
        "blocked_by": error.blocked_by,
        "guard_status": error.guard_status,
        "effective_threshold": None,
        "stress_level": None,
        "reasoning": f"FAIL-CLOSED ({error.guard_status}): {error}",
    }
    integrity = _error_integrity(error)
    if integrity is not None:
        result["binary_integrity"] = integrity
    return result


def _validate_hard_block_inputs(action, stress_level, is_reincident, user_id) -> float:
    if not isinstance(action, str) or action not in _VALID_ACTIONS:
        raise GuardInvalidInput(
            f"action inválida: {action!r}; esperado um de {sorted(_VALID_ACTIONS)}"
        )
    if not _is_finite_number(stress_level):
        raise GuardInvalidInput(
            f"stress_level deve ser número finito; recebido: {stress_level!r}"
        )
    stress = float(stress_level)
    if not 0.0 <= stress <= 100.0:
        raise GuardInvalidInput(f"stress_level fora da faixa 0..100: {stress}")

    if type(is_reincident) is not bool:
        raise GuardInvalidInput(
            f"is_reincident deve ser booleano estrito; recebido: {is_reincident!r}"
        )

    if not isinstance(user_id, str):
        raise GuardInvalidInput(f"user_id deve ser string; recebido: {type(user_id).__name__}")
    if not user_id.strip():
        raise GuardInvalidInput("user_id vazio")
    if user_id != user_id.strip():
        raise GuardInvalidInput("user_id com espaço no início ou no fim")
    if len(user_id) > _MAX_USER_ID_CHARS:
        raise GuardInvalidInput(
            f"user_id com {len(user_id)} caracteres; máximo: {_MAX_USER_ID_CHARS}"
        )
    if any(ord(c) < 32 or ord(c) == 127 for c in user_id):
        raise GuardInvalidInput("user_id contém caractere de controle")

    return stress


def hard_block(action: str, stress_level: float, is_reincident: bool, user_id: str) -> dict:
    """Avalia se uma ação CRUD deve ser bloqueada com base no nível de estresse.

    Esta função é total para falhas do mecanismo: ausência do binário, timeout,
    erro de execução, JSON inválido, resposta malformada ou entrada inválida
    resultam em `allowed=False` com `guard_status` explícito.

    Args:
        action: "create", "read", "update" ou "delete".
        stress_level: nível de estresse atual (0-100), finito.
        is_reincident: se o usuário é reincidente (limiar cai para 66,5%).
        user_id: identificador do usuário (não vazio, até 256 caracteres).

    Returns:
        dict com {"allowed": bool, "blocked_by": str|None, "guard_status": str,
        "effective_threshold": number|None, "stress_level": number|None,
        "reasoning": str}
    """
    try:
        stress = _validate_hard_block_inputs(action, stress_level, is_reincident, user_id)
        payload = _run_rust(
            "hard_block",
            {
                "action": action,
                "stress_level": stress,
                "is_reincident": is_reincident,
                "user_id": user_id,
            },
        )
    except GuardError as e:
        return _fail_closed(e)

    payload["guard_status"] = "GUARD_OK"
    return payload


def _has_control_or_format(value: str) -> bool:
    for char in value:
        code = ord(char)
        if code < 32 or code == 127:
            return True
        if (
            0x200B <= code <= 0x200F
            or 0x202A <= code <= 0x202E
            or 0x2060 <= code <= 0x206F
            or code == 0xFEFF
        ):
            return True
    return False


def _validate_kernel_inputs(action, target, intent, from_majority_vote) -> None:
    if not isinstance(action, str) or action not in _VALID_ACTIONS:
        raise GuardInvalidInput(
            f"action inválida para o Kernel: {action!r}; esperado um de {sorted(_VALID_ACTIONS)}"
        )

    for name, value in (("target", target), ("intent", intent)):
        if not isinstance(value, str):
            raise GuardInvalidInput(
                f"{name} deve ser string; recebido: {type(value).__name__}"
            )
        if not value.strip():
            raise GuardInvalidInput(f"{name} vazio")
        if value != value.strip():
            raise GuardInvalidInput(f"{name} com espaço no início ou no fim")
        if len(value) > _MAX_KERNEL_FIELD_CHARS:
            raise GuardInvalidInput(
                f"{name} com {len(value)} caracteres; máximo: {_MAX_KERNEL_FIELD_CHARS}"
            )
        if _has_control_or_format(value):
            raise GuardInvalidInput(f"{name} contém caractere de controle/formatação")

    if type(from_majority_vote) is not bool:
        raise GuardInvalidInput(
            "from_majority_vote deve ser booleano estrito; "
            f"recebido: {from_majority_vote!r}"
        )


def _map_kernel_error(error: GuardError) -> str:
    if isinstance(error, GuardUnavailable):
        return _KERNEL_UNAVAILABLE
    if isinstance(error, GuardInvalidInput):
        return _KERNEL_INVALID_INPUT
    return _KERNEL_ERROR


def _kernel_fail_closed(status: str, action, from_majority_vote, error) -> dict:
    """Veredicto gerado pelo wrapper quando o Kernel não pode decidir."""
    action_value = action if isinstance(action, str) and action in _VALID_ACTIONS else None
    majority_value = from_majority_vote if type(from_majority_vote) is bool else None
    result = {
        "status": "error",
        "kernel_status": status,
        "allowed": False,
        "kernel_panic": False,
        "ring": 0,
        "action": action_value,
        "operation_class": "unknown",
        "target_category": "unavailable",
        "intent_category": "unavailable",
        "from_majority_vote": majority_value,
        "requires_review": True,
        "matched_rule": "fail_closed",
        "reasoning": f"FAIL-CLOSED ({status}): {error}",
    }
    if not isinstance(error, str):
        integrity = _error_integrity(error)
        if integrity is not None:
            result["binary_integrity"] = integrity
    return result


def _kernel_blocked_by(kernel: dict) -> str:
    return {
        _KERNEL_DENY: "kernel_constitucional",
        _KERNEL_REVIEW: "kernel_review",
        _KERNEL_UNAVAILABLE: "kernel_unavailable",
        _KERNEL_INVALID_INPUT: "kernel_invalid_input",
        _KERNEL_ERROR: "kernel_error",
    }.get(kernel.get("kernel_status"), "kernel_error")


def kernel_check(action: str, target: str, intent: str,
                 from_majority_vote: bool = False) -> dict:
    """Avalia um comando do Ring 3 contra as proteções imutáveis do Ring 0.

    O contrato é fail-closed: indisponibilidade, timeout, erro, resposta
    malformada, entrada inválida ou exceção inesperada resultam em
    `allowed=False` com `kernel_status` explícito. Somente `KERNEL_ALLOW`
    autoriza.

    Args:
        action: "create", "read", "update" ou "delete".
        target: alvo da ação (não vazio, até 256 caracteres).
        intent: intenção declarada (não vazia, até 256 caracteres).
        from_majority_vote: registrado no veredito; nunca sobrescreve Ring 0.

    Returns:
        dict com `kernel_status`, `allowed`, `kernel_panic`, `ring`,
        `operation_class`, `target_category`, `intent_category`,
        `from_majority_vote`, `requires_review`, `matched_rule` e `reasoning`.
    """
    try:
        _validate_kernel_inputs(action, target, intent, from_majority_vote)
        payload = _run_rust("kernel", {
            "action": action,
            "target": target,
            "intent": intent,
            "from_majority_vote": from_majority_vote,
        })
        _validate_kernel_response(payload)
        return payload
    except GuardError as e:
        return _kernel_fail_closed(
            _map_kernel_error(e), action, from_majority_vote, e
        )
    except Exception as e:  # defesa em profundidade: exceção nunca autoriza
        return _kernel_fail_closed(
            _KERNEL_ERROR,
            action,
            from_majority_vote,
            f"erro inesperado: {type(e).__name__}: {e}",
        )


def _finalize_direct_authorization(
    result: dict,
    *,
    hard,
    kernel,
    action: str,
    target,
    intent,
    user_id,
    subject_id,
    request_id: str,
    policy_controls=None,
    policy_evaluated: bool = False,
    decision: str = None,
    decision_reason: str = None,
    policy_provenance=None,
) -> dict:
    """Adicionar contrato de identidade/decisão a uma chamada direta.

    A chamada direta nunca é apresentada como autorização completa quando a
    política não foi avaliada. `authorization_complete=False` e
    `authority_scope` tornam a limitação explícita.
    """
    identity = build_identity_context(user_id, subject_id=subject_id)
    if decision is None:
        decision, decision_reason = derive_authorization_status(
            identity=identity,
            hard_block=hard,
            kernel=kernel,
            policy_controls=policy_controls,
            policy_evaluated=policy_evaluated,
        )
    complete = bool(policy_evaluated)
    record = build_authorization_record(
        request_id=request_id,
        identity=identity,
        action=action,
        target=target,
        intent=intent,
        threat_type=None,
        hard_block=hard,
        kernel=kernel,
        policy_controls=policy_controls,
        decision=decision,
        decision_reason=decision_reason,
        policy_evaluated=policy_evaluated,
        complete=complete,
        execution_status=EXECUTION_NOT_EXECUTED,
        execution_detail=(
            "Chamada direta de autorização; nenhum executor CRUD foi acionado."
        ),
        policy_provenance=policy_provenance,
    )
    result.update(record)
    result["authorization_status"] = decision
    result["authorization_complete"] = complete
    result["authority_scope"] = (
        "HARD_BLOCK_KERNEL_POLICY"
        if policy_evaluated
        else "HARD_BLOCK_KERNEL_ONLY"
    )
    result["policy_evaluated"] = bool(policy_evaluated)
    if policy_controls is not None:
        result["policy_controls"] = policy_controls
    if policy_provenance is not None:
        result["policy_provenance"] = policy_provenance
    if not policy_evaluated:
        result["partial_reason"] = (
            "Policy Engine não avaliado; esta decisão não é uma autorização "
            "completa e não autoriza execução."
        )
    integrity = None
    if isinstance(hard, dict):
        integrity = hard.get("binary_integrity")
    if integrity is None and isinstance(kernel, dict):
        integrity = kernel.get("binary_integrity")
    if integrity is not None:
        result["binary_integrity"] = integrity
    return result


def authorize_action(
    action: str,
    stress_level: float,
    is_reincident: bool,
    user_id: str,
    target: str = None,
    intent: str = None,
    from_majority_vote: bool = False,
    *,
    policy_result: dict = None,
    subject_id: str = None,
    request_id: str = None,
    expected_policy_engine_id: str = None,
) -> dict:
    """Ponto central de autorização antes de qualquer operação protegida.

    Ordem: identidade declarada -> Hard Block (OS099) -> Kernel Constitucional
    (OS100) -> Policy Engine (OS105/OS112/OS115). O Hard Block vem primeiro
    para preservar o contrato fail-closed da OS099 quando o binário está
    indisponível.

    Para `create`, `update` e `delete`, `target` e `intent` são obrigatórios.
    Para `read`, se omitidos, o Kernel avalia `user_id` e a intenção
    `"leitura"`.

    **Contrato OS112:** se `policy_result` for fornecido, `read_only` e
    `adjusted_threshold` são aplicados aqui, no mesmo ponto da decisão. Se
    `policy_result` não for fornecido:

    - `read` pode ser autorizado como decisão **parcial**;
    - `create/update/delete` falham fechado com
      `blocked_by="policy_context_required"`.

    **Contrato OS115:** `policy_result` precisa ter sido emitido por
    `PolicyEngine20.evaluate()` com o mesmo `request_id`, `user_id`,
    `subject_id` e `action` desta chamada. A verificação ocorre antes de
    qualquer decisão de autorização completa. Um dicionário estruturalmente
    válido sem proveniência registrada é rejeitado; `"source": "PolicyEngine"`
    não é prova. A avaliação é consumida no sucesso (uso único), e cópias,
    reutilizações ou alterações são rejeitadas.

    `expected_policy_engine_id` permite exigir uma instância específica do
    Policy Engine; o fluxo principal do motor sempre o fornece. Sem ele, a
    verificação ainda garante emissão no processo e vínculo contextual, mas
    não distingue duas instâncias locais.

    Identidade é declarada, não autenticada. `user_id`/`subject_id` não são
    prova de identidade. A função não executa ação; `execution.status` sempre
    indica `NOT_EXECUTED`.
    """
    request_id_value = new_request_id() if request_id is None else request_id
    identity = build_identity_context(user_id, subject_id=subject_id)
    request_error = validate_identifier("request_id", request_id_value)
    engine_error = (
        validate_identifier("expected_policy_engine_id", expected_policy_engine_id)
        if expected_policy_engine_id is not None
        else None
    )
    if not identity.is_valid or request_error is not None or engine_error is not None:
        input_error = (
            identity.error
            or request_error
            or engine_error
            or "contexto de autorização inválido"
        )
        return _finalize_direct_authorization(
            {
                "allowed": False,
                "blocked_by": "guard_invalid_input",
                "guard_status": "GUARD_INVALID_INPUT",
                "kernel_status": "KERNEL_NOT_EVALUATED",
                "kernel": None,
                "hard_block": {},
                "reasoning": f"ENTRADA INVÁLIDA: {input_error}",
            },
            hard={},
            kernel=None,
            action=action,
            target=target,
            intent=intent,
            user_id=user_id,
            subject_id=subject_id,
            request_id=request_id_value,
            policy_controls=None,
            policy_evaluated=False,
            decision=AUTHORIZATION_INPUT_INVALID,
            decision_reason=input_error,
        )

    try:
        hard = hard_block(action, stress_level, is_reincident, user_id)
    except Exception as error:  # exceção de mecanismo nunca autoriza
        hard = {
            "allowed": False,
            "blocked_by": "guard_internal_error",
            "guard_status": "GUARD_INTERNAL_ERROR",
            "effective_threshold": None,
            "reasoning": (
                "FAIL-CLOSED (GUARD_INTERNAL_ERROR): "
                f"{type(error).__name__}: {error}"
            ),
        }

    if hard.get("allowed") is not True or hard.get("guard_status") != "GUARD_OK":
        return _finalize_direct_authorization(
            {
                "allowed": False,
                "blocked_by": hard.get("blocked_by") or "guard_unavailable",
                "guard_status": hard.get("guard_status") or "GUARD_PROTOCOL_ERROR",
                "kernel_status": "KERNEL_NOT_EVALUATED",
                "kernel": None,
                "hard_block": hard,
                "reasoning": hard.get("reasoning"),
            },
            hard=hard,
            kernel=None,
            action=action,
            target=target,
            intent=intent,
            user_id=user_id,
            subject_id=subject_id,
            request_id=request_id_value,
        )

    protected = action in _PROTECTED_ACTIONS
    if protected and (target is None or intent is None):
        kernel = _kernel_fail_closed(
            _KERNEL_INVALID_INPUT,
            action,
            from_majority_vote,
            "target e intent são obrigatórios para operações protegidas",
        )
    else:
        kernel_target = user_id if target is None else target
        kernel_intent = "leitura" if intent is None else intent
        try:
            kernel = kernel_check(
                action, kernel_target, kernel_intent, from_majority_vote
            )
        except Exception as e:  # defesa em profundidade: exceção nunca autoriza
            kernel = _kernel_fail_closed(
                _KERNEL_ERROR,
                action,
                from_majority_vote,
                f"erro inesperado no Kernel: {type(e).__name__}: {e}",
            )

    if kernel.get("kernel_status") != _KERNEL_ALLOW or kernel.get("allowed") is not True:
        return _finalize_direct_authorization(
            {
                "allowed": False,
                "blocked_by": _kernel_blocked_by(kernel),
                "guard_status": "GUARD_OK",
                "kernel_status": kernel.get("kernel_status") or _KERNEL_ERROR,
                "kernel": kernel,
                "hard_block": hard,
                "reasoning": kernel.get("reasoning"),
            },
            hard=hard,
            kernel=kernel,
            action=action,
            target=target,
            intent=intent,
            user_id=user_id,
            subject_id=subject_id,
            request_id=request_id_value,
        )

    policy_controls = None
    policy_evaluated = False
    policy_provenance = {
        "status": PROVENANCE_ABSENT,
        "valid": False,
        "blocked_by": None,
        "reason": "policy_result ausente",
        "evaluation_id": None,
        "engine_id": None,
        "contract_version": None,
    }
    if policy_result is not None:
        policy_error = validate_policy_result(policy_result)
        if policy_error is not None:
            return _finalize_direct_authorization(
                {
                    "allowed": False,
                    "blocked_by": "policy_state_invalid",
                    "guard_status": "GUARD_OK",
                    "kernel_status": _KERNEL_ALLOW,
                    "kernel": kernel,
                    "hard_block": hard,
                    "reasoning": (
                        "FAIL-CLOSED (POLICY_STATE_INVALID): "
                        f"{policy_error}. Hard Block e Kernel permitiram, mas "
                        "o contexto de política não é utilizável."
                    ),
                },
                hard=hard,
                kernel=kernel,
                action=action,
                target=target,
                intent=intent,
                user_id=user_id,
                subject_id=subject_id,
                request_id=request_id_value,
                policy_controls={
                    "evaluated": False,
                    "status": "POLICY_STATE_INVALID",
                    "blocked_by_policy": "policy_state_invalid",
                    "policy_level": None,
                    "policy_level_valid": False,
                    "validation_error": policy_error,
                },
                policy_evaluated=False,
                decision=AUTHORIZATION_DENIED,
                decision_reason=f"policy_result inválido: {policy_error}",
                policy_provenance={
                    "status": PROVENANCE_MALFORMED,
                    "valid": False,
                    "blocked_by": "policy_state_invalid",
                    "reason": policy_error,
                    "evaluation_id": None,
                    "engine_id": None,
                    "contract_version": None,
                },
            )

        # OS115: proveniência e vínculo contextual são verificados ANTES de
        # qualquer decisão completa. A avaliação é consumida no sucesso.
        try:
            policy_provenance = verify_policy_result(
                policy_result,
                request_id=request_id_value,
                user_id=user_id,
                subject_id=subject_id,
                action=action,
                expected_engine_id=expected_policy_engine_id,
            )
        except Exception as error:  # falha de validação nunca autoriza
            provenance_error = {
                "status": PROVENANCE_ERROR,
                "valid": False,
                "blocked_by": "policy_provenance_error",
                "reason": f"{type(error).__name__}: {error}",
                "evaluation_id": None,
                "engine_id": None,
                "contract_version": None,
            }
            return _finalize_direct_authorization(
                {
                    "allowed": False,
                    "blocked_by": "policy_provenance_error",
                    "guard_status": "GUARD_OK",
                    "kernel_status": _KERNEL_ALLOW,
                    "kernel": kernel,
                    "hard_block": hard,
                    "reasoning": (
                        "FAIL-CLOSED (POLICY_PROVENANCE_ERROR): "
                        f"{type(error).__name__}: {error}"
                    ),
                },
                hard=hard,
                kernel=kernel,
                action=action,
                target=target,
                intent=intent,
                user_id=user_id,
                subject_id=subject_id,
                request_id=request_id_value,
                policy_controls={
                    "evaluated": False,
                    "status": "POLICY_PROVENANCE_ERROR",
                    "blocked_by_policy": None,
                    "provenance_status": PROVENANCE_ERROR,
                    "provenance_reason": provenance_error["reason"],
                },
                policy_evaluated=False,
                decision=AUTHORIZATION_INFRASTRUCTURE_FAILURE,
                decision_reason=(
                    "Falha interna ao validar proveniência da política: "
                    f"{type(error).__name__}"
                ),
                policy_provenance=provenance_error,
            )

        if policy_provenance["status"] != PROVENANCE_VALID:
            provenance_status = policy_provenance["status"]
            provenance_reason = policy_provenance["reason"]
            blocked_by_provenance = (
                policy_provenance.get("blocked_by") or "policy_provenance_invalid"
            )
            return _finalize_direct_authorization(
                {
                    "allowed": False,
                    "blocked_by": blocked_by_provenance,
                    "guard_status": "GUARD_OK",
                    "kernel_status": _KERNEL_ALLOW,
                    "kernel": kernel,
                    "hard_block": hard,
                    "reasoning": (
                        "FAIL-CLOSED (POLICY_PROVENANCE_REJECTED): "
                        f"{provenance_status}: {provenance_reason}. Hard Block "
                        "e Kernel permitiram, mas o resultado de política não "
                        "tem proveniência/vínculo válidos."
                    ),
                },
                hard=hard,
                kernel=kernel,
                action=action,
                target=target,
                intent=intent,
                user_id=user_id,
                subject_id=subject_id,
                request_id=request_id_value,
                policy_controls={
                    "evaluated": False,
                    "status": "POLICY_PROVENANCE_REJECTED",
                    "blocked_by_policy": blocked_by_provenance,
                    "provenance_status": provenance_status,
                    "provenance_reason": provenance_reason,
                    "policy_level": None,
                    "policy_level_valid": False,
                    "validation_error": provenance_reason,
                },
                policy_evaluated=False,
                decision=AUTHORIZATION_DENIED,
                decision_reason=(
                    "policy_result rejeitado: "
                    f"{provenance_status} ({provenance_reason})"
                ),
                policy_provenance=policy_provenance,
            )

        try:
            policy_controls = build_policy_controls(
                policy_result, action, hard, enforced=True
            )
        except Exception as error:  # falha de política nunca autoriza
            return _finalize_direct_authorization(
                {
                    "allowed": False,
                    "blocked_by": "policy_internal_error",
                    "guard_status": "GUARD_OK",
                    "kernel_status": _KERNEL_ALLOW,
                    "kernel": kernel,
                    "hard_block": hard,
                    "reasoning": (
                        "FAIL-CLOSED (POLICY_INTERNAL_ERROR): "
                        f"{type(error).__name__}: {error}"
                    ),
                },
                hard=hard,
                kernel=kernel,
                action=action,
                target=target,
                intent=intent,
                user_id=user_id,
                subject_id=subject_id,
                request_id=request_id_value,
                policy_controls={
                    "evaluated": False,
                    "status": "POLICY_INTERNAL_ERROR",
                    "blocked_by_policy": None,
                },
                policy_evaluated=False,
                decision=AUTHORIZATION_INFRASTRUCTURE_FAILURE,
                decision_reason=(
                    "Policy Engine não pôde avaliar a política: "
                    f"{type(error).__name__}"
                ),
                policy_provenance=policy_provenance,
            )
        policy_evaluated = True
        blocked_by_policy = policy_controls.get("blocked_by_policy")
        if blocked_by_policy:
            return _finalize_direct_authorization(
                {
                    "allowed": False,
                    "blocked_by": blocked_by_policy,
                    "guard_status": "GUARD_OK",
                    "kernel_status": _KERNEL_ALLOW,
                    "kernel": kernel,
                    "hard_block": hard,
                    "reasoning": (
                        f"POLÍTICA ({blocked_by_policy}): Hard Block e Kernel "
                        "permitiram, mas a política restringiu a operação."
                    ),
                },
                hard=hard,
                kernel=kernel,
                action=action,
                target=target,
                intent=intent,
                user_id=user_id,
                subject_id=subject_id,
                request_id=request_id_value,
                policy_controls=policy_controls,
                policy_evaluated=True,
                decision=AUTHORIZATION_DENIED,
                decision_reason=f"Policy negou: {blocked_by_policy}",
                policy_provenance=policy_provenance,
            )
    elif action in _PROTECTED_ACTIONS:
        return _finalize_direct_authorization(
            {
                "allowed": False,
                "blocked_by": "policy_context_required",
                "guard_status": "GUARD_OK",
                "kernel_status": _KERNEL_ALLOW,
                "kernel": kernel,
                "hard_block": hard,
                "reasoning": (
                    "POLÍTICA NÃO AVALIADA: create/update/delete exigem "
                    "policy_result; a chamada direta falha fechado."
                ),
            },
            hard=hard,
            kernel=kernel,
            action=action,
            target=target,
            intent=intent,
            user_id=user_id,
            subject_id=subject_id,
            request_id=request_id_value,
            policy_controls=None,
            policy_evaluated=False,
            decision=AUTHORIZATION_DENIED,
            decision_reason=(
                "policy_context_required: operação de escrita sem avaliação "
                "de política"
            ),
        )

    return _finalize_direct_authorization(
        {
            "allowed": True,
            "blocked_by": None,
            "guard_status": "GUARD_OK",
            "kernel_status": _KERNEL_ALLOW,
            "kernel": kernel,
            "hard_block": hard,
            "reasoning": (
                "AUTORIZADO: Hard Block, Kernel Constitucional"
                + (" e Policy" if policy_evaluated else "")
                + " permitiram a operação."
            ),
        },
        hard=hard,
        kernel=kernel,
        action=action,
        target=target,
        intent=intent,
        user_id=user_id,
        subject_id=subject_id,
        request_id=request_id_value,
        policy_controls=policy_controls,
        policy_evaluated=policy_evaluated,
        policy_provenance=policy_provenance,
    )


def _break_glass_context(
    event_id=None,
    request_id=None,
    emitter_id=None,
    subject_id=None,
    timestamp_unix=None,
    nonce=None,
    key_id=None,
    gps_coords=None,
    **kwargs,
) -> dict:
    """Campos seguros para devolver em um veredicto fail-closed."""
    del kwargs
    return {
        "event_id": event_id if isinstance(event_id, str) else None,
        "request_id": request_id if isinstance(request_id, str) else None,
        "emitter_id": emitter_id if isinstance(emitter_id, str) else None,
        "subject_id": subject_id if isinstance(subject_id, str) else None,
        "key_id": key_id if isinstance(key_id, str) else None,
        "timestamp_unix": timestamp_unix if type(timestamp_unix) is int else 0,
        "nonce": nonce if isinstance(nonce, str) else None,
        "gps_coords": gps_coords if isinstance(gps_coords, str) else None,
        "gps_provenance": (
            "declared_metadata_unauthenticated"
            if isinstance(gps_coords, str) and gps_coords
            else "not_provided"
        ),
    }


def _break_glass_fail_closed(status: str, reason: str, *,
                             binary_integrity=None, **fields) -> dict:
    context = _break_glass_context(**fields)
    result = {
        "status": "error",
        "autorizado": False,
        "break_glass_status": status,
        "event_id": context["event_id"],
        "request_id": context["request_id"],
        "emitter_id": context["emitter_id"],
        "subject_id": context["subject_id"],
        "key_id": context["key_id"],
        "timestamp_unix": context["timestamp_unix"],
        "server_timestamp_unix": int(time.time()),
        "camera_sha256": None,
        "audio_sha256": None,
        "gps_coords": context["gps_coords"],
        "gps_provenance": context["gps_provenance"],
        "nonce": context["nonce"],
        "signature_algorithm": "HMAC-SHA256",
        "signature_verified": False,
        "nonce_consumed": False,
        "evidence_digest": "",
        "selo_criptografico": "",
        "motivo_recusa": f"FAIL-CLOSED ({status}): {reason}",
    }
    if binary_integrity is not None:
        result["binary_integrity"] = binary_integrity
    return result


def _map_break_glass_error(error: GuardError) -> str:
    if isinstance(error, GuardInvalidInput):
        return _BREAK_GLASS_INVALID_INPUT
    if isinstance(error, (GuardUnavailable, GuardCommunicationError)):
        return _BREAK_GLASS_UNAVAILABLE
    return _BREAK_GLASS_INTERNAL_ERROR


def _validate_break_glass_inputs(**fields) -> None:
    missing = [
        name
        for name in _BREAK_GLASS_REQUIRED_FIELDS
        if fields.get(name) is None
    ]
    if missing:
        raise GuardInvalidInput(
            "campos obrigatórios ausentes: " + ", ".join(missing)
        )

    if type(fields.get("timestamp_unix")) is not int:
        raise GuardInvalidInput("timestamp_unix deve ser inteiro")

    for name in _BREAK_GLASS_REQUIRED_FIELDS:
        if name == "timestamp_unix":
            continue
        value = fields.get(name)
        if not isinstance(value, str) or not value.strip():
            raise GuardInvalidInput(f"{name} vazio ou de tipo inválido")

    gps_coords = fields.get("gps_coords")
    if gps_coords is not None and not isinstance(gps_coords, str):
        raise GuardInvalidInput("gps_coords deve ser string ou null")


def break_glass(camera_hash: str = None, audio_hash: str = None,
                gps_coords: str = None, justificativa: str = "",
                *, event_id: str = None, request_id: str = None,
                emitter_id: str = None, subject_id: str = None,
                timestamp_unix: int = None, nonce: str = None, key_id: str = None,
                camera_file: str = None, camera_media_type: str = None,
                camera_sha256: str = None, audio_file: str = None,
                audio_media_type: str = None, audio_sha256: str = None,
                signature_hmac_sha256: str = None) -> dict:
    """Avalia uma solicitação de Break Glass com evidência verificável.

    O contrato OS101 exige: identificadores de evento/requisição/emissor,
    timestamp, nonce, chave, arquivos reais de câmera e áudio, digests
    SHA-256, justificativa e assinatura HMAC-SHA256 da serialização canônica.
    O wrapper **não** assina e **não** possui a chave; a assinatura deve vir
    do componente emissor confiável.

    `camera_hash` e `audio_hash` são parâmetros legados mantidos apenas para
    compatibilidade de assinatura. Hashes declarados sem arquivos reais não
    são evidência suficiente e resultam em `BREAK_GLASS_INVALID_INPUT`.

    Returns:
        dict com `autorizado`, `break_glass_status`, digests, verificação de
        assinatura, consumo de nonce e motivo de recusa. Somente
        `BREAK_GLASS_AUTHORIZED` com `autorizado is True` representa sucesso.
    """
    del camera_hash, audio_hash  # legado: não é evidência no contrato OS101

    fields = {
        "event_id": event_id,
        "request_id": request_id,
        "emitter_id": emitter_id,
        "subject_id": subject_id,
        "timestamp_unix": timestamp_unix,
        "nonce": nonce,
        "key_id": key_id,
        "camera_file": camera_file,
        "camera_media_type": camera_media_type,
        "camera_sha256": camera_sha256,
        "audio_file": audio_file,
        "audio_media_type": audio_media_type,
        "audio_sha256": audio_sha256,
        "gps_coords": gps_coords,
        "justificativa": justificativa,
        "signature_hmac_sha256": signature_hmac_sha256,
    }

    try:
        _validate_break_glass_inputs(**fields)
        payload = _run_rust("break_glass", {
            "event_id": event_id,
            "request_id": request_id,
            "emitter_id": emitter_id,
            "subject_id": subject_id,
            "timestamp_unix": timestamp_unix,
            "nonce": nonce,
            "key_id": key_id,
            "camera_file": camera_file,
            "camera_media_type": camera_media_type,
            "camera_sha256": camera_sha256,
            "audio_file": audio_file,
            "audio_media_type": audio_media_type,
            "audio_sha256": audio_sha256,
            "gps_coords": gps_coords,
            "justificativa": justificativa,
            "signature_hmac_sha256": signature_hmac_sha256,
        })
        _validate_break_glass_response(payload)
        if payload.get("break_glass_status") == _BREAK_GLASS_AUTHORIZED:
            exact_fields = {
                "event_id": event_id,
                "request_id": request_id,
                "emitter_id": emitter_id,
                "subject_id": subject_id,
                "key_id": key_id,
                "nonce": nonce,
            }
            for field, expected in exact_fields.items():
                if payload.get(field) != expected:
                    raise GuardProtocolError(
                        f"Resposta autorizada não corresponde ao campo '{field}'"
                    )
            for field, expected in (
                ("camera_sha256", camera_sha256),
                ("audio_sha256", audio_sha256),
            ):
                if payload.get(field, "").lower() != expected.lower():
                    raise GuardProtocolError(
                        f"Resposta autorizada não corresponde ao campo '{field}'"
                    )
        return payload
    except GuardError as error:
        return _break_glass_fail_closed(
            _map_break_glass_error(error), str(error),
            binary_integrity=_error_integrity(error), **fields
        )
    except Exception as error:  # defesa em profundidade: exceção nunca autoriza
        return _break_glass_fail_closed(
            _BREAK_GLASS_INTERNAL_ERROR,
            f"erro inesperado: {type(error).__name__}: {error}",
            **fields,
        )


def classify_crud(action: str) -> dict:
    """Classifica uma ação CRUD quanto à elegibilidade para bloqueio (Paradoxo do Jornalista)."""
    return _call_rust("crud", {"action": action})
