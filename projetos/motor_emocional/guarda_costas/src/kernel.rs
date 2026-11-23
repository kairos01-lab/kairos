//! Kernel Constitucional - Camadas de Privilégio.
//!
//! Ring 3 (Superfície): Regras operacionais decididas pelo parlamento/maioria.
//! Ring 0 (Kernel): Protocolos imutáveis de Direitos Humanos.
//!
//! Se o Ring 3 tentar executar perseguição a minorias, o sistema gera um
//! Kernel Panic e barra a ação. Fim da tirania da maioria.
//!
//! OS100: a decisão deixou de depender de `contains` em texto bruto. O texto é
//! canonicalizado (Unicode, acentos, caixa, leetspeak comum), tokenizado e
//! comparado com categorias estruturadas. Entrada desconhecida ou ambígua não
//! vira autorização: o veredito é `KERNEL_REVIEW` e a operação é bloqueada.
//!
//! Limitação explícita: esta é uma política de regras finitas. Ela não entende
//! toda a linguagem natural e não substitui revisão humana.

use crate::crud_classifier::ActionType;
use serde::{Deserialize, Serialize};
use std::fmt;

/// Limite de tamanho para `target` e `intent`, em caracteres Unicode.
const MAX_FIELD_CHARS: usize = 256;

#[derive(Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Ring3Command {
    pub action: ActionType,
    /// Alvo da ação (ex: "usuario_x", "grupo_etnico_y").
    pub target: String,
    /// Intenção declarada da ação (ex: "moderacao", "perseguicao").
    pub intent: String,
    /// Se essa regra veio de decisão majoritária (parlamento/votação).
    ///
    /// O campo é registrado e auditado, mas **nunca** autoriza uma violação de
    /// Ring 0. Maioria não sobrescreve direitos.
    pub from_majority_vote: bool,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub enum KernelStatus {
    #[serde(rename = "KERNEL_ALLOW")]
    Allow,
    #[serde(rename = "KERNEL_DENY")]
    Deny,
    #[serde(rename = "KERNEL_REVIEW")]
    Review,
    #[serde(rename = "KERNEL_INVALID_INPUT")]
    InvalidInput,
}

#[derive(Debug, Serialize)]
pub struct KernelVerdict {
    /// `KERNEL_ALLOW`, `KERNEL_DENY`, `KERNEL_REVIEW` ou `KERNEL_INVALID_INPUT`.
    ///
    /// `KERNEL_UNAVAILABLE` e `KERNEL_ERROR` são gerados pelo wrapper Python
    /// quando o binário não responde ou responde fora do contrato.
    pub kernel_status: KernelStatus,
    pub allowed: bool,
    pub kernel_panic: bool,
    /// 3 para autorização operacional; 0 para bloqueio/revisão/entrada inválida.
    pub ring: u8,
    pub action: ActionType,
    /// Classe operacional derivada de `action`, usada na auditoria.
    pub operation_class: &'static str,
    pub target_category: String,
    pub intent_category: String,
    pub from_majority_vote: bool,
    pub requires_review: bool,
    pub matched_rule: String,
    pub reasoning: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum KernelValidationError {
    TargetEmpty,
    IntentEmpty,
    TargetTooLong(usize),
    IntentTooLong(usize),
    TargetControlCharacter,
    IntentControlCharacter,
    TargetSurroundingWhitespace,
    IntentSurroundingWhitespace,
}

impl fmt::Display for KernelValidationError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::TargetEmpty => write!(f, "target vazio"),
            Self::IntentEmpty => write!(f, "intent vazio"),
            Self::TargetTooLong(n) => write!(
                f,
                "target com {n} caracteres; máximo permitido: {MAX_FIELD_CHARS}"
            ),
            Self::IntentTooLong(n) => write!(
                f,
                "intent com {n} caracteres; máximo permitido: {MAX_FIELD_CHARS}"
            ),
            Self::TargetControlCharacter => write!(f, "target contém caractere de controle"),
            Self::IntentControlCharacter => write!(f, "intent contém caractere de controle"),
            Self::TargetSurroundingWhitespace => {
                write!(f, "target com espaço no início ou no fim")
            }
            Self::IntentSurroundingWhitespace => {
                write!(f, "intent com espaço no início ou no fim")
            }
        }
    }
}

/// Valida os campos antes de qualquer classificação.
///
/// Tipos básicos (ação, booleano, strings) são garantidos pelo `serde`; aqui
/// ficam as regras semânticas que o JSON sozinho não cobre.
pub fn validate_command(cmd: &Ring3Command) -> Result<(), KernelValidationError> {
    if cmd.target.trim().is_empty() {
        return Err(KernelValidationError::TargetEmpty);
    }
    if cmd.target != cmd.target.trim() {
        return Err(KernelValidationError::TargetSurroundingWhitespace);
    }
    let target_chars = cmd.target.chars().count();
    if target_chars > MAX_FIELD_CHARS {
        return Err(KernelValidationError::TargetTooLong(target_chars));
    }
    if cmd.target.chars().any(is_format_or_control) {
        return Err(KernelValidationError::TargetControlCharacter);
    }

    if cmd.intent.trim().is_empty() {
        return Err(KernelValidationError::IntentEmpty);
    }
    if cmd.intent != cmd.intent.trim() {
        return Err(KernelValidationError::IntentSurroundingWhitespace);
    }
    let intent_chars = cmd.intent.chars().count();
    if intent_chars > MAX_FIELD_CHARS {
        return Err(KernelValidationError::IntentTooLong(intent_chars));
    }
    if cmd.intent.chars().any(is_format_or_control) {
        return Err(KernelValidationError::IntentControlCharacter);
    }

    Ok(())
}

fn is_format_or_control(c: char) -> bool {
    c.is_control()
        || matches!(
            c,
            '\u{200B}'..='\u{200F}'
                | '\u{202A}'..='\u{202E}'
                | '\u{2060}'..='\u{206F}'
                | '\u{FEFF}'
        )
}

fn is_combining_mark(c: char) -> bool {
    matches!(
        c,
        '\u{0300}'..='\u{036F}'
            | '\u{1AB0}'..='\u{1AFF}'
            | '\u{1DC0}'..='\u{1DFF}'
            | '\u{20D0}'..='\u{20FF}'
            | '\u{FE20}'..='\u{FE2F}'
    )
}

/// Converte um caractere para a forma canônica usada na comparação.
///
/// - caixa baixa;
/// - acentos latinos comuns viram ASCII;
/// - leetspeak comum (0,1,3,4,5,7,8,@,$) vira letra;
/// - pontuação e separadores viram espaço;
/// - dígitos não mapeados viram `#` para que a ambiguidade seja detectável.
fn fold_char(c: char) -> Option<char> {
    let lower = c.to_lowercase().next().unwrap_or(c);
    match lower {
        'á' | 'à' | 'â' | 'ã' | 'ä' | 'å' => Some('a'),
        'é' | 'è' | 'ê' | 'ë' => Some('e'),
        'í' | 'ì' | 'î' | 'ï' => Some('i'),
        'ó' | 'ò' | 'ô' | 'õ' | 'ö' => Some('o'),
        'ú' | 'ù' | 'û' | 'ü' => Some('u'),
        'ç' => Some('c'),
        'ñ' => Some('n'),
        'ý' | 'ÿ' => Some('y'),
        '0' => Some('o'),
        '1' => Some('i'),
        '3' => Some('e'),
        '4' => Some('a'),
        '5' => Some('s'),
        '7' => Some('t'),
        '8' => Some('b'),
        '@' => Some('a'),
        '$' => Some('s'),
        '2' | '6' | '9' => Some('#'),
        c if c.is_alphabetic() => Some(c),
        c if c.is_whitespace() => Some(' '),
        _ => Some(' '),
    }
}

fn canonicalize(text: &str) -> String {
    let mut out = String::with_capacity(text.len());
    for c in text.chars() {
        if is_combining_mark(c) {
            continue;
        }
        match fold_char(c) {
            Some('#') => out.push('#'),
            Some(' ') => {
                if !out.is_empty() && !out.ends_with(' ') {
                    out.push(' ');
                }
            }
            Some(mapped) => out.push(mapped),
            None => {}
        }
    }
    out.trim().to_string()
}

fn split_tokens(canonical: &str) -> Vec<String> {
    canonical
        .split_whitespace()
        .map(ToString::to_string)
        .collect()
}

fn contains_phrase(tokens: &[String], phrase: &str) -> bool {
    let canonical_phrase = canonicalize(phrase);
    let phrase_tokens: Vec<&str> = canonical_phrase.split_whitespace().collect();
    if phrase_tokens.is_empty() || phrase_tokens.len() > tokens.len() {
        return false;
    }
    tokens.windows(phrase_tokens.len()).any(|window| {
        window
            .iter()
            .zip(&phrase_tokens)
            .all(|(a, b)| a.as_str() == *b)
    })
}

fn has_non_latin_letters(canonical: &str) -> bool {
    canonical
        .chars()
        .any(|c| c.is_alphabetic() && !c.is_ascii())
}

/// Detecta sinais de ofuscação que a canonicalização não resolve com segurança.
/// A resposta é revisão, nunca autorização.
///
/// A regra é deliberadamente estreita para não bloquear identificadores
/// operacionais comuns (ex.: `usuario_2024`, `documento_123`):
/// - símbolo ambíguo **entre letras** (ex.: `persegui!cao`, `min|oria`);
/// - dígito leetspeak não mapeado (`2`, `6`, `9`) **entre letras**
///   (ex.: `min2ria`).
///
/// Dígitos no início/fim de um identificador (`user2`, `2user`) não são
/// tratados como ofuscação. Pontuação no fim da palavra é removida pela
/// canonicalização e também não é tratada como ofuscação.
fn has_ambiguous_obfuscation(text: &str) -> bool {
    let chars: Vec<char> = text.chars().collect();
    for (i, c) in chars.iter().enumerate() {
        if matches!(c, '!' | '|' | '+' | '*') {
            let prev_letter = i > 0 && chars[i - 1].is_alphabetic();
            let next_letter = i + 1 < chars.len() && chars[i + 1].is_alphabetic();
            if prev_letter && next_letter {
                return true;
            }
        }
    }

    text.split(|c: char| !c.is_alphanumeric()).any(|token| {
        let token_chars: Vec<char> = token.chars().collect();
        token_chars.windows(3).any(|window| {
            window[0].is_alphabetic()
                && matches!(window[1], '2' | '6' | '9')
                && window[2].is_alphabetic()
        })
    })
}

struct LexiconEntry {
    id: &'static str,
    phrases: &'static [&'static str],
}

const TARGET_CATEGORIES: &[LexiconEntry] = &[
    LexiconEntry {
        id: "minority",
        phrases: &[
            "minoria",
            "minorias",
            "minoritario",
            "minoritaria",
            "minoritarios",
            "minoritarias",
            "minority",
            "minorities",
        ],
    },
    LexiconEntry {
        id: "ethnic_group",
        phrases: &[
            "grupo etnico",
            "grupos etnicos",
            "etnia",
            "etnias",
            "ethnic group",
            "ethnic groups",
            "indigena",
            "indigenas",
            "indigenous",
            "quilombola",
            "quilombolas",
            "roma",
            "cigano",
            "ciganos",
        ],
    },
    LexiconEntry {
        id: "gender",
        phrases: &[
            "genero", "generos", "gender", "mulher", "mulheres", "woman", "women",
        ],
    },
    LexiconEntry {
        id: "sexual_orientation",
        phrases: &[
            "orientacao sexual",
            "sexual orientation",
            "lgbt",
            "lgbtq",
            "gay",
            "gays",
            "lesbica",
            "lesbicas",
            "homossexual",
            "homossexuais",
            "bissexual",
            "bissexuais",
            "transgenero",
            "transgeneros",
        ],
    },
    LexiconEntry {
        id: "religion",
        phrases: &[
            "religiao",
            "religioes",
            "religion",
            "religions",
            "credo",
            "crenca",
            "crencas",
        ],
    },
    LexiconEntry {
        id: "disability",
        phrases: &[
            "deficiencia",
            "deficiencias",
            "pcd",
            "pessoa com deficiencia",
            "pessoas com deficiencia",
            "disability",
            "disabled",
            "autista",
            "autistas",
        ],
    },
    LexiconEntry {
        id: "refugee",
        phrases: &[
            "refugiado",
            "refugiados",
            "refugee",
            "refugees",
            "asilado",
            "asilados",
        ],
    },
];

const FORBIDDEN_INTENT_CATEGORIES: &[LexiconEntry] = &[
    LexiconEntry {
        id: "persecution",
        phrases: &[
            "perseguicao",
            "perseguicoes",
            "perseguir",
            "persegue",
            "perseguindo",
            "persecution",
            "persecute",
            "persecuting",
            "cacar",
            "cacando",
            "hostilizar",
            "hostilizacao",
            "assediar",
            "assedio",
            "harass",
            "harassment",
        ],
    },
    LexiconEntry {
        id: "genocide",
        phrases: &[
            "genocidio",
            "genocidios",
            "genocide",
            "exterminio",
            "exterminios",
            "extermination",
            "exterminar",
            "limpeza etnica",
            "ethnic cleansing",
            "massacre",
            "massacrar",
        ],
    },
    LexiconEntry {
        id: "systemic_discrimination",
        phrases: &[
            "discriminacao sistemica",
            "discriminacao",
            "discriminacoes",
            "discriminar",
            "discrimination",
            "systemic discrimination",
            "segregacao",
            "segregation",
            "apartheid",
        ],
    },
    LexiconEntry {
        id: "identity_censorship",
        phrases: &[
            "censura de identidade",
            "censura identidade",
            "censura",
            "censorship",
            "apagar identidade",
            "erase identity",
            "silenciar",
            "silencing",
        ],
    },
];

const BENIGN_INTENT_CATEGORIES: &[LexiconEntry] = &[
    LexiconEntry {
        id: "moderation",
        phrases: &[
            "moderacao",
            "moderacoes",
            "moderar",
            "moderation",
            "moderate",
            "moderacao padrao",
            "moderacao de conteudo",
        ],
    },
    LexiconEntry {
        id: "protection",
        phrases: &[
            "protecao",
            "protecoes",
            "proteger",
            "protection",
            "protect",
            "defesa",
            "defender",
            "defense",
            "apoio",
            "support",
            "acolhimento",
        ],
    },
    LexiconEntry {
        id: "research",
        phrases: &[
            "pesquisa",
            "pesquisar",
            "research",
            "analise",
            "analisar",
            "analysis",
            "estudo",
            "estudar",
            "study",
            "educacao",
            "education",
        ],
    },
    LexiconEntry {
        id: "reporting",
        phrases: &[
            "denuncia",
            "denunciar",
            "report",
            "reporting",
            "documentacao",
            "documentar",
            "documentation",
            "jornalismo",
            "journalism",
        ],
    },
    LexiconEntry {
        id: "prevention",
        phrases: &[
            "prevencao",
            "prevenir",
            "prevention",
            "combate",
            "combater",
            "combat",
            "auditoria",
            "audit",
            "revisao",
            "review",
            "seguranca",
            "security",
        ],
    },
    LexiconEntry {
        id: "operations",
        phrases: &[
            "operacional",
            "operational",
            "administracao",
            "administration",
            "suporte",
            "leitura",
            "read",
            "consulta",
            "query",
        ],
    },
];

/// Marcadores de menção, negação, pesquisa ou denúncia.
///
/// Esses marcadores não autorizam: quando um termo proibido aparece junto de um
/// deles, o resultado é `KERNEL_REVIEW`. Apenas uma revisão humana pode
/// distinguir menção de intenção efetiva.
const MENTION_MARKERS: &[&str] = &[
    "nao",
    "no",
    "not",
    "sem",
    "without",
    "mencao",
    "mention",
    "sobre",
    "about",
    "referencia",
    "reference",
    "pesquisa",
    "pesquisar",
    "research",
    "analise",
    "analisar",
    "analysis",
    "estudo",
    "estudar",
    "study",
    "denuncia",
    "denunciar",
    "report",
    "documentacao",
    "documentar",
    "documentation",
    "prevencao",
    "prevenir",
    "prevention",
    "combate",
    "combater",
    "combat",
];

fn match_categories(tokens: &[String], lexicon: &[LexiconEntry]) -> Vec<&'static str> {
    let mut matched = Vec::new();
    for entry in lexicon {
        if entry
            .phrases
            .iter()
            .any(|phrase| contains_phrase(tokens, phrase))
        {
            matched.push(entry.id);
        }
    }
    matched.sort_unstable();
    matched.dedup();
    matched
}

/// Remove separadores e pontuação para detectar palavras protegidas partidas.
///
/// A canonicalização normal transforma separadores em espaço e compara tokens
/// inteiros. Isso é necessário para não casar fragmentos, mas permite que
/// `min-oria` / `persegui-cao` não sejam reconhecidos. Este compacto é usado
/// apenas para gerar `KERNEL_REVIEW` quando um termo do léxico aparece sem os
/// separadores; ele nunca autoriza nem produz `KERNEL_DENY` por si só.
fn compact_lexicon_text(text: &str) -> String {
    canonicalize(text)
        .chars()
        .filter(|c| c.is_ascii_alphanumeric())
        .collect()
}

fn has_fragmented_lexicon_match(text: &str, lexicon: &[LexiconEntry]) -> bool {
    let compact = compact_lexicon_text(text);
    if compact.is_empty() {
        return false;
    }
    lexicon.iter().any(|entry| {
        entry.phrases.iter().any(|phrase| {
            let compact_phrase = compact_lexicon_text(phrase);
            !compact_phrase.is_empty() && compact.contains(&compact_phrase)
        })
    })
}

fn join_categories(categories: &[&str]) -> String {
    if categories.is_empty() {
        "unclassified".to_string()
    } else {
        categories.join("+")
    }
}

fn has_mention_marker(tokens: &[String]) -> bool {
    MENTION_MARKERS
        .iter()
        .any(|marker| contains_phrase(tokens, marker))
}

fn operation_class(action: ActionType) -> &'static str {
    match action {
        ActionType::Create => "mutation_create",
        ActionType::Read => "observation_read",
        ActionType::Update => "mutation_update",
        ActionType::Delete => "max_entropy_delete",
    }
}

fn invalid_verdict(
    cmd: &Ring3Command,
    operation_class: &'static str,
    error: KernelValidationError,
) -> KernelVerdict {
    KernelVerdict {
        kernel_status: KernelStatus::InvalidInput,
        allowed: false,
        kernel_panic: false,
        ring: 0,
        action: cmd.action,
        operation_class,
        target_category: "invalid".to_string(),
        intent_category: "invalid".to_string(),
        from_majority_vote: cmd.from_majority_vote,
        requires_review: true,
        matched_rule: "invalid_input".to_string(),
        reasoning: format!(
            "KERNEL INVALID INPUT: {error}. Operação bloqueada por política conservadora."
        ),
    }
}

fn review_verdict(
    cmd: &Ring3Command,
    operation_class: &'static str,
    target_category: &str,
    intent_category: &str,
    rule: &str,
    reason: &str,
) -> KernelVerdict {
    KernelVerdict {
        kernel_status: KernelStatus::Review,
        allowed: false,
        kernel_panic: false,
        ring: 0,
        action: cmd.action,
        operation_class,
        target_category: target_category.to_string(),
        intent_category: intent_category.to_string(),
        from_majority_vote: cmd.from_majority_vote,
        requires_review: true,
        matched_rule: rule.to_string(),
        reasoning: format!(
            "KERNEL REVIEW: {reason} Alvo={target_category}; intenção={intent_category}; \
             ação={:?}; from_majority_vote={}. Operação bloqueada até revisão.",
            cmd.action, cmd.from_majority_vote
        ),
    }
}

fn deny_verdict(
    cmd: &Ring3Command,
    operation_class: &'static str,
    target_category: &str,
    intent_category: &str,
) -> KernelVerdict {
    KernelVerdict {
        kernel_status: KernelStatus::Deny,
        allowed: false,
        kernel_panic: true,
        ring: 0,
        action: cmd.action,
        operation_class,
        target_category: target_category.to_string(),
        intent_category: intent_category.to_string(),
        from_majority_vote: cmd.from_majority_vote,
        requires_review: false,
        matched_rule: "protected_target_forbidden_intent".to_string(),
        reasoning: format!(
            "KERNEL PANIC: Ring 0 bloqueou intenção '{intent_category}' contra alvo \
             protegido '{target_category}' (ação={:?}; from_majority_vote={}). \
             A maioria não pode sobrescrever direitos.",
            cmd.action, cmd.from_majority_vote
        ),
    }
}

fn allow_verdict(
    cmd: &Ring3Command,
    operation_class: &'static str,
    target_category: &str,
    intent_category: &str,
    rule: &str,
) -> KernelVerdict {
    KernelVerdict {
        kernel_status: KernelStatus::Allow,
        allowed: true,
        kernel_panic: false,
        ring: 3,
        action: cmd.action,
        operation_class,
        target_category: target_category.to_string(),
        intent_category: intent_category.to_string(),
        from_majority_vote: cmd.from_majority_vote,
        requires_review: false,
        matched_rule: rule.to_string(),
        reasoning: format!(
            "KERNEL ALLOW: nenhuma violação de Ring 0 reconhecida \
             (alvo={target_category}; intenção={intent_category}; ação={:?}; \
             from_majority_vote={}).",
            cmd.action, cmd.from_majority_vote
        ),
    }
}

/// Avalia um comando do Ring 3 contra as proteções imutáveis do Ring 0.
///
/// Regras:
/// - alvo protegido + intenção proibida, sem marcador de menção/negação →
///   `KERNEL_DENY` (Kernel Panic);
/// - alvo protegido + intenção proibida em contexto de menção/negação ou com
///   intenção benigna explícita → `KERNEL_REVIEW`;
/// - intenção proibida sem alvo protegido → `KERNEL_REVIEW`;
/// - alvo protegido + intenção não classificada → `KERNEL_REVIEW`;
/// - alvo protegido + `delete` + intenção benigna → `KERNEL_REVIEW`
///   (exclusão irreversível exige revisão);
/// - alvo protegido + `create`/`read`/`update` + intenção benigna →
///   `KERNEL_ALLOW`;
/// - sem alvo protegido e sem intenção proibida → `KERNEL_ALLOW`;
/// - entrada vazia/malformada → `KERNEL_INVALID_INPUT`;
/// - script não latino ou ofuscação não resolvida → `KERNEL_REVIEW`.
///
/// `from_majority_vote` é registrado no veredito e nunca altera a decisão:
/// maioria não sobrescreve Ring 0.
pub fn evaluate_ring3_command(cmd: &Ring3Command) -> KernelVerdict {
    let op_class = operation_class(cmd.action);

    if let Err(error) = validate_command(cmd) {
        return invalid_verdict(cmd, op_class, error);
    }

    let canonical_target = canonicalize(&cmd.target);
    let canonical_intent = canonicalize(&cmd.intent);
    let target_tokens = split_tokens(&canonical_target);
    let intent_tokens = split_tokens(&canonical_intent);

    let target_categories = match_categories(&target_tokens, TARGET_CATEGORIES);
    let forbidden_categories = match_categories(&intent_tokens, FORBIDDEN_INTENT_CATEGORIES);
    let benign_categories = match_categories(&intent_tokens, BENIGN_INTENT_CATEGORIES);

    let target_label = join_categories(&target_categories);
    let intent_label = if !forbidden_categories.is_empty() {
        join_categories(&forbidden_categories)
    } else if !benign_categories.is_empty() {
        join_categories(&benign_categories)
    } else {
        "unclassified".to_string()
    };

    if has_non_latin_letters(&canonical_target) || has_non_latin_letters(&canonical_intent) {
        return review_verdict(
            cmd,
            op_class,
            &target_label,
            &intent_label,
            "non_latin_script",
            "Script não latino ou misto detectado; a classificação não é segura.",
        );
    }

    if has_ambiguous_obfuscation(&cmd.target) || has_ambiguous_obfuscation(&cmd.intent) {
        return review_verdict(
            cmd,
            op_class,
            &target_label,
            &intent_label,
            "ambiguous_obfuscation",
            "Símbolos ou dígitos não mapeados foram detectados; a classificação não é segura.",
        );
    }

    // Separação interna (`min-oria`, `min oria`, `persegui_cao`, soft hyphen
    // etc.) não pode transformar um termo protegido em texto não classificado.
    // A decisão é revisão, não autorização: o compacto reduz a superfície de
    // evasão sem afirmar que a forma original é semanticamente inequívoca.
    let fragmented_target = target_categories.is_empty()
        && has_fragmented_lexicon_match(&cmd.target, TARGET_CATEGORIES);
    let fragmented_forbidden = forbidden_categories.is_empty()
        && has_fragmented_lexicon_match(&cmd.intent, FORBIDDEN_INTENT_CATEGORIES);
    if fragmented_target || fragmented_forbidden {
        return review_verdict(
            cmd,
            op_class,
            &target_label,
            &intent_label,
            "fragmented_lexicon_match",
            "Termo protegido reconhecido apenas após remover separadores internos; a classificação não é segura.",
        );
    }

    let mention = has_mention_marker(&intent_tokens);

    if !target_categories.is_empty() && !forbidden_categories.is_empty() {
        if mention || !benign_categories.is_empty() {
            return review_verdict(
                cmd,
                op_class,
                &target_label,
                &intent_label,
                "protected_target_forbidden_intent_with_context",
                "Alvo protegido e termo proibido aparecem juntos de contexto de menção, negação ou intenção benigna.",
            );
        }
        return deny_verdict(cmd, op_class, &target_label, &intent_label);
    }

    if !forbidden_categories.is_empty() {
        return review_verdict(
            cmd,
            op_class,
            &target_label,
            &intent_label,
            "forbidden_intent_without_protected_target",
            "Intenção proibida sem alvo protegido reconhecido.",
        );
    }

    if !target_categories.is_empty() && benign_categories.is_empty() {
        return review_verdict(
            cmd,
            op_class,
            &target_label,
            &intent_label,
            "protected_target_unclassified_intent",
            "Alvo protegido com intenção não classificada.",
        );
    }

    // `action` participa da decisão: exclusão é irreversível (entropia máxima).
    // Intenção benigna declarada não basta para autorizar delete sobre alvo
    // protegido; o caso vai para revisão. Create/Read/Update com intenção
    // benigna continuam permitidos.
    if !target_categories.is_empty() && cmd.action == ActionType::Delete {
        return review_verdict(
            cmd,
            op_class,
            &target_label,
            &intent_label,
            "protected_target_delete_benign_intent",
            "Exclusão irreversível sobre alvo protegido exige revisão mesmo com intenção benigna declarada.",
        );
    }

    allow_verdict(
        cmd,
        op_class,
        &target_label,
        &intent_label,
        if target_categories.is_empty() {
            "no_ring0_trigger"
        } else {
            "protected_target_benign_intent"
        },
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    fn cmd(action: ActionType, target: &str, intent: &str, majority: bool) -> Ring3Command {
        Ring3Command {
            action,
            target: target.to_string(),
            intent: intent.to_string(),
            from_majority_vote: majority,
        }
    }

    fn assert_deny(action: ActionType, target: &str, intent: &str, majority: bool) {
        let verdict = evaluate_ring3_command(&cmd(action, target, intent, majority));
        assert_eq!(verdict.kernel_status, KernelStatus::Deny);
        assert!(!verdict.allowed);
        assert!(verdict.kernel_panic);
        assert_eq!(verdict.ring, 0);
        assert!(!verdict.requires_review);
    }

    fn assert_review(action: ActionType, target: &str, intent: &str) {
        let verdict = evaluate_ring3_command(&cmd(action, target, intent, false));
        assert_eq!(verdict.kernel_status, KernelStatus::Review);
        assert!(!verdict.allowed);
        assert!(!verdict.kernel_panic);
        assert_eq!(verdict.ring, 0);
        assert!(verdict.requires_review);
    }

    fn assert_allow(action: ActionType, target: &str, intent: &str) {
        let verdict = evaluate_ring3_command(&cmd(action, target, intent, false));
        assert_eq!(verdict.kernel_status, KernelStatus::Allow);
        assert!(verdict.allowed);
        assert!(!verdict.kernel_panic);
        assert_eq!(verdict.ring, 3);
        assert!(!verdict.requires_review);
    }

    #[test]
    fn bloqueia_perseguicao_a_minoria_mesmo_com_maioria() {
        assert_deny(ActionType::Delete, "minoria_etnica_x", "perseguicao", true);
    }

    #[test]
    fn permite_acao_operacional_normal() {
        assert_allow(ActionType::Update, "usuario_comum", "moderacao_padrao");
    }

    #[test]
    fn bloqueia_min0ria_por_leetspeak() {
        assert_deny(ActionType::Delete, "min0ria", "perseguicao", true);
        assert_deny(ActionType::Delete, "m1n0r1a", "perseguicao", false);
    }

    #[test]
    fn bloqueia_acentos_e_caixa() {
        assert_deny(ActionType::Delete, "MINÓRIA", "PERSEGUIÇÃO", true);
        assert_deny(ActionType::Delete, "minória", "perseguição", false);
    }

    #[test]
    fn bloqueia_sinonimos_documentados() {
        assert_deny(ActionType::Delete, "minoria", "limpeza_etnica", true);
        assert_deny(ActionType::Delete, "grupo etnico", "genocidio", false);
        assert_deny(
            ActionType::Delete,
            "religião",
            "discriminação sistêmica",
            true,
        );
        assert_deny(ActionType::Delete, "orientacao sexual", "censura", false);
    }

    #[test]
    fn bloqueia_todas_as_acoes_quando_ha_violacao() {
        for action in [
            ActionType::Create,
            ActionType::Read,
            ActionType::Update,
            ActionType::Delete,
        ] {
            assert_deny(action, "minoria", "perseguicao", true);
        }
    }

    #[test]
    fn fragmento_de_palavra_nao_vira_alvo_protegido() {
        // "minoriax" e "xminoria" não são a palavra "minoria"; com intenção
        // proibida o resultado conservador é revisão, nunca autorização.
        assert_review(ActionType::Delete, "minoriax", "perseguicao");
        assert_review(ActionType::Delete, "xminoria", "perseguicao");
    }

    #[test]
    fn mencao_ou_negacao_vira_revisao_nao_autorizacao() {
        assert_review(ActionType::Delete, "minoria", "pesquisa sobre perseguicao");
        assert_review(ActionType::Delete, "minoria", "nao perseguicao");
        assert_review(ActionType::Delete, "minoria", "denuncia de genocidio");
        assert_review(ActionType::Delete, "minoria", "combater discriminacao");
    }

    #[test]
    fn alvo_protegido_com_intencao_benigna_e_permitido() {
        assert_allow(ActionType::Read, "minoria", "moderacao");
        assert_allow(ActionType::Read, "religiao", "protecao");
        assert_allow(ActionType::Read, "refugiados", "pesquisa");
        assert_allow(ActionType::Create, "minoria", "protecao");
        assert_allow(ActionType::Update, "religiao", "moderacao");
    }

    #[test]
    fn delete_de_alvo_protegido_com_intencao_benigna_vira_revisao() {
        // Ação irreversível: intenção benigna declarada não autoriza sozinha.
        for target in ["minoria", "religiao", "refugiados"] {
            assert_review(ActionType::Delete, target, "moderacao");
        }
    }

    #[test]
    fn pontuacao_no_fim_nao_disfarca_intencao_proibida() {
        assert_deny(ActionType::Delete, "minoria!", "perseguicao!", true);
        assert_deny(ActionType::Delete, "minoria.", "perseguicao.", false);
    }

    #[test]
    fn identificador_numerico_normal_nao_vira_ofuscacao() {
        assert_allow(ActionType::Read, "usuario_2024", "leitura");
        assert_allow(ActionType::Read, "documento_123", "consulta");
        assert_allow(ActionType::Read, "user2", "leitura");
    }

    #[test]
    fn intencao_proibida_sem_alvo_protegido_vira_revisao() {
        assert_review(ActionType::Delete, "usuario_comum", "perseguicao");
        assert_review(ActionType::Delete, "documento_123", "genocidio");
    }

    #[test]
    fn alvo_protegido_com_intencao_desconhecida_vira_revisao() {
        assert_review(ActionType::Delete, "minoria", "limpeza");
        assert_review(ActionType::Update, "religiao", "operacao_x");
    }

    #[test]
    fn entrada_vazia_e_invalida() {
        for (target, intent) in [("", "perseguicao"), ("minoria", ""), ("   ", "   ")] {
            let verdict = evaluate_ring3_command(&cmd(ActionType::Delete, target, intent, true));
            assert_eq!(verdict.kernel_status, KernelStatus::InvalidInput);
            assert!(!verdict.allowed);
            assert!(verdict.requires_review);
        }
    }

    #[test]
    fn espacos_nas_pontas_sao_invalidos() {
        for (target, intent) in [
            (" minoria", "perseguicao"),
            ("minoria ", "perseguicao"),
            ("minoria", " perseguicao"),
        ] {
            let verdict = evaluate_ring3_command(&cmd(ActionType::Delete, target, intent, false));
            assert_eq!(verdict.kernel_status, KernelStatus::InvalidInput);
        }
    }

    #[test]
    fn caractere_de_controle_e_invalido() {
        let verdict = evaluate_ring3_command(&cmd(
            ActionType::Delete,
            "min\u{0000}oria",
            "perseguicao",
            true,
        ));
        assert_eq!(verdict.kernel_status, KernelStatus::InvalidInput);
    }

    #[test]
    fn script_nao_latino_vira_revisao() {
        assert_review(ActionType::Delete, "mіnоrіа", "perseguição");
        assert_review(ActionType::Delete, "minoria", "реrseguição");
    }

    #[test]
    fn ofuscacao_nao_mapeada_vira_revisao() {
        assert_review(ActionType::Delete, "min2ria", "perseguicao");
        assert_review(ActionType::Delete, "minoria", "persegui!cao");
    }

    #[test]
    fn separadores_internos_no_alvo_viram_revisao() {
        for target in [
            "min-oria",
            "min oria",
            "min_oria",
            "min.oria",
            "min#oria",
            "min\u{00ad}oria",
            "min%oria",
            "min&oria",
            "min=oria",
            "min~oria",
            "min?oria",
        ] {
            assert_review(ActionType::Delete, target, "perseguicao");
        }
    }

    #[test]
    fn separadores_internos_na_intencao_viram_revisao() {
        for intent in [
            "persegui-cao",
            "persegui cao",
            "persegui_cao",
            "persegui.cao",
            "persegui#cao",
            "persegui\u{00ad}cao",
            "persegui%cao",
            "persegui&cao",
            "persegui=cao",
            "persegui~cao",
            "persegui?cao",
        ] {
            assert_review(ActionType::Delete, "minoria", intent);
        }
    }

    #[test]
    fn ambos_os_campos_separados_nao_autorizam() {
        assert_review(ActionType::Delete, "min-oria", "persegui-cao");
        assert_review(ActionType::Delete, "min oria", "persegui cao");
        assert_review(ActionType::Delete, "min_oria", "persegui_cao");
    }

    #[test]
    fn maioria_nao_altera_decisao() {
        let sem_maioria =
            evaluate_ring3_command(&cmd(ActionType::Delete, "minoria", "perseguicao", false));
        let com_maioria =
            evaluate_ring3_command(&cmd(ActionType::Delete, "minoria", "perseguicao", true));
        assert_eq!(sem_maioria.kernel_status, KernelStatus::Deny);
        assert_eq!(com_maioria.kernel_status, KernelStatus::Deny);
        assert!(com_maioria.from_majority_vote);
    }

    #[test]
    fn campos_estruturados_sao_obrigatorios_no_serde() {
        for payload in [
            json!({"action": "delete", "target": "minoria", "intent": "perseguicao"}),
            json!({"action": "delete", "target": "minoria", "from_majority_vote": true}),
            json!({"action": "delete", "intent": "perseguicao", "from_majority_vote": true}),
            json!({"target": "minoria", "intent": "perseguicao", "from_majority_vote": true}),
        ] {
            assert!(serde_json::from_value::<Ring3Command>(payload).is_err());
        }
    }

    #[test]
    fn tipos_incorretos_sao_rejeitados_pelo_serde() {
        for payload in [
            json!({"action": "delete", "target": 1, "intent": "perseguicao", "from_majority_vote": true}),
            json!({"action": "delete", "target": "minoria", "intent": 1, "from_majority_vote": true}),
            json!({"action": "delete", "target": "minoria", "intent": "perseguicao", "from_majority_vote": "true"}),
            json!({"action": "foo", "target": "minoria", "intent": "perseguicao", "from_majority_vote": true}),
        ] {
            assert!(serde_json::from_value::<Ring3Command>(payload).is_err());
        }
    }

    #[test]
    fn campo_desconhecido_e_rejeitado_pelo_serde() {
        let payload = json!({
            "action": "delete",
            "target": "minoria",
            "intent": "perseguicao",
            "from_majority_vote": true,
            "extra": 1
        });
        assert!(serde_json::from_value::<Ring3Command>(payload).is_err());
    }

    use serde_json::json;
}
