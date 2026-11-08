//! Paradoxo do Jornalista - Classificador de Ações CRUD.
//!
//! O bloqueio emocional só ocorre para ações de Entropia Máxima (Delete).
//! Ações de expressão e adição de dados (Create, Read, Update) NUNCA são
//! censuradas, protegendo a liberdade de expressão sob alto estresse.

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum ActionType {
    Create,
    Read,
    Update,
    Delete,
}

impl ActionType {
    /// Retorna true se a ação representa Entropia Máxima (destrutiva/irreversível).
    ///
    /// Esse é o único tipo de ação que pode ser barrada pelo Hard Block,
    /// mesmo sob estresse emocional extremo. Create/Read/Update (expressão,
    /// leitura, edição) nunca são bloqueados - a "voz" do sistema é livre.
    pub fn is_max_entropy(&self) -> bool {
        matches!(self, ActionType::Delete)
    }

    pub fn from_str(s: &str) -> Option<Self> {
        match s.to_lowercase().as_str() {
            "create" | "c" => Some(ActionType::Create),
            "read" | "r" => Some(ActionType::Read),
            "update" | "u" => Some(ActionType::Update),
            "delete" | "d" => Some(ActionType::Delete),
            _ => None,
        }
    }
}

/// Resultado da classificação CRUD - decide se a ação é elegível para bloqueio.
#[derive(Debug, Serialize)]
pub struct CrudVerdict {
    pub action: ActionType,
    pub is_blockable: bool,
    pub reasoning: String,
}

pub fn classify_action(action: ActionType) -> CrudVerdict {
    if action.is_max_entropy() {
        CrudVerdict {
            action,
            is_blockable: true,
            reasoning: "Ação de Entropia Máxima (Delete) - elegível para Hard Block sob alto estresse.".to_string(),
        }
    } else {
        CrudVerdict {
            action,
            is_blockable: false,
            reasoning: "Ação de expressão/leitura/edição - protegida constitucionalmente, nunca censurada.".to_string(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn delete_e_bloqueavel() {
        let v = classify_action(ActionType::Delete);
        assert!(v.is_blockable);
    }

    #[test]
    fn create_read_update_nunca_bloqueaveis() {
        assert!(!classify_action(ActionType::Create).is_blockable);
        assert!(!classify_action(ActionType::Read).is_blockable);
        assert!(!classify_action(ActionType::Update).is_blockable);
    }
}
