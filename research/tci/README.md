# TCI — arquivo de pesquisa

Este diretório preserva o material histórico da tentativa de testar a TCI
(Teoria da Causalidade Irredutível / TCI-F) no projeto.

**Veredito:** o V19 foi **REPROVADO** como teste da TCI pela auditoria
`AUDITORIA_REDTEAM_V19_FASE_A.md`. O valor deste arquivo é a **negativa
metodológica**, não uma validação.

## O que está aqui

| Arquivo | Papel |
|---|---|
| `MAKTUB_ANALISE_TCI_TEORIA_TESTES.txt` | Síntese teórica (TCI, E-BIDT, TAFA). |
| `FORMALIZACAO_TCI.md` | Resumo limpo das previsões P1–P3. |
| `AUDITORIA_REDTEAM_V19_FASE_A.md` | Auditoria completa (REPROVADO). |
| `PROTOCOLO_V19_DESACOPLAMENTO.md` | Protocolo do V19. |
| `FASE_B_V19.md` | Resultados da Fase B. |
| `DEFINICAO_D_E_ESTABILIDADE_V19.md` | Definições matemáticas. |
| `CALIBRACAO_NUMERICA_V19.md` | Calibração numérica do Σ. |
| `run_v19_fase_b.py` | Script histórico da Fase B. |
| `run_v19_numeric_stability.py` | Script histórico de estabilidade. |
| `registros_v19_fase_b.json` | Registros da Fase B. |
| `registros_v19_estabilidade.json` | Registros de estabilidade. |

## O que não está aqui

- `MAKTUB_TCI_EBIDT_TAFA.txt` (corpus bruto de 48.796 linhas, ~2,3 MB): não foi
  lido linha a linha pela auditoria e não é necessário para o veredito.
- A conversa informal de formalização (`FORMALIZACAO_TCIF_P1_P3_RAW.md`): o
  conteúdo substantivo foi resumido em `FORMALIZACAO_TCI.md`, sem publicar o
  chat bruto.
- Dados de outros experimentos e materiais privados de pesquisa.

## Scripts

Os scripts históricos foram mantidos, mas com os caminhos de saída adaptados:
eles escrevem em `research/tci/reproducao/`, não em `/home/maktub`. A lógica
experimental não foi alterada. Eles servem para reprodução histórica; não são
necessários para usar o motor Kairós.

## Leitura recomendada

1. `MAKTUB_ANALISE_TCI_TEORIA_TESTES.txt` — o que a teoria diz.
2. `FORMALIZACAO_TCI.md` — como as previsões foram formalizadas.
3. `AUDITORIA_REDTEAM_V19_FASE_A.md` — por que o teste não testa a teoria.
4. `docs/TCI.md` — resumo e o que faltaria para um teste real.

## Aviso

Não use este material para afirmar que a TCI foi validada. O resultado é
negativo/metodológico. Se você quiser retomar a TCI, comece por Φ_MIP, mesmo
sistema causal para Φ×Σ e um desfecho de resiliência sob perturbação.
