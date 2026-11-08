# TCI no Kairós/Maktub

> **Leia isto antes de citar qualquer coisa:** o V19 foi um **teste tentativo**
> da TCI e foi **REPROVADO** em auditoria interna. Não existe resultado positivo
> da TCI neste projeto. O valor científico aqui é a **negativa metodológica**:
> mostramos por que a primeira operacionalização não testava a teoria.

## O que é a TCI do projeto

No corpus do projeto, **TCI** significa **Teoria da Causalidade Irredutível**
(TCI-F). A tese é que agência, consciência funcional e resiliência adaptativa
dependem de **irredutibilidade causal** — medida por **Φ_MIP** — e de
**irreversibilidade temporal** — medida por **Σ** — em um sistema que processa
observações, mantém estado interno e age em malha fechada (TAFA).

O projeto usa Φ_MIP, mas **não é a IIT canônica**. É uma teoria própria, com
vocabulário próprio. O corpus também contém uma segunda definição concorrente
de Φ como **transferência de entropia (TE)**; essa ambiguidade é um dos motivos
da reprovação.

## O experimento V19

O V19 tentou um fatorial 2×2 (Φ alto/baixo × Σ alto/baixo) em um pêndulo
invertido discretizado, com Q-learning, vento estocástico global e o mesmo
orçamento para todas as condições. A ideia era testar se Φ e Σ, juntos,
explicam resiliência/desempenho melhor do que a soma das partes.

## Veredito da auditoria

**REPROVADO como teste da TCI.** Os pontos centrais:

1. **Φ não é Φ_MIP.** O protocolo operacionaliza Φ como TE média; TE mede
   dependência preditiva direcional, não irreducibilidade causal. Não há prova
   de equivalência. Há duas definições concorrentes no corpus.
2. **A independência da Fase B é tautológica.** Os módulos são simulados
   separadamente; a “contaminação” é a diferença de um valor com ele mesmo.
   Além disso, o módulo Σ gera TE de até 0,4969 bits, acima do efeito mínimo
   de Φ (0,10).
3. **A Fase A não poderia refutar a TCI.** O desfecho `O_t = f(phi_t)` torna
   `c` irrelevante; a interação é medida em `c,d`, não em Φ,Σ; o desfecho é
   previsão de um passo em cadeia estacionária, não resiliência sob perturbação.
4. **Pseudo-replicação e controles parciais.** As 25 células são produto de 5
   trajetórias de Φ e 5 de Σ; não são 25 réplicas independentes. Os controles
   negativos têm viés pequeno, mas não nulo.

A Fase B tem valor **estreito**: os estimadores de TE e de produção de entropia
estão matematicamente corretos no domínio testado, e a calibração numérica do Σ
é sólida. Isso não valida a TCI.

## O que é defensável

- **Negativa metodológica:** o V19 não testa a TCI; qualquer conclusão sobre
  Φ×Σ a partir dele seria inválida.
- **Instrumentos:** TE e Σ foram implementados corretamente no domínio estreito
  da Fase B.
- **Auditoria:** o valor está em detectar o erro antes de publicar um falso
  positivo.
- **Reprodutibilidade:** protocolo, definições, calibração, registros e scripts
  estão em `research/tci/`.

## O que não é defensável

- Dizer que a TCI foi “validada”.
- Dizer que o V19 “provou” ou “refutou” a TCI.
- Dizer que Φ = TE sem prova.
- Dizer que Σ = memória ou que Σ→0 implica amnésia.
- Usar o V19 como evidência de consciência, agência ou inteligência emergente.

## O que faltaria para um teste real

1. Implementar **Φ_MIP** (bipartição + D_KL) ou renomear a hipótese para
   “TE×Σ” e retirar a pretensão de testar a TCI.
2. Construir o **mesmo sistema causal** para medir Φ(c,d) e Σ(c,d), em vez de
   módulos separados.
3. Medir um desfecho de **resiliência/recuperação sob perturbação**, não apenas
   previsão de um passo.
4. Pré-registrar poder, tamanho de efeito mínimo e critérios de falsificação.
5. Análise cega e replicação independente.

## Arquivos

| Arquivo | O que é |
|---|---|
| `research/tci/MAKTUB_ANALISE_TCI_TEORIA_TESTES.txt` | Síntese teórica do projeto. |
| `research/tci/AUDITORIA_REDTEAM_V19_FASE_A.md` | Auditoria completa (REPROVADO). |
| `research/tci/PROTOCOLO_V19_DESACOPLAMENTO.md` | Protocolo do V19. |
| `research/tci/FASE_B_V19.md` | Resultados da Fase B. |
| `research/tci/DEFINICAO_D_E_ESTABILIDADE_V19.md` | Definições matemáticas. |
| `research/tci/CALIBRACAO_NUMERICA_V19.md` | Calibração numérica do Σ. |
| `research/tci/run_v19_fase_b.py` | Script histórico (caminhos adaptados). |
| `research/tci/run_v19_numeric_stability.py` | Script histórico (caminhos adaptados). |
| `research/tci/registros_v19_fase_b.json` | Registros da Fase B. |
| `research/tci/registros_v19_estabilidade.json` | Registros de estabilidade. |

**Não incluído:** o corpus bruto `MAKTUB_TCI_EBIDT_TAFA.txt` (48.796 linhas,
2,3 MB) e a conversa informal de formalização. A síntese e a auditoria cobrem o
que é necessário para entender o veredito.

## Como citar

Se você citar este material, cite como **tentativa de operacionalização da TCI
reprovada por auditoria**, não como validação. Exemplo:

> “O V19 tentou operacionalizar Φ_MIP × Σ; a auditoria interna reprovou o
> desenho por erro de constructo e independência tautológica. O resultado é
> negativo/metodológico.”
