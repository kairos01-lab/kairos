//! Protocolo Break Glass - Botão de Pânico.
//!
//! Quando o Hard Block do Contrato de Ulisses trava o usuário numa emergência
//! real, o humano aciona a quebra de vidro. A máquina deixa de ser Bloqueadora
//! e vira Testemunha.
//!
//! OS101 - contrato de evidência:
//! - lê os bytes reais dos arquivos de câmera e áudio;
//! - calcula SHA-256 do conteúdo e compara com o digest declarado;
//! - verifica uma assinatura HMAC-SHA256 sobre uma serialização canônica;
//! - vincula evento, requisição, emissor, timestamp, nonce e digests;
//! - consome o nonce e o par de evidências em armazenamento persistente para
//!   impedir replay e reutilização em outro evento;
//! - falha fechado em qualquer erro, ausência de chave, resposta inválida ou
//!   indisponibilidade.
//!
//! Limites explícitos:
//! - HMAC prova posse da chave provisionada, não atestação de hardware;
//! - o conteúdo de mídia é validado apenas por magic bytes e tamanho;
//! - GPS é metadado declarado, não uma fonte autenticada;
//! - o Break Glass **não** libera Hard Block nem Kernel. Ele apenas valida a
//!   evidência de emergência. A liberação de operação não é implementada aqui.

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::env;
use std::fs::{self, File, OpenOptions};
use std::io::{BufReader, Read, Write};
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

const KEY_DIR_ENV: &str = "KAIROS_BREAK_GLASS_KEY_DIR";
const EVIDENCE_DIR_ENV: &str = "KAIROS_BREAK_GLASS_EVIDENCE_DIR";
const STATE_DIR_ENV: &str = "KAIROS_BREAK_GLASS_STATE_DIR";

const MAX_EVIDENCE_BYTES: u64 = 64 * 1024 * 1024;
const MAX_ID_CHARS: usize = 128;
const MAX_NONCE_CHARS: usize = 128;
const MIN_NONCE_CHARS: usize = 16;
const MAX_JUSTIFICATION_CHARS: usize = 2000;
const MAX_GPS_CHARS: usize = 64;
const MAX_CLOCK_SKEW_SECS: i64 = 300;
const SHA256_HEX_CHARS: usize = 64;

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct BreakGlassRequest {
    /// Identificador do evento de emergência. Vinculado à assinatura.
    pub event_id: String,
    /// Identificador da requisição. Vinculado à assinatura.
    pub request_id: String,
    /// Identidade declarada do emissor; precisa corresponder ao vínculo da chave.
    pub emitter_id: String,
    /// Sujeito da emergência (usuário ou entidade). Vinculado à assinatura.
    pub subject_id: String,
    /// Timestamp Unix da coleta/assinatura. Janela de ±300 segundos.
    pub timestamp_unix: i64,
    /// Nonce único, de 16 a 128 caracteres. Consumido uma única vez.
    pub nonce: String,
    /// Identificador da chave HMAC provisionada.
    pub key_id: String,
    /// Nome simples do arquivo de câmera dentro do diretório de evidências.
    pub camera_file: String,
    /// `jpeg`, `png` ou `mp4`.
    pub camera_media_type: String,
    /// SHA-256 declarado do conteúdo real do arquivo de câmera.
    pub camera_sha256: String,
    /// Nome simples do arquivo de áudio dentro do diretório de evidências.
    pub audio_file: String,
    /// `wav`, `mp3`, `ogg` ou `mp4`.
    pub audio_media_type: String,
    /// SHA-256 declarado do conteúdo real do arquivo de áudio.
    pub audio_sha256: String,
    /// GPS declarado no formato "lat,lon". Metadado não autenticado.
    pub gps_coords: Option<String>,
    /// Justificativa textual da emergência.
    pub justificativa: String,
    /// HMAC-SHA256 hexadecimal da serialização canônica.
    pub signature_hmac_sha256: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub enum BreakGlassStatus {
    #[serde(rename = "BREAK_GLASS_AUTHORIZED")]
    Authorized,
    #[serde(rename = "BREAK_GLASS_DENIED")]
    Denied,
    #[serde(rename = "BREAK_GLASS_INVALID_INPUT")]
    InvalidInput,
    #[serde(rename = "BREAK_GLASS_INVALID_EVIDENCE")]
    InvalidEvidence,
    #[serde(rename = "BREAK_GLASS_INTEGRITY_FAILURE")]
    IntegrityFailure,
    #[serde(rename = "BREAK_GLASS_AUTHENTICATION_FAILURE")]
    AuthenticationFailure,
    #[serde(rename = "BREAK_GLASS_AUTHENTICATION_UNAVAILABLE")]
    AuthenticationUnavailable,
    #[serde(rename = "BREAK_GLASS_REPLAY_DETECTED")]
    ReplayDetected,
    #[serde(rename = "BREAK_GLASS_UNAVAILABLE")]
    Unavailable,
    #[serde(rename = "BREAK_GLASS_INTERNAL_ERROR")]
    InternalError,
}

#[derive(Debug, Clone, Serialize)]
pub struct BreakGlassVerdict {
    pub autorizado: bool,
    pub break_glass_status: BreakGlassStatus,
    pub event_id: Option<String>,
    pub request_id: Option<String>,
    pub emitter_id: Option<String>,
    pub subject_id: Option<String>,
    pub key_id: Option<String>,
    pub timestamp_unix: i64,
    pub server_timestamp_unix: i64,
    pub camera_sha256: Option<String>,
    pub audio_sha256: Option<String>,
    pub gps_coords: Option<String>,
    pub gps_provenance: String,
    pub nonce: Option<String>,
    pub signature_algorithm: String,
    pub signature_verified: bool,
    pub nonce_consumed: bool,
    /// SHA-256 da serialização canônica assinada.
    pub evidence_digest: String,
    /// HMAC-SHA256 verificado; vazio em caso de falha.
    pub selo_criptografico: String,
    pub motivo_recusa: Option<String>,
}

#[derive(Debug, Clone)]
pub struct BreakGlassConfig {
    pub key_dir: PathBuf,
    pub evidence_dir: PathBuf,
    pub state_dir: PathBuf,
}

impl BreakGlassConfig {
    fn from_env() -> Result<Self, BreakGlassError> {
        Ok(Self {
            key_dir: env_path(KEY_DIR_ENV)?,
            evidence_dir: env_path(EVIDENCE_DIR_ENV)?,
            state_dir: env_path(STATE_DIR_ENV)?,
        })
    }
}

fn env_path(name: &str) -> Result<PathBuf, BreakGlassError> {
    let value = env::var(name)
        .map_err(|_| BreakGlassError::Unavailable(format!("{name} não configurado")))?;
    if value.trim().is_empty() {
        return Err(BreakGlassError::Unavailable(format!(
            "{name} não configurado"
        )));
    }
    Ok(PathBuf::from(value))
}

#[derive(Debug, Clone, PartialEq, Eq)]
enum BreakGlassError {
    InvalidEvidence(String),
    Authentication(String),
    AuthenticationUnavailable(String),
    Replay(String),
    Unavailable(String),
    Internal(String),
}

impl BreakGlassError {
    fn status(&self) -> BreakGlassStatus {
        match self {
            Self::InvalidEvidence(_) => BreakGlassStatus::InvalidEvidence,
            Self::Authentication(_) => BreakGlassStatus::AuthenticationFailure,
            Self::AuthenticationUnavailable(_) => BreakGlassStatus::AuthenticationUnavailable,
            Self::Replay(_) => BreakGlassStatus::ReplayDetected,
            Self::Unavailable(_) => BreakGlassStatus::Unavailable,
            Self::Internal(_) => BreakGlassStatus::InternalError,
        }
    }

    fn reason(&self) -> &str {
        match self {
            Self::InvalidEvidence(s)
            | Self::Authentication(s)
            | Self::AuthenticationUnavailable(s)
            | Self::Replay(s)
            | Self::Unavailable(s)
            | Self::Internal(s) => s,
        }
    }
}

/// Validação estrutural da requisição. Não lê arquivos nem chaves.
pub fn validate_request(req: &BreakGlassRequest) -> Result<(), String> {
    validate_identifier("event_id", &req.event_id, MAX_ID_CHARS)?;
    validate_identifier("request_id", &req.request_id, MAX_ID_CHARS)?;
    validate_identifier("emitter_id", &req.emitter_id, MAX_ID_CHARS)?;
    validate_identifier("subject_id", &req.subject_id, MAX_ID_CHARS)?;
    validate_key_id("key_id", &req.key_id)?;
    validate_nonce(&req.nonce)?;
    validate_file_name("camera_file", &req.camera_file)?;
    validate_file_name("audio_file", &req.audio_file)?;

    if !matches!(req.camera_media_type.as_str(), "jpeg" | "png" | "mp4") {
        return Err("camera_media_type inválido; esperado jpeg, png ou mp4".to_string());
    }
    if !matches!(req.audio_media_type.as_str(), "wav" | "mp3" | "ogg" | "mp4") {
        return Err("audio_media_type inválido; esperado wav, mp3, ogg ou mp4".to_string());
    }

    if !is_hex(&req.camera_sha256, SHA256_HEX_CHARS) {
        return Err("camera_sha256 deve ser SHA-256 hexadecimal de 64 caracteres".to_string());
    }
    if !is_hex(&req.audio_sha256, SHA256_HEX_CHARS) {
        return Err("audio_sha256 deve ser SHA-256 hexadecimal de 64 caracteres".to_string());
    }
    if !is_hex(&req.signature_hmac_sha256, SHA256_HEX_CHARS) {
        return Err(
            "signature_hmac_sha256 deve ser HMAC-SHA256 hexadecimal de 64 caracteres".to_string(),
        );
    }

    if req.timestamp_unix <= 0 {
        return Err("timestamp_unix deve ser positivo".to_string());
    }

    if req.justificativa.trim().is_empty() {
        return Err("justificativa vazia".to_string());
    }
    if req.justificativa.chars().count() > MAX_JUSTIFICATION_CHARS {
        return Err(format!(
            "justificativa excede {MAX_JUSTIFICATION_CHARS} caracteres"
        ));
    }
    if req.justificativa.chars().any(char::is_control) {
        return Err("justificativa contém caractere de controle".to_string());
    }

    if let Some(gps) = &req.gps_coords {
        validate_gps(gps)?;
    }

    Ok(())
}

fn validate_identifier(field: &str, value: &str, max: usize) -> Result<(), String> {
    let len = value.chars().count();
    if len == 0 || len > max {
        return Err(format!("{field} deve ter entre 1 e {max} caracteres"));
    }
    let first = value.chars().next().unwrap_or('\0');
    if !first.is_ascii_alphanumeric() {
        return Err(format!("{field} deve começar com letra ou dígito"));
    }
    if !value
        .chars()
        .all(|c| c.is_ascii_alphanumeric() || matches!(c, '.' | '_' | ':' | '-'))
    {
        return Err(format!("{field} contém caractere não permitido"));
    }
    Ok(())
}

fn validate_key_id(field: &str, value: &str) -> Result<(), String> {
    let len = value.chars().count();
    if len == 0 || len > 64 {
        return Err(format!("{field} deve ter entre 1 e 64 caracteres"));
    }
    let first = value.chars().next().unwrap_or('\0');
    if !first.is_ascii_alphanumeric() {
        return Err(format!("{field} deve começar com letra ou dígito"));
    }
    if !value
        .chars()
        .all(|c| c.is_ascii_alphanumeric() || matches!(c, '.' | '_' | '-'))
    {
        return Err(format!("{field} contém caractere não permitido"));
    }
    Ok(())
}

fn validate_nonce(value: &str) -> Result<(), String> {
    let len = value.chars().count();
    if !(MIN_NONCE_CHARS..=MAX_NONCE_CHARS).contains(&len) {
        return Err(format!(
            "nonce deve ter entre {MIN_NONCE_CHARS} e {MAX_NONCE_CHARS} caracteres"
        ));
    }
    let first = value.chars().next().unwrap_or('\0');
    if !first.is_ascii_alphanumeric() {
        return Err("nonce deve começar com letra ou dígito".to_string());
    }
    if !value
        .chars()
        .all(|c| c.is_ascii_alphanumeric() || matches!(c, '.' | '_' | ':' | '-'))
    {
        return Err("nonce contém caractere não permitido".to_string());
    }
    Ok(())
}

fn validate_file_name(field: &str, value: &str) -> Result<(), String> {
    let len = value.chars().count();
    if len == 0 || len > 255 {
        return Err(format!("{field} deve ter entre 1 e 255 caracteres"));
    }
    let first = value.chars().next().unwrap_or('\0');
    if !first.is_ascii_alphanumeric() {
        return Err(format!("{field} deve começar com letra ou dígito"));
    }
    if !value
        .chars()
        .all(|c| c.is_ascii_alphanumeric() || matches!(c, '.' | '_' | '-'))
    {
        return Err(format!(
            "{field} deve ser um nome simples, sem separadores de caminho"
        ));
    }
    Ok(())
}

fn validate_gps(value: &str) -> Result<(), String> {
    if value.chars().count() > MAX_GPS_CHARS {
        return Err(format!("gps_coords excede {MAX_GPS_CHARS} caracteres"));
    }
    let parts: Vec<&str> = value.split(',').collect();
    if parts.len() != 2 {
        return Err("gps_coords deve estar no formato 'lat,lon'".to_string());
    }
    let lat: f64 = parts[0]
        .trim()
        .parse()
        .map_err(|_| "gps_coords com latitude inválida".to_string())?;
    let lon: f64 = parts[1]
        .trim()
        .parse()
        .map_err(|_| "gps_coords com longitude inválida".to_string())?;
    if !lat.is_finite() || !lon.is_finite() {
        return Err("gps_coords deve conter números finitos".to_string());
    }
    if !(-90.0..=90.0).contains(&lat) {
        return Err("gps_coords com latitude fora de -90..90".to_string());
    }
    if !(-180.0..=180.0).contains(&lon) {
        return Err("gps_coords com longitude fora de -180..180".to_string());
    }
    Ok(())
}

fn is_hex(value: &str, expected_len: usize) -> bool {
    value.len() == expected_len && value.bytes().all(|b| b.is_ascii_hexdigit())
}

fn hex_decode(value: &str) -> Option<Vec<u8>> {
    if !value.len().is_multiple_of(2) {
        return None;
    }
    let bytes = value.as_bytes();
    let mut out = Vec::with_capacity(bytes.len() / 2);
    let mut i = 0;
    while i < bytes.len() {
        let hi = hex_val(bytes[i])?;
        let lo = hex_val(bytes[i + 1])?;
        out.push((hi << 4) | lo);
        i += 2;
    }
    Some(out)
}

fn hex_val(byte: u8) -> Option<u8> {
    match byte {
        b'0'..=b'9' => Some(byte - b'0'),
        b'a'..=b'f' => Some(byte - b'a' + 10),
        b'A'..=b'F' => Some(byte - b'A' + 10),
        _ => None,
    }
}

fn hex_encode(bytes: &[u8]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut out = String::with_capacity(bytes.len() * 2);
    for &byte in bytes {
        out.push(HEX[(byte >> 4) as usize] as char);
        out.push(HEX[(byte & 0x0f) as usize] as char);
    }
    out
}

fn sha256_hex(bytes: &[u8]) -> String {
    let digest = Sha256::digest(bytes);
    hex_encode(&digest[..])
}

/// HMAC-SHA256 (RFC 2104) construído sobre o crate `sha2`.
fn hmac_sha256(key: &[u8], message: &[u8]) -> [u8; 32] {
    const BLOCK: usize = 64;
    let mut key_block = [0u8; BLOCK];
    if key.len() > BLOCK {
        let digest = Sha256::digest(key);
        key_block[..32].copy_from_slice(&digest[..]);
    } else {
        key_block[..key.len()].copy_from_slice(key);
    }

    let mut ipad = [0u8; BLOCK];
    let mut opad = [0u8; BLOCK];
    for i in 0..BLOCK {
        ipad[i] = key_block[i] ^ 0x36;
        opad[i] = key_block[i] ^ 0x5c;
    }

    let mut inner = Sha256::new();
    inner.update(ipad);
    inner.update(message);
    let inner_digest = inner.finalize();

    let mut outer = Sha256::new();
    outer.update(opad);
    outer.update(&inner_digest[..]);
    let outer_digest = outer.finalize();

    let mut tag = [0u8; 32];
    tag.copy_from_slice(&outer_digest[..]);
    tag
}

fn constant_time_eq(left: &[u8], right: &[u8]) -> bool {
    if left.len() != right.len() {
        return false;
    }
    let mut diff = 0u8;
    for (a, b) in left.iter().zip(right.iter()) {
        diff |= a ^ b;
    }
    diff == 0
}

/// Serialização canônica com prefixo de tamanho para nome e valor.
///
/// A ordem dos campos é fixa. O campo `signature_hmac_sha256` não participa.
/// Os digests usados são os **calculados** sobre os arquivos, não os
/// declarados pelo chamador.
fn canonical_payload(req: &BreakGlassRequest, camera_sha256: &str, audio_sha256: &str) -> Vec<u8> {
    let mut out = Vec::new();
    out.extend_from_slice(b"KAIROS-BREAK-GLASS-V1");
    push_field(&mut out, "event_id", req.event_id.as_bytes());
    push_field(&mut out, "request_id", req.request_id.as_bytes());
    push_field(&mut out, "emitter_id", req.emitter_id.as_bytes());
    push_field(&mut out, "subject_id", req.subject_id.as_bytes());
    push_field(
        &mut out,
        "timestamp_unix",
        req.timestamp_unix.to_string().as_bytes(),
    );
    push_field(&mut out, "nonce", req.nonce.as_bytes());
    push_field(&mut out, "key_id", req.key_id.as_bytes());
    push_field(&mut out, "camera_file", req.camera_file.as_bytes());
    push_field(
        &mut out,
        "camera_media_type",
        req.camera_media_type.as_bytes(),
    );
    push_field(&mut out, "camera_sha256", camera_sha256.as_bytes());
    push_field(&mut out, "audio_file", req.audio_file.as_bytes());
    push_field(
        &mut out,
        "audio_media_type",
        req.audio_media_type.as_bytes(),
    );
    push_field(&mut out, "audio_sha256", audio_sha256.as_bytes());
    push_field(
        &mut out,
        "gps_present",
        if req.gps_coords.is_some() { b"1" } else { b"0" },
    );
    if let Some(gps) = &req.gps_coords {
        push_field(&mut out, "gps_coords", gps.as_bytes());
    }
    push_field(&mut out, "justificativa", req.justificativa.as_bytes());
    out
}

fn push_field(out: &mut Vec<u8>, name: &str, value: &[u8]) {
    out.extend_from_slice(&(name.len() as u64).to_be_bytes());
    out.extend_from_slice(name.as_bytes());
    out.extend_from_slice(&(value.len() as u64).to_be_bytes());
    out.extend_from_slice(value);
}

fn validate_timestamp(timestamp: i64, now: i64) -> Result<(), BreakGlassError> {
    if timestamp <= 0 {
        return Err(BreakGlassError::InvalidEvidence(
            "timestamp inválido".to_string(),
        ));
    }
    let min = now.saturating_sub(MAX_CLOCK_SKEW_SECS);
    let max = now.saturating_add(MAX_CLOCK_SKEW_SECS);
    if timestamp < min || timestamp > max {
        return Err(BreakGlassError::InvalidEvidence(format!(
            "timestamp fora da janela de {MAX_CLOCK_SKEW_SECS}s"
        )));
    }
    Ok(())
}

fn validate_dir(path: &Path, owner_only: bool, label: &str) -> Result<(), BreakGlassError> {
    let meta = fs::symlink_metadata(path)
        .map_err(|_| BreakGlassError::Unavailable(format!("{label} indisponível")))?;
    if meta.file_type().is_symlink() || !meta.is_dir() {
        return Err(BreakGlassError::Unavailable(format!("{label} inválido")));
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let forbidden: u32 = if owner_only { 0o077 } else { 0o022 };
        if meta.permissions().mode() & forbidden != 0 {
            return Err(BreakGlassError::Unavailable(format!(
                "{label} com permissões inseguras"
            )));
        }
    }
    #[cfg(not(unix))]
    let _ = owner_only;
    Ok(())
}

fn read_private_file(path: &Path, max_bytes: u64, label: &str) -> Result<Vec<u8>, BreakGlassError> {
    let pre = fs::symlink_metadata(path)
        .map_err(|_| BreakGlassError::AuthenticationUnavailable(format!("{label} indisponível")))?;
    if pre.file_type().is_symlink() || !pre.is_file() {
        return Err(BreakGlassError::AuthenticationUnavailable(format!(
            "{label} inválido"
        )));
    }
    if pre.len() == 0 || pre.len() > max_bytes {
        return Err(BreakGlassError::AuthenticationUnavailable(format!(
            "{label} com tamanho inválido"
        )));
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        if pre.permissions().mode() & 0o077 != 0 {
            return Err(BreakGlassError::AuthenticationUnavailable(format!(
                "{label} com permissões inseguras"
            )));
        }
    }

    let file = File::open(path)
        .map_err(|_| BreakGlassError::AuthenticationUnavailable(format!("{label} indisponível")))?;
    let post = file
        .metadata()
        .map_err(|_| BreakGlassError::AuthenticationUnavailable(format!("{label} indisponível")))?;
    if !post.is_file() || post.len() != pre.len() {
        return Err(BreakGlassError::AuthenticationUnavailable(format!(
            "{label} mudou durante a leitura"
        )));
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        if post.dev() != pre.dev() || post.ino() != pre.ino() {
            return Err(BreakGlassError::AuthenticationUnavailable(format!(
                "{label} mudou durante a leitura"
            )));
        }
    }

    let mut bytes = Vec::new();
    let mut limited = file.take(max_bytes);
    limited
        .read_to_end(&mut bytes)
        .map_err(|_| BreakGlassError::AuthenticationUnavailable(format!("{label} ilegível")))?;
    if bytes.len() as u64 != pre.len() {
        return Err(BreakGlassError::AuthenticationUnavailable(format!(
            "{label} mudou durante a leitura"
        )));
    }
    Ok(bytes)
}

fn hash_evidence_file(
    config: &BreakGlassConfig,
    file_name: &str,
    media_type: &str,
    label: &str,
) -> Result<String, BreakGlassError> {
    validate_dir(&config.evidence_dir, false, "diretório de evidências")?;
    let path = config.evidence_dir.join(file_name);

    let pre = fs::symlink_metadata(&path)
        .map_err(|_| BreakGlassError::InvalidEvidence(format!("{label} indisponível")))?;
    if pre.file_type().is_symlink() || !pre.is_file() {
        return Err(BreakGlassError::InvalidEvidence(format!(
            "{label} inválida"
        )));
    }
    if pre.len() == 0 || pre.len() > MAX_EVIDENCE_BYTES {
        return Err(BreakGlassError::InvalidEvidence(format!(
            "{label} com tamanho inválido"
        )));
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        if pre.permissions().mode() & 0o022 != 0 {
            return Err(BreakGlassError::InvalidEvidence(format!(
                "{label} com permissões inseguras"
            )));
        }
    }

    let file = File::open(&path)
        .map_err(|_| BreakGlassError::InvalidEvidence(format!("{label} indisponível")))?;
    let post = file
        .metadata()
        .map_err(|_| BreakGlassError::InvalidEvidence(format!("{label} indisponível")))?;
    if !post.is_file() || post.len() != pre.len() {
        return Err(BreakGlassError::InvalidEvidence(format!(
            "{label} mudou durante a leitura"
        )));
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        if post.dev() != pre.dev() || post.ino() != pre.ino() {
            return Err(BreakGlassError::InvalidEvidence(format!(
                "{label} mudou durante a leitura"
            )));
        }
    }

    let mut reader = BufReader::new(file);
    let mut hasher = Sha256::new();
    let mut prefix = Vec::with_capacity(12);
    let mut buf = [0u8; 64 * 1024];
    let mut total: u64 = 0;
    loop {
        let n = reader
            .read(&mut buf)
            .map_err(|_| BreakGlassError::InvalidEvidence(format!("{label} ilegível")))?;
        if n == 0 {
            break;
        }
        total += n as u64;
        if total > MAX_EVIDENCE_BYTES {
            return Err(BreakGlassError::InvalidEvidence(format!(
                "{label} excede o limite"
            )));
        }
        if prefix.len() < 12 {
            let need = 12 - prefix.len();
            let take = n.min(need);
            prefix.extend_from_slice(&buf[..take]);
        }
        hasher.update(&buf[..n]);
    }

    if total != pre.len() {
        return Err(BreakGlassError::InvalidEvidence(format!(
            "{label} mudou durante a leitura"
        )));
    }
    if !media_magic_ok(media_type, &prefix) {
        return Err(BreakGlassError::InvalidEvidence(format!(
            "{label} com formato inválido"
        )));
    }

    let digest = hasher.finalize();
    Ok(hex_encode(&digest[..]))
}

fn media_magic_ok(media_type: &str, prefix: &[u8]) -> bool {
    match media_type {
        "jpeg" => prefix.starts_with(&[0xff, 0xd8, 0xff]),
        "png" => prefix.starts_with(&[0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
        "mp4" => prefix.len() >= 8 && &prefix[4..8] == b"ftyp",
        "wav" => prefix.len() >= 12 && &prefix[0..4] == b"RIFF" && &prefix[8..12] == b"WAVE",
        "mp3" => {
            prefix.len() >= 3
                && (prefix.starts_with(b"ID3") || (prefix[0] == 0xff && (prefix[1] & 0xe0) == 0xe0))
        }
        "ogg" => prefix.starts_with(b"OggS"),
        _ => false,
    }
}

fn load_key(
    config: &BreakGlassConfig,
    req: &BreakGlassRequest,
) -> Result<[u8; 32], BreakGlassError> {
    validate_dir(&config.key_dir, true, "diretório de chaves")?;

    let key_path = config.key_dir.join(format!("{}.key", req.key_id));
    let key_bytes = read_private_file(&key_path, 256, "chave")?;
    let key_text = std::str::from_utf8(&key_bytes)
        .map_err(|_| BreakGlassError::Authentication("chave não é UTF-8".to_string()))?;
    let key_hex = key_text.trim();
    if !is_hex(key_hex, SHA256_HEX_CHARS) {
        return Err(BreakGlassError::Authentication(
            "chave com formato inválido".to_string(),
        ));
    }
    let decoded = hex_decode(key_hex)
        .ok_or_else(|| BreakGlassError::Authentication("chave inválida".to_string()))?;
    let mut key = [0u8; 32];
    key.copy_from_slice(&decoded);

    let emitter_path = config.key_dir.join(format!("{}.emitter", req.key_id));
    let emitter_bytes = read_private_file(&emitter_path, 256, "vínculo de emissor")?;
    let emitter_text = std::str::from_utf8(&emitter_bytes).map_err(|_| {
        BreakGlassError::AuthenticationUnavailable("vínculo de emissor não é UTF-8".to_string())
    })?;
    let emitter = emitter_text.trim();
    if validate_identifier("emitter_id", emitter, MAX_ID_CHARS).is_err() {
        return Err(BreakGlassError::AuthenticationUnavailable(
            "vínculo de emissor inválido".to_string(),
        ));
    }
    if emitter != req.emitter_id {
        return Err(BreakGlassError::Authentication(
            "emissor não corresponde à chave provisionada".to_string(),
        ));
    }

    Ok(key)
}

fn create_new_state_file(
    path: &Path,
    content: &str,
    max_len: usize,
) -> Result<(), BreakGlassError> {
    if content.len() > max_len {
        return Err(BreakGlassError::Internal(
            "registro de estado excede o limite".to_string(),
        ));
    }

    let mut options = OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }

    match options.open(path) {
        Ok(mut file) => {
            if let Err(error) = file
                .write_all(content.as_bytes())
                .and_then(|_| file.sync_all())
            {
                drop(file);
                let _ = fs::remove_file(path);
                return Err(BreakGlassError::Unavailable(format!(
                    "falha ao registrar estado: {error}"
                )));
            }
            Ok(())
        }
        Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {
            Err(BreakGlassError::Replay("estado já utilizado".to_string()))
        }
        Err(error) => Err(BreakGlassError::Unavailable(format!(
            "falha ao registrar estado: {error}"
        ))),
    }
}

fn read_state_file(path: &Path, max_bytes: u64) -> Result<String, BreakGlassError> {
    let pre = fs::symlink_metadata(path)
        .map_err(|_| BreakGlassError::Internal("estado indisponível".to_string()))?;
    if pre.file_type().is_symlink() || !pre.is_file() || pre.len() > max_bytes {
        return Err(BreakGlassError::Internal("estado inválido".to_string()));
    }
    let file = File::open(path)
        .map_err(|_| BreakGlassError::Internal("estado indisponível".to_string()))?;
    let mut limited = file.take(max_bytes);
    let mut bytes = Vec::new();
    limited
        .read_to_end(&mut bytes)
        .map_err(|_| BreakGlassError::Internal("estado ilegível".to_string()))?;
    String::from_utf8(bytes).map_err(|_| BreakGlassError::Internal("estado inválido".to_string()))
}

fn consume_evidence_binding(
    config: &BreakGlassConfig,
    req: &BreakGlassRequest,
    camera_sha256: &str,
    audio_sha256: &str,
) -> Result<(), BreakGlassError> {
    validate_dir(&config.state_dir, true, "diretório de estado")?;

    let mut combined = Vec::with_capacity(128);
    combined.extend_from_slice(camera_sha256.as_bytes());
    combined.push(0);
    combined.extend_from_slice(audio_sha256.as_bytes());
    let key = sha256_hex(&combined);
    let path = config.state_dir.join(format!("evidence-{key}"));
    let record = format!(
        "{}\n{}\n{}",
        req.event_id, req.request_id, req.timestamp_unix
    );

    match create_new_state_file(&path, &record, 1024) {
        Ok(()) => Ok(()),
        Err(BreakGlassError::Replay(_)) => {
            let existing = read_state_file(&path, 1024)?;
            let first = existing.lines().next().unwrap_or("");
            if first == req.event_id.as_str() {
                Ok(())
            } else {
                Err(BreakGlassError::Replay(
                    "evidência já vinculada a outro evento".to_string(),
                ))
            }
        }
        Err(error) => Err(error),
    }
}

fn consume_nonce(
    config: &BreakGlassConfig,
    req: &BreakGlassRequest,
) -> Result<(), BreakGlassError> {
    validate_dir(&config.state_dir, true, "diretório de estado")?;
    let key = sha256_hex(req.nonce.as_bytes());
    let path = config.state_dir.join(format!("nonce-{key}"));
    let record = format!(
        "{}\n{}\n{}\n{}\n{}",
        req.event_id, req.request_id, req.emitter_id, req.key_id, req.timestamp_unix
    );
    create_new_state_file(&path, &record, 2048).map_err(|error| match error {
        BreakGlassError::Replay(_) => BreakGlassError::Replay("nonce já utilizado".to_string()),
        other => other,
    })
}

fn failure_verdict(
    status: BreakGlassStatus,
    req: Option<&BreakGlassRequest>,
    now: i64,
    reason: impl Into<String>,
) -> BreakGlassVerdict {
    let context = if status == BreakGlassStatus::InvalidInput {
        None
    } else {
        req
    };
    BreakGlassVerdict {
        autorizado: false,
        break_glass_status: status,
        event_id: context.map(|r| r.event_id.clone()),
        request_id: context.map(|r| r.request_id.clone()),
        emitter_id: context.map(|r| r.emitter_id.clone()),
        subject_id: context.map(|r| r.subject_id.clone()),
        key_id: context.map(|r| r.key_id.clone()),
        timestamp_unix: context.map(|r| r.timestamp_unix).unwrap_or(0),
        server_timestamp_unix: now,
        camera_sha256: None,
        audio_sha256: None,
        gps_coords: context.and_then(|r| r.gps_coords.clone()),
        gps_provenance: if context.and_then(|r| r.gps_coords.as_ref()).is_some() {
            "declared_metadata_unauthenticated".to_string()
        } else {
            "not_provided".to_string()
        },
        nonce: context.map(|r| r.nonce.clone()),
        signature_algorithm: "HMAC-SHA256".to_string(),
        signature_verified: false,
        nonce_consumed: false,
        evidence_digest: String::new(),
        selo_criptografico: String::new(),
        motivo_recusa: Some(reason.into()),
    }
}

fn success_verdict(
    req: &BreakGlassRequest,
    now: i64,
    camera_sha256: String,
    audio_sha256: String,
    evidence_digest: String,
    signature: [u8; 32],
) -> BreakGlassVerdict {
    BreakGlassVerdict {
        autorizado: true,
        break_glass_status: BreakGlassStatus::Authorized,
        event_id: Some(req.event_id.clone()),
        request_id: Some(req.request_id.clone()),
        emitter_id: Some(req.emitter_id.clone()),
        subject_id: Some(req.subject_id.clone()),
        key_id: Some(req.key_id.clone()),
        timestamp_unix: req.timestamp_unix,
        server_timestamp_unix: now,
        camera_sha256: Some(camera_sha256),
        audio_sha256: Some(audio_sha256),
        gps_coords: req.gps_coords.clone(),
        gps_provenance: if req.gps_coords.is_some() {
            "declared_metadata_unauthenticated".to_string()
        } else {
            "not_provided".to_string()
        },
        nonce: Some(req.nonce.clone()),
        signature_algorithm: "HMAC-SHA256".to_string(),
        signature_verified: true,
        nonce_consumed: true,
        evidence_digest,
        selo_criptografico: hex_encode(&signature),
        motivo_recusa: None,
    }
}

/// Avalia o Break Glass com um horário fixo. Usado por testes e pelo wrapper.
pub fn evaluate_at(
    req: &BreakGlassRequest,
    now: i64,
    config: &BreakGlassConfig,
) -> BreakGlassVerdict {
    if let Err(reason) = validate_request(req) {
        return failure_verdict(BreakGlassStatus::InvalidInput, None, now, reason);
    }

    if let Err(error) = validate_timestamp(req.timestamp_unix, now) {
        return failure_verdict(error.status(), Some(req), now, error.reason());
    }

    let key = match load_key(config, req) {
        Ok(key) => key,
        Err(error) => return failure_verdict(error.status(), Some(req), now, error.reason()),
    };

    let camera_sha256 =
        match hash_evidence_file(config, &req.camera_file, &req.camera_media_type, "câmera") {
            Ok(digest) => digest,
            Err(error) => return failure_verdict(error.status(), Some(req), now, error.reason()),
        };
    let audio_sha256 =
        match hash_evidence_file(config, &req.audio_file, &req.audio_media_type, "áudio") {
            Ok(digest) => digest,
            Err(error) => return failure_verdict(error.status(), Some(req), now, error.reason()),
        };

    if !req.camera_sha256.eq_ignore_ascii_case(&camera_sha256) {
        return failure_verdict(
            BreakGlassStatus::IntegrityFailure,
            Some(req),
            now,
            "digest da câmera divergente",
        );
    }
    if !req.audio_sha256.eq_ignore_ascii_case(&audio_sha256) {
        return failure_verdict(
            BreakGlassStatus::IntegrityFailure,
            Some(req),
            now,
            "digest do áudio divergente",
        );
    }

    let canonical = canonical_payload(req, &camera_sha256, &audio_sha256);
    let expected_signature = hmac_sha256(&key, &canonical);
    let provided_signature = match hex_decode(&req.signature_hmac_sha256) {
        Some(signature) if signature.len() == 32 => signature,
        _ => {
            return failure_verdict(
                BreakGlassStatus::AuthenticationFailure,
                Some(req),
                now,
                "assinatura HMAC inválida",
            )
        }
    };
    if !constant_time_eq(&expected_signature, &provided_signature) {
        return failure_verdict(
            BreakGlassStatus::AuthenticationFailure,
            Some(req),
            now,
            "assinatura HMAC inválida",
        );
    }

    let evidence_digest = sha256_hex(&canonical);

    if let Err(error) = consume_evidence_binding(config, req, &camera_sha256, &audio_sha256) {
        return failure_verdict(error.status(), Some(req), now, error.reason());
    }
    if let Err(error) = consume_nonce(config, req) {
        return failure_verdict(error.status(), Some(req), now, error.reason());
    }

    success_verdict(
        req,
        now,
        camera_sha256,
        audio_sha256,
        evidence_digest,
        expected_signature,
    )
}

/// Avalia o Break Glass usando o relógio do sistema e a configuração de ambiente.
pub fn evaluate_break_glass(req: &BreakGlassRequest) -> BreakGlassVerdict {
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_secs() as i64)
        .unwrap_or(0);

    if let Err(reason) = validate_request(req) {
        return failure_verdict(BreakGlassStatus::InvalidInput, None, now, reason);
    }

    match BreakGlassConfig::from_env() {
        Ok(config) => evaluate_at(req, now, &config),
        Err(error) => failure_verdict(error.status(), Some(req), now, error.reason()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    use std::sync::atomic::{AtomicU64, Ordering};

    static TEST_COUNTER: AtomicU64 = AtomicU64::new(0);

    fn test_key(seed: u8) -> [u8; 32] {
        let nanos = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let mut material = Vec::new();
        material.extend_from_slice(&nanos.to_be_bytes());
        material.extend_from_slice(&std::process::id().to_be_bytes());
        material.push(seed);
        let digest = Sha256::digest(&material);
        let mut key = [0u8; 32];
        key.copy_from_slice(&digest[..]);
        key
    }

    struct TestEnv {
        root: PathBuf,
        config: BreakGlassConfig,
        key: [u8; 32],
    }

    impl TestEnv {
        fn new(label: &str) -> Self {
            let counter = TEST_COUNTER.fetch_add(1, Ordering::Relaxed);
            let nanos = SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .as_nanos();
            let root = env::temp_dir().join(format!(
                "kairos_bg_{label}_{}_{}_{}",
                std::process::id(),
                nanos,
                counter
            ));
            let key_dir = root.join("keys");
            let evidence_dir = root.join("evidence");
            let state_dir = root.join("state");
            fs::create_dir_all(&key_dir).unwrap();
            fs::create_dir_all(&evidence_dir).unwrap();
            fs::create_dir_all(&state_dir).unwrap();
            set_mode(&root, 0o700);
            set_mode(&key_dir, 0o700);
            set_mode(&evidence_dir, 0o700);
            set_mode(&state_dir, 0o700);

            let env = Self {
                root,
                config: BreakGlassConfig {
                    key_dir,
                    evidence_dir,
                    state_dir,
                },
                key: test_key(0x42),
            };
            env.write_key("key-test", "device-A", &env.key);
            env.write_evidence("camera.jpg", b"\xff\xd8\xff\xe0camera-evidence");
            env.write_evidence("audio.wav", b"RIFF\x00\x00\x00\x00WAVEaudio-evidence");
            env
        }

        fn write_key(&self, key_id: &str, emitter: &str, key: &[u8; 32]) {
            let key_path = self.config.key_dir.join(format!("{key_id}.key"));
            let emitter_path = self.config.key_dir.join(format!("{key_id}.emitter"));
            fs::write(&key_path, format!("{}\n", hex_encode(key))).unwrap();
            fs::write(&emitter_path, format!("{emitter}\n")).unwrap();
            set_mode(&key_path, 0o600);
            set_mode(&emitter_path, 0o600);
        }

        fn write_evidence(&self, name: &str, bytes: &[u8]) {
            let path = self.config.evidence_dir.join(name);
            fs::write(&path, bytes).unwrap();
            set_mode(&path, 0o600);
        }

        fn request(
            &self,
            event_id: &str,
            request_id: &str,
            nonce: &str,
            timestamp: i64,
        ) -> BreakGlassRequest {
            self.request_with_files(
                event_id,
                request_id,
                nonce,
                timestamp,
                "camera.jpg",
                "audio.wav",
            )
        }

        fn request_with_files(
            &self,
            event_id: &str,
            request_id: &str,
            nonce: &str,
            timestamp: i64,
            camera_file: &str,
            audio_file: &str,
        ) -> BreakGlassRequest {
            let camera_bytes = fs::read(self.config.evidence_dir.join(camera_file)).unwrap();
            let audio_bytes = fs::read(self.config.evidence_dir.join(audio_file)).unwrap();
            let mut req = BreakGlassRequest {
                event_id: event_id.to_string(),
                request_id: request_id.to_string(),
                emitter_id: "device-A".to_string(),
                subject_id: "user-1".to_string(),
                timestamp_unix: timestamp,
                nonce: nonce.to_string(),
                key_id: "key-test".to_string(),
                camera_file: camera_file.to_string(),
                camera_media_type: "jpeg".to_string(),
                camera_sha256: sha256_hex(&camera_bytes),
                audio_file: audio_file.to_string(),
                audio_media_type: "wav".to_string(),
                audio_sha256: sha256_hex(&audio_bytes),
                gps_coords: Some("-23.55,-46.63".to_string()),
                justificativa: "emergência médica".to_string(),
                signature_hmac_sha256: "0".repeat(64),
            };
            let canonical = canonical_payload(&req, &req.camera_sha256, &req.audio_sha256);
            req.signature_hmac_sha256 = hex_encode(&hmac_sha256(&self.key, &canonical));
            req
        }
    }

    impl Drop for TestEnv {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.root);
        }
    }

    fn set_mode(path: &Path, mode: u32) {
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            fs::set_permissions(path, fs::Permissions::from_mode(mode)).unwrap();
        }
        #[cfg(not(unix))]
        {
            let _ = (path, mode);
        }
    }

    fn assert_status(verdict: &BreakGlassVerdict, status: BreakGlassStatus) {
        assert_eq!(
            verdict.break_glass_status, status,
            "motivo: {:?}",
            verdict.motivo_recusa
        );
    }

    fn nonce(suffix: &str) -> String {
        format!("nonce-{suffix}-0123456789abcdef")
    }

    #[test]
    fn hmac_sha256_vetor_rfc4231() {
        let key = [0x0b; 20];
        let tag = hmac_sha256(&key, b"Hi There");
        assert_eq!(
            hex_encode(&tag),
            "b0344c61d8db38535ca8afceaf0bf12b881dc200c9833da726e9376c2e32cff7"
        );
    }

    #[test]
    fn serializacao_canonica_nao_e_ambigua() {
        let env = TestEnv::new("canonical");
        let now = 1_700_000_000;
        let mut a = env.request("ab", "c", &nonce("a"), now);
        let mut b = env.request("a", "bc", &nonce("b"), now);
        a.signature_hmac_sha256 = "0".repeat(64);
        b.signature_hmac_sha256 = "0".repeat(64);
        assert_ne!(
            canonical_payload(&a, &a.camera_sha256, &a.audio_sha256),
            canonical_payload(&b, &b.camera_sha256, &b.audio_sha256)
        );
    }

    #[test]
    fn autoriza_evidencia_valida() {
        let env = TestEnv::new("valid");
        let now = 1_700_000_000;
        let req = env.request("evt-1", "req-1", &nonce("valid"), now);
        let verdict = evaluate_at(&req, now, &env.config);
        assert_status(&verdict, BreakGlassStatus::Authorized);
        assert!(verdict.autorizado);
        assert!(verdict.signature_verified);
        assert!(verdict.nonce_consumed);
        assert_eq!(verdict.selo_criptografico.len(), 64);
        assert_eq!(verdict.evidence_digest.len(), 64);
        assert_eq!(verdict.subject_id.as_deref(), Some("user-1"));
        assert_eq!(verdict.gps_provenance, "declared_metadata_unauthenticated");
    }

    #[test]
    fn rejeita_entrada_invalida() {
        let env = TestEnv::new("invalid");
        let now = 1_700_000_000;
        let mut req = env.request("evt-1", "req-1", &nonce("invalid"), now);
        req.event_id = String::new();
        assert_status(
            &evaluate_at(&req, now, &env.config),
            BreakGlassStatus::InvalidInput,
        );

        let mut req = env.request("evt-1", "req-1", &nonce("invalid-subject"), now);
        req.subject_id = String::new();
        assert_status(
            &evaluate_at(&req, now, &env.config),
            BreakGlassStatus::InvalidInput,
        );

        let mut req = env.request("evt-1", "req-1", &nonce("invalid2"), now);
        req.camera_sha256 = "xyz".to_string();
        assert_status(
            &evaluate_at(&req, now, &env.config),
            BreakGlassStatus::InvalidInput,
        );

        let mut req = env.request("evt-1", "req-1", &nonce("invalid3"), now);
        req.gps_coords = Some("200,0".to_string());
        assert_status(
            &evaluate_at(&req, now, &env.config),
            BreakGlassStatus::InvalidInput,
        );
    }

    #[test]
    fn rejeita_campos_ausentes_ou_desconhecidos_no_serde() {
        let env = TestEnv::new("serde");
        let now = 1_700_000_000;
        let req = env.request("evt-1", "req-1", &nonce("serde"), now);
        let mut value = serde_json::to_value(&req).unwrap();
        value.as_object_mut().unwrap().remove("camera_file");
        assert!(serde_json::from_value::<BreakGlassRequest>(value).is_err());

        let mut value = serde_json::to_value(&req).unwrap();
        value
            .as_object_mut()
            .unwrap()
            .insert("extra".to_string(), json!(1));
        assert!(serde_json::from_value::<BreakGlassRequest>(value).is_err());
    }

    #[test]
    fn rejeita_timestamp_fora_da_janela() {
        let env = TestEnv::new("timestamp");
        let now = 1_700_000_000;
        let old = env.request("evt-1", "req-1", &nonce("old"), now - 3600);
        assert_status(
            &evaluate_at(&old, now, &env.config),
            BreakGlassStatus::InvalidEvidence,
        );
        let future = env.request("evt-1", "req-1", &nonce("future"), now + 3600);
        assert_status(
            &evaluate_at(&future, now, &env.config),
            BreakGlassStatus::InvalidEvidence,
        );
    }

    #[test]
    fn rejeita_digest_divergente_apos_alteracao() {
        let env = TestEnv::new("integrity");
        let now = 1_700_000_000;
        let req = env.request("evt-1", "req-1", &nonce("integrity"), now);
        env.write_evidence("camera.jpg", b"\xff\xd8\xff\xe0camera-alterada");
        assert_status(
            &evaluate_at(&req, now, &env.config),
            BreakGlassStatus::IntegrityFailure,
        );
    }

    #[test]
    fn rejeita_digest_declarado_incorreto() {
        let env = TestEnv::new("declared");
        let now = 1_700_000_000;
        let mut req = env.request("evt-1", "req-1", &nonce("declared"), now);
        req.camera_sha256 = "0".repeat(64);
        assert_status(
            &evaluate_at(&req, now, &env.config),
            BreakGlassStatus::IntegrityFailure,
        );
    }

    #[test]
    fn rejeita_arquivo_ausente_vazio_ou_formato_invalido() {
        let env = TestEnv::new("file");
        let now = 1_700_000_000;
        let req = env.request("evt-1", "req-1", &nonce("file"), now);
        fs::remove_file(env.config.evidence_dir.join("camera.jpg")).unwrap();
        assert_status(
            &evaluate_at(&req, now, &env.config),
            BreakGlassStatus::InvalidEvidence,
        );

        env.write_evidence("camera.jpg", b"");
        assert_status(
            &evaluate_at(&req, now, &env.config),
            BreakGlassStatus::InvalidEvidence,
        );

        env.write_evidence("camera.jpg", b"not-an-image");
        assert_status(
            &evaluate_at(&req, now, &env.config),
            BreakGlassStatus::InvalidEvidence,
        );
    }

    #[test]
    fn rejeita_arquivo_truncado() {
        let env = TestEnv::new("truncated");
        let now = 1_700_000_000;
        let req = env.request("evt-1", "req-1", &nonce("truncated"), now);
        env.write_evidence("camera.jpg", b"\xff\xd8\xff");
        assert_status(
            &evaluate_at(&req, now, &env.config),
            BreakGlassStatus::IntegrityFailure,
        );
    }

    #[test]
    fn rejeita_arquivo_acima_do_limite() {
        let env = TestEnv::new("oversize");
        let now = 1_700_000_000;
        let req = env.request("evt-1", "req-1", &nonce("oversize"), now);
        let path = env.config.evidence_dir.join("camera.jpg");
        let file = File::create(&path).unwrap();
        file.set_len(MAX_EVIDENCE_BYTES + 1).unwrap();
        set_mode(&path, 0o600);
        assert_status(
            &evaluate_at(&req, now, &env.config),
            BreakGlassStatus::InvalidEvidence,
        );
    }

    #[test]
    fn rejeita_assinatura_invalida() {
        let env = TestEnv::new("signature");
        let now = 1_700_000_000;
        let mut req = env.request("evt-1", "req-1", &nonce("signature"), now);
        req.signature_hmac_sha256 = "0".repeat(64);
        assert_status(
            &evaluate_at(&req, now, &env.config),
            BreakGlassStatus::AuthenticationFailure,
        );
    }

    #[test]
    fn rejeita_chave_ausente() {
        let env = TestEnv::new("nokey");
        let now = 1_700_000_000;
        let mut req = env.request("evt-1", "req-1", &nonce("nokey"), now);
        req.key_id = "missing".to_string();
        assert_status(
            &evaluate_at(&req, now, &env.config),
            BreakGlassStatus::AuthenticationUnavailable,
        );
    }

    #[test]
    fn rejeita_emissor_desconhecido_ou_sem_vinculo() {
        let env = TestEnv::new("emitter");
        let now = 1_700_000_000;
        let mut req = env.request("evt-1", "req-1", &nonce("emitter"), now);
        req.emitter_id = "device-B".to_string();
        let canonical = canonical_payload(&req, &req.camera_sha256, &req.audio_sha256);
        req.signature_hmac_sha256 = hex_encode(&hmac_sha256(&env.key, &canonical));
        assert_status(
            &evaluate_at(&req, now, &env.config),
            BreakGlassStatus::AuthenticationFailure,
        );

        let req = env.request("evt-1", "req-1", &nonce("emitter2"), now);
        fs::remove_file(env.config.key_dir.join("key-test.emitter")).unwrap();
        assert_status(
            &evaluate_at(&req, now, &env.config),
            BreakGlassStatus::AuthenticationUnavailable,
        );
    }

    #[cfg(unix)]
    #[test]
    fn rejeita_permissoes_inseguras_da_chave() {
        let env = TestEnv::new("permissions");
        let now = 1_700_000_000;
        let req = env.request("evt-1", "req-1", &nonce("permissions"), now);
        set_mode(&env.config.key_dir.join("key-test.key"), 0o644);
        assert_status(
            &evaluate_at(&req, now, &env.config),
            BreakGlassStatus::AuthenticationUnavailable,
        );
    }

    #[test]
    fn detecta_replay_de_nonce() {
        let env = TestEnv::new("replay");
        let now = 1_700_000_000;
        let req = env.request("evt-1", "req-1", &nonce("replay"), now);
        assert_status(
            &evaluate_at(&req, now, &env.config),
            BreakGlassStatus::Authorized,
        );
        assert_status(
            &evaluate_at(&req, now, &env.config),
            BreakGlassStatus::ReplayDetected,
        );
    }

    #[test]
    fn detecta_reuso_de_evidencia_em_outro_evento() {
        let env = TestEnv::new("evidence-reuse");
        let now = 1_700_000_000;
        let first = env.request("evt-1", "req-1", &nonce("reuse1"), now);
        assert_status(
            &evaluate_at(&first, now, &env.config),
            BreakGlassStatus::Authorized,
        );
        let second = env.request("evt-2", "req-2", &nonce("reuse2"), now);
        assert_status(
            &evaluate_at(&second, now, &env.config),
            BreakGlassStatus::ReplayDetected,
        );
    }

    #[test]
    fn permite_retry_do_mesmo_evento_com_novo_nonce() {
        let env = TestEnv::new("retry");
        let now = 1_700_000_000;
        let first = env.request("evt-1", "req-1", &nonce("retry1"), now);
        assert_status(
            &evaluate_at(&first, now, &env.config),
            BreakGlassStatus::Authorized,
        );
        let second = env.request("evt-1", "req-2", &nonce("retry2"), now);
        assert_status(
            &evaluate_at(&second, now, &env.config),
            BreakGlassStatus::Authorized,
        );
    }

    #[test]
    fn autoriza_com_rotacao_de_chave() {
        let env = TestEnv::new("rotation");
        let now = 1_700_000_000;
        let new_key = test_key(0x77);
        env.write_key("key-2", "device-A", &new_key);
        let mut req = env.request("evt-1", "req-1", &nonce("rotation"), now);
        req.key_id = "key-2".to_string();
        let canonical = canonical_payload(&req, &req.camera_sha256, &req.audio_sha256);
        req.signature_hmac_sha256 = hex_encode(&hmac_sha256(&new_key, &canonical));
        assert_status(
            &evaluate_at(&req, now, &env.config),
            BreakGlassStatus::Authorized,
        );
    }

    #[test]
    fn falha_sem_diretorio_de_estado() {
        let env = TestEnv::new("nostate");
        let now = 1_700_000_000;
        let req = env.request("evt-1", "req-1", &nonce("nostate"), now);
        let config = BreakGlassConfig {
            key_dir: env.config.key_dir.clone(),
            evidence_dir: env.config.evidence_dir.clone(),
            state_dir: env.root.join("missing-state"),
        };
        assert_status(
            &evaluate_at(&req, now, &config),
            BreakGlassStatus::Unavailable,
        );
    }

    #[test]
    fn rejeita_justificativa_com_controle() {
        let env = TestEnv::new("control");
        let now = 1_700_000_000;
        let mut req = env.request("evt-1", "req-1", &nonce("control"), now);
        req.justificativa = "linha\nquebrada".to_string();
        assert_status(
            &evaluate_at(&req, now, &env.config),
            BreakGlassStatus::InvalidInput,
        );
    }
}
