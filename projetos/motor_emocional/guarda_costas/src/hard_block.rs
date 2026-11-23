//! Hard Block - O Contrato de Ulisses.
//!
//! Une o classificador CRUD (Paradoxo do Jornalista) com o nível de estresse
//! vindo do Fígado Virtual/Policy Engine (Python) para decidir se uma ação
//! de Entropia Máxima (Delete) deve ser fisicamente barrada.
//!
//! Este módulo roda em Rust - incorruptível por picos emocionais do Python.
//! Mesmo que o Córtex (LLM) "queira" deixar passar, o Hard Block em Rust
//! é a última linha de defesa a nível de compilação/memória.
//!
//! OS099: entradas inválidas nunca são convertidas em autorização. Se a
//! requisição não puder ser validada, a resposta é `allowed=false` com
//! `blocked_by="invalid_input"`.

use crate::crud_classifier::{classify_action, ActionType};
use serde::{Deserialize, Serialize};
use std::fmt;

/// Limiar de estresse (%) acima do qual uma ação de Delete é fisicamente
/// barrada. Corresponde ao Nível 3 (Break Glass) da Policy Engine 2.0.
const HARD_BLOCK_STRESS_THRESHOLD: f64 = 95.0;

/// Se o usuário for reincidente, o limiar cai para 70% do valor original
/// (mesma lógica de "pavio mais curto" da Policy Engine 2.0 em Python).
const REINCIDENT_PENALTY: f64 = 0.7;

/// Limite de tamanho do identificador, em caracteres Unicode.
const MAX_USER_ID_CHARS: usize = 256;

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct HardBlockRequest {
    pub action: ActionType,
    pub stress_level: f64,
    pub is_reincident: bool,
    pub user_id: String,
}

#[derive(Debug, Serialize)]
pub struct HardBlockResponse {
    pub allowed: bool,
    pub blocked_by: Option<String>,
    pub effective_threshold: f64,
    pub stress_level: f64,
    pub reasoning: String,
}

/// Erros de validação semântica do Hard Block.
///
/// Tipos e formatos básicos (ação, booleano, string, número) são garantidos
/// pelo `serde`; aqui ficam as regras que o JSON sozinho não cobre.
#[derive(Debug, Clone, PartialEq)]
pub enum HardBlockValidationError {
    StressNotFinite,
    StressOutOfRange(f64),
    UserIdEmpty,
    UserIdTooLong(usize),
    UserIdControlCharacter,
    UserIdSurroundingWhitespace,
}

impl fmt::Display for HardBlockValidationError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::StressNotFinite => write!(f, "stress_level não é um número finito"),
            Self::StressOutOfRange(v) => write!(f, "stress_level fora da faixa 0..100: {v}"),
            Self::UserIdEmpty => write!(f, "user_id vazio"),
            Self::UserIdTooLong(n) => write!(
                f,
                "user_id com {n} caracteres; máximo permitido: {MAX_USER_ID_CHARS}"
            ),
            Self::UserIdControlCharacter => {
                write!(f, "user_id contém caractere de controle")
            }
            Self::UserIdSurroundingWhitespace => {
                write!(f, "user_id com espaço no início ou no fim")
            }
        }
    }
}

/// Valida a requisição antes de qualquer decisão de autorização.
pub fn validate_request(req: &HardBlockRequest) -> Result<(), HardBlockValidationError> {
    if !req.stress_level.is_finite() {
        return Err(HardBlockValidationError::StressNotFinite);
    }
    if !(0.0..=100.0).contains(&req.stress_level) {
        return Err(HardBlockValidationError::StressOutOfRange(req.stress_level));
    }
    if req.user_id.trim().is_empty() {
        return Err(HardBlockValidationError::UserIdEmpty);
    }
    if req.user_id != req.user_id.trim() {
        return Err(HardBlockValidationError::UserIdSurroundingWhitespace);
    }
    let chars = req.user_id.chars().count();
    if chars > MAX_USER_ID_CHARS {
        return Err(HardBlockValidationError::UserIdTooLong(chars));
    }
    if req.user_id.chars().any(char::is_control) {
        return Err(HardBlockValidationError::UserIdControlCharacter);
    }
    Ok(())
}

pub fn evaluate_hard_block(req: &HardBlockRequest) -> HardBlockResponse {
    // Fail-closed: uma requisição inválida nunca vira autorização, mesmo que
    // o chamador tenha pulado a validação explícita do CLI.
    if let Err(e) = validate_request(req) {
        return HardBlockResponse {
            allowed: false,
            blocked_by: Some("invalid_input".to_string()),
            effective_threshold: 0.0,
            stress_level: if req.stress_level.is_finite() {
                req.stress_level
            } else {
                0.0
            },
            reasoning: format!("ENTRADA INVÁLIDA: {e}. Operação bloqueada por fail-closed."),
        };
    }

    let verdict = classify_action(req.action);

    // Paradoxo do Jornalista: Create/Read/Update NUNCA são bloqueados,
    // independente do estresse. A "voz" do sistema é sempre livre.
    if !verdict.is_blockable {
        return HardBlockResponse {
            allowed: true,
            blocked_by: None,
            effective_threshold: 100.0,
            stress_level: req.stress_level,
            reasoning: verdict.reasoning,
        };
    }

    // Ação é Delete (Entropia Máxima) - aplicar limiar dinâmico
    let effective_threshold = if req.is_reincident {
        HARD_BLOCK_STRESS_THRESHOLD * REINCIDENT_PENALTY
    } else {
        HARD_BLOCK_STRESS_THRESHOLD
    };

    if req.stress_level >= effective_threshold {
        HardBlockResponse {
            allowed: false,
            blocked_by: Some("hard_block_rust".to_string()),
            effective_threshold,
            stress_level: req.stress_level,
            reasoning: format!(
                "BLOQUEADO: Ação Delete com estresse {:.1}% >= limiar {:.1}% \
                (usuário '{}'{}). Contrato de Ulisses ativo - use Break Glass \
                em caso de emergência real.",
                req.stress_level,
                effective_threshold,
                req.user_id,
                if req.is_reincident {
                    ", REINCIDENTE - limiar reduzido"
                } else {
                    ""
                }
            ),
        }
    } else {
        HardBlockResponse {
            allowed: true,
            blocked_by: None,
            effective_threshold,
            stress_level: req.stress_level,
            reasoning: format!(
                "Permitido: estresse {:.1}% abaixo do limiar {:.1}%.",
                req.stress_level, effective_threshold
            ),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn req(action: ActionType, stress: f64, reincident: bool, user_id: &str) -> HardBlockRequest {
        HardBlockRequest {
            action,
            stress_level: stress,
            is_reincident: reincident,
            user_id: user_id.to_string(),
        }
    }

    #[test]
    fn create_sempre_permitido_mesmo_com_estresse_maximo() {
        let req = HardBlockRequest {
            action: ActionType::Create,
            stress_level: 100.0,
            is_reincident: true,
            user_id: "u1".to_string(),
        };
        let resp = evaluate_hard_block(&req);
        assert!(resp.allowed);
    }

    #[test]
    fn delete_bloqueado_acima_do_limiar() {
        let req = HardBlockRequest {
            action: ActionType::Delete,
            stress_level: 96.0,
            is_reincident: false,
            user_id: "u2".to_string(),
        };
        let resp = evaluate_hard_block(&req);
        assert!(!resp.allowed);
    }

    #[test]
    fn delete_bloqueado_mais_cedo_se_reincidente() {
        let req = HardBlockRequest {
            action: ActionType::Delete,
            stress_level: 68.0, // abaixo do limiar normal, acima do reduzido (66.5)
            is_reincident: true,
            user_id: "u3".to_string(),
        };
        let resp = evaluate_hard_block(&req);
        assert!(!resp.allowed);
        assert_eq!(resp.effective_threshold, 66.5);
    }

    #[test]
    fn delete_permitido_abaixo_do_limiar() {
        let req = HardBlockRequest {
            action: ActionType::Delete,
            stress_level: 50.0,
            is_reincident: false,
            user_id: "u4".to_string(),
        };
        let resp = evaluate_hard_block(&req);
        assert!(resp.allowed);
    }

    #[test]
    fn estresse_nan_e_rejeitado() {
        let r = req(ActionType::Delete, f64::NAN, false, "u1");
        assert_eq!(
            validate_request(&r),
            Err(HardBlockValidationError::StressNotFinite)
        );
        let resp = evaluate_hard_block(&r);
        assert!(!resp.allowed);
        assert_eq!(resp.blocked_by.as_deref(), Some("invalid_input"));
    }

    #[test]
    fn estresse_infinito_positivo_e_negativo_e_rejeitado() {
        for v in [f64::INFINITY, f64::NEG_INFINITY] {
            let r = req(ActionType::Read, v, false, "u1");
            assert_eq!(
                validate_request(&r),
                Err(HardBlockValidationError::StressNotFinite)
            );
            assert!(!evaluate_hard_block(&r).allowed);
        }
    }

    #[test]
    fn estresse_fora_da_faixa_e_rejeitado() {
        for v in [-0.1, 100.1, -50.0, 1_000.0] {
            let r = req(ActionType::Read, v, false, "u1");
            assert!(matches!(
                validate_request(&r),
                Err(HardBlockValidationError::StressOutOfRange(_))
            ));
            assert!(!evaluate_hard_block(&r).allowed);
        }
    }

    #[test]
    fn limites_de_estresse_sao_aceitos() {
        assert!(validate_request(&req(ActionType::Delete, 0.0, false, "u1")).is_ok());
        assert!(validate_request(&req(ActionType::Delete, 100.0, false, "u1")).is_ok());
    }

    #[test]
    fn estresse_no_limite_superior_bloqueia_delete() {
        let resp = evaluate_hard_block(&req(ActionType::Delete, 100.0, false, "u1"));
        assert!(!resp.allowed);
        assert_eq!(resp.effective_threshold, HARD_BLOCK_STRESS_THRESHOLD);
    }

    #[test]
    fn identificador_vazio_ou_malformado_e_rejeitado() {
        let cases = [
            ("", HardBlockValidationError::UserIdEmpty),
            ("   ", HardBlockValidationError::UserIdEmpty),
            (" u1", HardBlockValidationError::UserIdSurroundingWhitespace),
            ("u1 ", HardBlockValidationError::UserIdSurroundingWhitespace),
            (
                "u\u{0000}1",
                HardBlockValidationError::UserIdControlCharacter,
            ),
        ];
        for (user_id, esperado) in cases {
            let r = req(ActionType::Read, 10.0, false, user_id);
            assert_eq!(validate_request(&r), Err(esperado));
            assert!(!evaluate_hard_block(&r).allowed);
        }
    }

    #[test]
    fn identificador_longo_demais_e_rejeitado() {
        let user_id = "a".repeat(MAX_USER_ID_CHARS + 1);
        let r = req(ActionType::Read, 10.0, false, &user_id);
        assert_eq!(
            validate_request(&r),
            Err(HardBlockValidationError::UserIdTooLong(
                MAX_USER_ID_CHARS + 1
            ))
        );
    }

    #[test]
    fn reincidencia_como_string_ou_numero_e_rejeitada_pelo_serde() {
        for valor in [
            json!("true"),
            json!("false"),
            json!(1),
            json!(0),
            json!(null),
        ] {
            let r = serde_json::from_value::<HardBlockRequest>(json!({
                "action": "delete",
                "stress_level": 50.0,
                "is_reincident": valor,
                "user_id": "u1"
            }));
            assert!(r.is_err(), "valor aceito indevidamente: {valor}");
        }
    }

    #[test]
    fn campo_desconhecido_e_rejeitado_pelo_serde() {
        let r = serde_json::from_value::<HardBlockRequest>(json!({
            "action": "delete",
            "stress_level": 50.0,
            "is_reincident": false,
            "user_id": "u1",
            "extra": true
        }));
        assert!(r.is_err());
    }

    #[test]
    fn acao_desconhecida_e_rejeitada_pelo_serde() {
        for valor in [json!("foo"), json!(""), json!(null), json!(1)] {
            let r = serde_json::from_value::<HardBlockRequest>(json!({
                "action": valor,
                "stress_level": 50.0,
                "is_reincident": false,
                "user_id": "u1"
            }));
            assert!(r.is_err(), "ação aceita indevidamente: {valor}");
        }
    }

    #[test]
    fn entrada_invalida_nunca_e_permitida_em_nenhuma_acao() {
        for action in [
            ActionType::Create,
            ActionType::Read,
            ActionType::Update,
            ActionType::Delete,
        ] {
            let r = req(action, f64::NAN, false, "u1");
            assert!(!evaluate_hard_block(&r).allowed);
        }
    }
}
