//! Guarda-Costas CLI - Ponte com o Python via JSON (stdin/stdout).
//!
//! Uso:
//!   echo '{"op":"hard_block", "data": {...}}' | ./guarda_costas
//!
//! Operações suportadas (campo "op"):
//!   - "hard_block": avalia HardBlockRequest -> HardBlockResponse
//!   - "kernel": avalia Ring3Command -> KernelVerdict
//!   - "break_glass": avalia CryptoHandshake -> AlibiJudicial
//!   - "crud": classifica ActionType -> CrudVerdict

use guarda_costas::{break_glass, crud_classifier, hard_block, kernel};
use serde::Deserialize;
use serde_json::Value;
use std::io::{self, Read, Write};

#[derive(Debug, Deserialize)]
struct Envelope {
    op: String,
    data: Value,
}

fn main() {
    let mut input = String::new();
    if io::stdin().read_to_string(&mut input).is_err() {
        print_error("Falha ao ler stdin");
        return;
    }

    let envelope: Envelope = match serde_json::from_str(&input) {
        Ok(e) => e,
        Err(e) => {
            print_error(&format!("JSON inválido: {}", e));
            return;
        }
    };

    let result = match envelope.op.as_str() {
        "hard_block" => {
            match serde_json::from_value::<hard_block::HardBlockRequest>(envelope.data) {
                Ok(req) => serde_json::to_value(hard_block::evaluate_hard_block(&req)),
                Err(e) => Err(e),
            }
        }
        "kernel" => {
            match serde_json::from_value::<kernel::Ring3Command>(envelope.data) {
                Ok(cmd) => serde_json::to_value(kernel::evaluate_ring3_command(&cmd)),
                Err(e) => Err(e),
            }
        }
        "break_glass" => {
            match serde_json::from_value::<break_glass::CryptoHandshake>(envelope.data) {
                Ok(hs) => serde_json::to_value(break_glass::ativar_break_glass(&hs)),
                Err(e) => Err(e),
            }
        }
        "crud" => {
            let action_str = envelope.data.get("action").and_then(|v| v.as_str()).unwrap_or("");
            match crud_classifier::ActionType::from_str(action_str) {
                Some(action) => serde_json::to_value(crud_classifier::classify_action(action)),
                None => {
                    print_error(&format!("Ação CRUD desconhecida: '{}'", action_str));
                    return;
                }
            }
        }
        other => {
            print_error(&format!("Operação desconhecida: '{}'", other));
            return;
        }
    };

    match result {
        Ok(json) => {
            println!("{}", json);
            io::stdout().flush().ok();
        }
        Err(e) => print_error(&format!("Erro ao processar: {}", e)),
    }
}

fn print_error(msg: &str) {
    let err = serde_json::json!({ "error": msg });
    println!("{}", err);
}
