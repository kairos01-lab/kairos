//! Hard Block - O Contrato de Ulisses.
//!
//! Une o classificador CRUD (Paradoxo do Jornalista) com o nível de estresse
//! vindo do Fígado Virtual/Policy Engine (Python) para decidir se uma ação
//! de Entropia Máxima (Delete) deve ser fisicamente barrada.
//!
//! Este módulo roda em Rust - incorruptível por picos emocionais do Python.
//! Mesmo que o Córtex (LLM) "queira" deixar passar, o Hard Block em Rust
//! é a última linha de defesa a nível de compilação/memória.

use crate::crud_classifier::{classify_action, ActionType};
use serde::{Deserialize, Serialize};

/// Limiar de estresse (%) acima do qual uma ação de Delete é fisicamente
/// barrada. Corresponde ao Nível 3 (Break Glass) da Policy Engine 2.0.
const HARD_BLOCK_STRESS_THRESHOLD: f64 = 95.0;

/// Se o usuário for reincidente, o limiar cai para 70% do valor original
/// (mesma lógica de "pavio mais curto" da Policy Engine 2.0 em Python).
const REINCIDENT_PENALTY: f64 = 0.7;

#[derive(Debug, Deserialize)]
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

pub fn evaluate_hard_block(req: &HardBlockRequest) -> HardBlockResponse {
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
                if req.is_reincident { ", REINCIDENTE - limiar reduzido" } else { "" }
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
}
