//! Protocolo Break Glass - Botão de Pânico.
//!
//! Quando o Hard Block do Contrato de Ulisses trava o usuário numa emergência
//! real (ex: cirurgia, sequestro), o humano aciona a quebra de vidro.
//! A máquina deixa de ser Bloqueadora e vira Testemunha. Libera a transação,
//! mas exige um Handshake criptográfico com gravação de câmera, áudio e GPS
//! para criar um álibi judicial inquebrável.

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

#[derive(Debug, Deserialize)]
pub struct CryptoHandshake {
    /// Hash SHA-256 (hex) do frame de câmera capturado no momento da emergência.
    pub camera_hash: Option<String>,
    /// Hash SHA-256 (hex) do trecho de áudio capturado.
    pub audio_hash: Option<String>,
    /// Coordenadas GPS no formato "lat,lon".
    pub gps_coords: Option<String>,
    /// Justificativa textual da emergência dada pelo usuário.
    pub justificativa: String,
}

#[derive(Debug, Serialize)]
pub struct AlibiJudicial {
    pub autorizado: bool,
    pub selo_criptografico: String,
    pub timestamp_unix: i64,
    pub motivo_recusa: Option<String>,
}

/// Ativa o protocolo Break Glass. Exige que os 3 fatores de handshake
/// (câmera, áudio, GPS) estejam presentes - sem isso, a quebra de vidro
/// é recusada e o Hard Block permanece ativo.
pub fn ativar_break_glass(handshake: &CryptoHandshake) -> AlibiJudicial {
    let now = chrono::Utc::now().timestamp();

    let faltando: Vec<&str> = [
        (&handshake.camera_hash, "camera"),
        (&handshake.audio_hash, "audio"),
        (&handshake.gps_coords, "gps"),
    ]
    .iter()
    .filter(|(v, _)| v.is_none())
    .map(|(_, nome)| *nome)
    .collect();

    if !faltando.is_empty() {
        return AlibiJudicial {
            autorizado: false,
            selo_criptografico: String::new(),
            timestamp_unix: now,
            motivo_recusa: Some(format!(
                "Handshake incompleto. Fatores ausentes: {}. \
                Break Glass exige câmera + áudio + GPS simultâneos.",
                faltando.join(", ")
            )),
        };
    }

    // Gerar selo criptográfico único combinando os 3 fatores + timestamp,
    // criando um "álibi judicial inquebrável" (hash determinístico e verificável).
    let payload = format!(
        "{}|{}|{}|{}|{}",
        handshake.camera_hash.as_ref().unwrap(),
        handshake.audio_hash.as_ref().unwrap(),
        handshake.gps_coords.as_ref().unwrap(),
        handshake.justificativa,
        now
    );

    let mut hasher = Sha256::new();
    hasher.update(payload.as_bytes());
    let selo = format!("{:x}", hasher.finalize());

    AlibiJudicial {
        autorizado: true,
        selo_criptografico: selo,
        timestamp_unix: now,
        motivo_recusa: None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn recusa_sem_handshake_completo() {
        let h = CryptoHandshake {
            camera_hash: Some("abc123".to_string()),
            audio_hash: None,
            gps_coords: None,
            justificativa: "emergencia medica".to_string(),
        };
        let alibi = ativar_break_glass(&h);
        assert!(!alibi.autorizado);
    }

    #[test]
    fn autoriza_com_handshake_completo() {
        let h = CryptoHandshake {
            camera_hash: Some("abc123".to_string()),
            audio_hash: Some("def456".to_string()),
            gps_coords: Some("-23.55,-46.63".to_string()),
            justificativa: "sequestro em andamento".to_string(),
        };
        let alibi = ativar_break_glass(&h);
        assert!(alibi.autorizado);
        assert!(!alibi.selo_criptografico.is_empty());
    }
}
