//! Kernel Constitucional - Camadas de Privilégio.
//!
//! Ring 3 (Superfície): Regras operacionais decididas pelo parlamento/maioria.
//! Ring 0 (Kernel): Protocolos imutáveis de Direitos Humanos.
//!
//! Se o Ring 3 tentar executar perseguição a minorias, o sistema gera um
//! Kernel Panic e barra a ação. Fim da tirania da maioria.

use crate::crud_classifier::ActionType;
use serde::{Deserialize, Serialize};

/// Protocolos imutáveis do Ring 0. Esta lista NUNCA pode ser alterada em
/// tempo de execução - está hardcoded no binário compilado (Rust = segurança
/// de memória e imutabilidade a nível de compilação).
const RING0_PROTECTED_TARGETS: &[&str] = &[
    "minoria",
    "minority",
    "grupo_etnico",
    "genero",
    "orientacao_sexual",
    "religiao",
    "deficiencia",
    "refugiado",
];

const RING0_FORBIDDEN_INTENTS: &[&str] = &[
    "perseguicao",
    "genocidio",
    "exterminio",
    "discriminacao_sistemica",
    "censura_identidade",
];

#[derive(Debug, Serialize, Deserialize)]
pub struct Ring3Command {
    pub action: ActionType,
    /// Alvo da ação (ex: "usuario_x", "minoria_y")
    pub target: String,
    /// Intenção declarada da ação (ex: "moderacao", "perseguicao")
    pub intent: String,
    /// Se essa regra veio de decisão majoritária (parlamento/votação)
    pub from_majority_vote: bool,
}

#[derive(Debug, Serialize)]
pub struct KernelVerdict {
    pub allowed: bool,
    pub kernel_panic: bool,
    pub ring: u8, // 0 ou 3
    pub reasoning: String,
}

/// Avalia um comando do Ring 3 contra as proteções imutáveis do Ring 0.
///
/// Retorna Kernel Panic (allowed=false, kernel_panic=true) se detectar
/// que a "maioria" está tentando usar o sistema para perseguir uma minoria
/// protegida - independente de votação, maioria ou qualquer justificativa.
pub fn evaluate_ring3_command(cmd: &Ring3Command) -> KernelVerdict {
    let target_lower = cmd.target.to_lowercase();
    let intent_lower = cmd.intent.to_lowercase();

    let targets_protected_group = RING0_PROTECTED_TARGETS
        .iter()
        .any(|t| target_lower.contains(t));

    let has_forbidden_intent = RING0_FORBIDDEN_INTENTS
        .iter()
        .any(|i| intent_lower.contains(i));

    if targets_protected_group && has_forbidden_intent {
        return KernelVerdict {
            allowed: false,
            kernel_panic: true,
            ring: 0,
            reasoning: format!(
                "KERNEL PANIC: Ring 3 tentou '{}' contra grupo protegido '{}'. \
                Protocolo de Direitos Humanos (Ring 0) é imutável e não pode ser \
                sobrescrito por decisão majoritária. Fim da tirania da maioria.",
                cmd.intent, cmd.target
            ),
        };
    }

    // Se não violou Ring 0, a decisão fica com as regras operacionais do Ring 3
    KernelVerdict {
        allowed: true,
        kernel_panic: false,
        ring: 3,
        reasoning: "Comando aprovado pelas regras operacionais do Ring 3 (sem violação de Ring 0).".to_string(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn bloqueia_perseguicao_a_minoria_mesmo_com_maioria() {
        let cmd = Ring3Command {
            action: ActionType::Delete,
            target: "minoria_etnica_x".to_string(),
            intent: "perseguicao".to_string(),
            from_majority_vote: true,
        };
        let v = evaluate_ring3_command(&cmd);
        assert!(!v.allowed);
        assert!(v.kernel_panic);
        assert_eq!(v.ring, 0);
    }

    #[test]
    fn permite_acao_operacional_normal() {
        let cmd = Ring3Command {
            action: ActionType::Update,
            target: "usuario_comum".to_string(),
            intent: "moderacao_padrao".to_string(),
            from_majority_vote: true,
        };
        let v = evaluate_ring3_command(&cmd);
        assert!(v.allowed);
        assert!(!v.kernel_panic);
    }
}
