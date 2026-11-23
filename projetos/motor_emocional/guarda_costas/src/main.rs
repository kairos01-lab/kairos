//! Guarda-Costas CLI - Ponte com o Python via JSON (stdin/stdout).
//!
//! Uso:
//!   echo '{"op":"hard_block", "data": {...}}' | ./guarda_costas
//!
//! Operações suportadas (campo "op"):
//!   - "hard_block": avalia HardBlockRequest -> HardBlockResponse
//!   - "kernel": avalia Ring3Command -> KernelVerdict
//!   - "break_glass": avalia BreakGlassRequest -> BreakGlassVerdict
//!   - "crud": classifica ActionType -> CrudVerdict
//!
//! Contrato de saída (OS099):
//!   sucesso: {"status":"ok", ...campos da operação...}          exit 0
//!   entrada inválida: {"status":"error","error_kind":"invalid_input",...}  exit 2
//!   erro interno: {"status":"error","error_kind":"internal",...}           exit 3
//!
//! O Python só aceita como decisão válida uma resposta com exit 0,
//! `status="ok"` e o contrato específico da operação (OS099/OS100). Qualquer
//! outra coisa é tratada como indisponibilidade/falha e bloqueia a operação.

use guarda_costas::{break_glass, crud_classifier, hard_block, kernel};
use serde::Deserialize;
use serde_json::{json, Value};
use std::io::{self, Read, Write};

const EXIT_INVALID_INPUT: i32 = 2;
const EXIT_INTERNAL: i32 = 3;

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct Envelope {
    op: String,
    data: Value,
}

/// Erro que vira uma resposta JSON de erro e um código de saída não-zero.
#[derive(Debug)]
struct CliError {
    exit_code: i32,
    kind: &'static str,
    message: String,
}

impl CliError {
    fn invalid(message: impl Into<String>) -> Self {
        Self {
            exit_code: EXIT_INVALID_INPUT,
            kind: "invalid_input",
            message: message.into(),
        }
    }

    fn internal(message: impl Into<String>) -> Self {
        Self {
            exit_code: EXIT_INTERNAL,
            kind: "internal",
            message: message.into(),
        }
    }
}

fn main() {
    match run() {
        Ok(value) => {
            println!("{value}");
            io::stdout().flush().ok();
        }
        Err(err) => {
            let payload = json!({
                "status": "error",
                "error_kind": err.kind,
                "error": err.message,
            });
            println!("{payload}");
            io::stdout().flush().ok();
            std::process::exit(err.exit_code);
        }
    }
}

fn run() -> Result<Value, CliError> {
    let mut input = String::new();
    io::stdin()
        .read_to_string(&mut input)
        .map_err(|e| CliError::internal(format!("Falha ao ler stdin: {e}")))?;

    let envelope: Envelope = serde_json::from_str(&input)
        .map_err(|e| CliError::invalid(format!("JSON inválido: {e}")))?;

    match envelope.op.as_str() {
        "hard_block" => {
            let req = serde_json::from_value::<hard_block::HardBlockRequest>(envelope.data)
                .map_err(|e| CliError::invalid(format!("Requisição hard_block inválida: {e}")))?;
            hard_block::validate_request(&req).map_err(|e| CliError::invalid(e.to_string()))?;
            ok_value(hard_block::evaluate_hard_block(&req))
        }
        "kernel" => {
            let cmd = serde_json::from_value::<kernel::Ring3Command>(envelope.data)
                .map_err(|e| CliError::invalid(format!("Requisição kernel inválida: {e}")))?;
            kernel::validate_command(&cmd).map_err(|e| CliError::invalid(e.to_string()))?;
            ok_value(kernel::evaluate_ring3_command(&cmd))
        }
        "break_glass" => {
            let req = serde_json::from_value::<break_glass::BreakGlassRequest>(envelope.data)
                .map_err(|e| CliError::invalid(format!("Requisição break_glass inválida: {e}")))?;
            break_glass::validate_request(&req).map_err(CliError::invalid)?;
            ok_value(break_glass::evaluate_break_glass(&req))
        }
        "crud" => {
            let action_str = envelope
                .data
                .get("action")
                .and_then(Value::as_str)
                .ok_or_else(|| {
                    CliError::invalid(
                        "Requisição crud inválida: campo 'action' ausente ou não é string",
                    )
                })?;
            let action = crud_classifier::ActionType::from_str(action_str).ok_or_else(|| {
                CliError::invalid(format!("Ação CRUD desconhecida: '{action_str}'"))
            })?;
            ok_value(crud_classifier::classify_action(action))
        }
        other => Err(CliError::invalid(format!(
            "Operação desconhecida: '{other}'"
        ))),
    }
}

/// Serializa a resposta e adiciona `status="ok"`.
fn ok_value<T: serde::Serialize>(value: T) -> Result<Value, CliError> {
    let mut value = serde_json::to_value(value)
        .map_err(|e| CliError::internal(format!("Erro ao serializar: {e}")))?;
    let object = value
        .as_object_mut()
        .ok_or_else(|| CliError::internal("Resposta não é um objeto JSON"))?;
    object.insert("status".to_string(), json!("ok"));
    Ok(value)
}
