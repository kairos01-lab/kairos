//! Guarda-Costas - Arquitetura de Segurança do Motor Emocional.
//!
//! Módulo em Rust responsável por:
//! 1. Paradoxo do Jornalista (CRUD) - bloqueio só para Delete
//! 2. Kernel Constitucional (Ring 0 vs Ring 3) - Direitos Humanos imutáveis
//! 3. Protocolo Break Glass - botão de pânico com handshake criptográfico
//! 4. Hard Block - une CRUD + nível de estresse para decisão final
//!
//! Roda separado do Python (via subprocess/JSON) para garantir que o
//! "Guarda-Costas" seja incorruptível por picos emocionais do Córtex (LLM)
//! ou por bugs no lado Python - segurança de memória a nível de compilação.

pub mod break_glass;
pub mod crud_classifier;
pub mod hard_block;
pub mod kernel;
