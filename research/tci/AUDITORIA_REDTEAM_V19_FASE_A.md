# OS029 — AUDITORIA RED TEAM DO V19 / FASE A

**Classificação:** auditoria somente leitura
**Execução experimental:** não autorizada
**Alteração de código:** não autorizada
**Chamadas a modelos/APIs:** não autorizadas
**GPU / Kaggle / rede:** não autorizados
**Data:** 2026-11-04
**Escopo:** V19 — Fase B executada; Fase A não executada.

**Condição final:**

```
AUDITORIA CONCLUÍDA — PARECER EMITIDO — FASE A NÃO AUTORIZADA
```

Nenhuma simulação, benchmark, chamada externa, tokenização ou alteração de artefato foi executada. Todo o trabalho foi leitura e análise estática dos arquivos listados na §2.

---

## 1. Resumo executivo

O V19 tem duas partes com estatutos muito diferentes:

1. **Fase B (executada):** calibração dos instrumentos em **módulos separados**. Ela tem valor metodológico real: as kernels construídas são reversíveis/irreversíveis como pretendido, os estimadores de TE e de produção de entropia são matematicamente corretos, e a calibração numérica do Σ é sólida. Mas a Fase B **não testa independência no mesmo sistema causal**: ela simula os módulos separadamente e calcula a “contaminação” como diferença de um valor com ele mesmo. O zero é tautológico.

2. **Fase A (não executada):** existe apenas como protocolo. Não há código, dados, pré-registro, tamanho amostral, poder, pools independentes ou parâmetros fechados. Pior: a estrutura causal especificada torna a interação **não identificável**. Com `O_t = f(phi_t)` e um relógio exógeno aos bits, o parâmetro `c` (Φ) **não tem caminho causal** até o desfecho `Y1`. A interação `Δ_int` é zero por construção, não por evidência.

O problema de constructo também é central: a TCI define Φ como **Φ_MIP** (bipartição + D_KL), mas o V19 operacionaliza Φ como **transferência de entropia (TE)**. TE mede dependência preditiva direcional; não é irreducibilidade causal. O protocolo não demonstra equivalência. A própria documentação teórica do projeto registra a diferença, e a formalização posterior redefine Φ como TE — ou seja, há **duas definições concorrentes** no corpus, e o V19 adota uma delas sem resolver o conflito.

**Parecer:** `REPROVADO — ERRO DE CONSTRUCTO OU DESENHO`.

A Fase B pode ser preservada como calibração estreita de instrumentos. O V19 **não** pode ser autorizado como teste da TCI, e a Fase A **não** pode ser executada na forma atual.

### 1.1 Painel de vereditos

| Bloco | Veredito |
|---|---|
| Fase B — kernels construídas (reversibilidade) | **PASS** |
| Fase B — separabilidade dos níveis | **PASS** |
| Fase B — independência no mesmo sistema | **FAIL** |
| Fase B — contaminação cruzada | **FAIL** |
| Fase B — estimador empírico | **PARTIAL** |
| Fase B — proveniência dos artefatos | **NOT_VERIFIABLE** |
| Fase A — implementação | **NOT_VERIFIABLE** |
| Fase A — estrutura causal | **FAIL** |
| Fase A — identificação da interação | **FAIL** |
| Fase A — desfecho primário | **FAIL** |
| Fase A — estatística | **FAIL** |
| V19 como teste da TCI | **REPROVADO** |

---

## 2. Inventário dos arquivos examinados

Todos os arquivos foram lidos em modo somente leitura. Os hashes abaixo foram calculados nesta auditoria; não havia manifesto V19 prévio que os registrasse.

| Arquivo | Linhas | SHA-256 | Papel | Fonte de verdade para |
|---|---:|---|---|---|
| `PROTOCOLO_V19_DESACOPLAMENTO.md` | 225 | `e3ae2dd66aad73e8be28214d4996018b6fe820a71c97675cd2cc55d255116520` | protocolo | definições operacionais, Fase A, critérios |
| `DEFINICAO_D_E_ESTABILIDADE_V19.md` | 182 | `b3e898cdd373c0f4beb923e0c22a4b613326391c8149e769d5214bb311760378` | definição matemática | D-relógio, processo conjunto, Σ |
| `CALIBRACAO_NUMERICA_V19.md` | 44 | `44db74ae24531433e369e54f3ee68122bcecaf23c87780cbf3443b7b5d8483cc` | calibração | tolerâncias numéricas |
| `FASE_B_V19.md` | 91 | `1269062a407045c2cfb57864223b85c01c9f01dd4173901ca053942e20226dc1` | relatório B | resultados da Fase B |
| `run_v19_fase_b.py` | 408 | `b777eb30083ff73ad3d29315ecdc13eda96c651d3f30efc771f261755c857edb` | código B | implementação dos estimadores |
| `run_v19_numeric_stability.py` | 298 | `7720fc19a11ea7ef3310e34c2270168bfabdcb602564940852d6571f904ec6be` | código de calibração | referência de alta precisão |
| `registros_v19_fase_b.json` | 560 | `97386d631574b1197a67d344c1e57a9e4d0855a49b83e25409c5131e80dc2b36` | dados B | valores por célula |
| `registros_v19_estabilidade.json` | 315 | `a34ade914206acd1595e040f372d69ed9824baa5408967af493d980df55fb52c` | dados de calibração | diagnósticos por matriz |
| `MAKTUB_ANALISE_TCI_TEORIA_TESTES.txt` | 67 | `f8d831358434dd6eec511f1c23f9dc8ae995e180fc3931964434d4dfa03e5a36` | referência teórica | definição de Φ_MIP e do teste da TCI |
| `FORMALIZACAO_TCIF_P1_P3_RAW.md` | 15 | `3ec7748da009995606ad7201b08da1fe3285421a2e52ca1a15a84b9523a07f6d` | formalização posterior | definição concorrente de Φ como TE |

**Arquivos ausentes (procurados e não encontrados):**

- `run_v19_fase_a.py` ou equivalente;
- `PRE_REGISTRO_V19*.md/json`;
- `registros_v19_fase_a.json`;
- o “ADENDO 13” citado em `run_v19_fase_b.py:6`;
- qualquer dado de `T=20000` que sustente os valores `0,872` e `8,88` citados em `FASE_B_V19.md:59-60`.

**Não examinado integralmente:** o corpus histórico `MAKTUB_TCI_EBIDT_TAFA.txt` (48.796 linhas) não foi lido linha a linha; a auditoria usou a síntese do próprio projeto (`MAKTUB_ANALISE_TCI_TEORIA_TESTES.txt`) para a definição teórica. Se houver definições conflitantes no corpus bruto, elas não foram avaliadas aqui.

**Observação de proveniência:** o `registros_v19_fase_b.json` contém os campos `verdict_construct`, `verdict_empirical`, `verdict_overall`, `empirical_phi_tracking` e `empirical_sigma_tracking` (linhas 556-560), que **não existem** no `run_v19_fase_b.py` preservado. O relatório `FASE_B_V19.md` também contém a seção “Ressalva Empírica nos Extremos Determinísticos” (linhas 57-61), que não é gerada pelo script. Portanto, o JSON e o relatório foram produzidos por uma **versão não preservada** do script, ou editados manualmente depois. A proveniência exata não é verificável.

---

## 3. Definições matemáticas recuperadas

### 3.1 Φ

**Definição teórica da TCI (fonte: `MAKTUB_ANALISE_TCI_TEORIA_TESTES.txt:12`):**

> “Irredutibilidade Causal (medida via Φ_MIP — Integrated Information/Causal Irreducibility).”
> “Φ_MIP: Bipartição cirúrgica {bit1} | {bit2}, cortando acoplamento cruzado e medindo D_KL(P_joint || P_bit1 × P_bit2) com Laplace smoothing (1e-12).” (`:42`)

**Definição operacional do V19 (fonte: `PROTOCOLO_V19_DESACOPLAMENTO.md:65-73`):**

```
TE(X->Y) = Σ p(x_t,y_t,y_{t+1}) log[ p(y_{t+1}|x_t,y_t) / p(y_{t+1}|y_t) ]
Phi_TCI = 0,5 · [ TE(b1->b2) + TE(b2->b1) ]
```

Unidade: bits (divisão por `ln 2` em `run_v19_fase_b.py:117`).

**Implementação:** `te_exact` em `run_v19_fase_b.py:89-117`; `te_empirical` em `:143-175`.

**Pressupostos:**

- cadeia de Markov de 2 bits, 4 estados;
- estacionariedade;
- `pi` uniforme — **hardcoded** em `run_v19_fase_b.py:90` (`pi = np.ones(4)/4.0`), não calculado de `P`;
- suavização empírica `alpha=1e-6` (`:143`);
- `pi` empírico obtido da soma das colunas das contagens (`:148`), não da estacionária de `P`.

**Limitação central:** TE não é Φ_MIP. TE mede quanto o passado de X reduz a incerteza sobre o futuro de Y; Φ_MIP mede a perda de informação causal sob uma partição do sistema. São quantidades diferentes, com propriedades diferentes. O protocolo **não demonstra** que uma seja proxy da outra. A formalização posterior (`FORMALIZACAO_TCIF_P1_P3_RAW.md:11`) redefine Φ como TE, mas essa é uma **segunda definição**, não uma prova de equivalência. O corpus fica com duas fontes de verdade concorrentes.

**Relação teórico vs empírico:** o valor construído é exato para a kernel; o empírico é uma estimativa de TE a partir de trajetórias. No regime intermediário, o empírico acompanha o teórico; em `c=1`, subestima gravemente (§4.6).

### 3.2 Σ

**Definição operacional (fonte: `PROTOCOLO_V19_DESACOPLAMENTO.md:40-59`):**

```
P_rev(i,j) = pi_j · P_fwd(j,i) / pi_i
Sigma_irrev = Σ_{i∈S+} pi_i Σ_j P_fwd(i,j) log( P_fwd(i,j) / P_rev(i,j) )
```

Unidade: nats por transição.

**Implementação:** `sigma_exact` em `run_v19_fase_b.py:72-86`; `sigma_empirical` em `:178-195`.

**Pressupostos:**

- cadeia de Markov com estacionária única;
- suporte completo (`S+` = todos os estados com `pi_i>0`);
- `0 log(0/·) = 0`;
- se `P_ij>0` e `P_rev_ij=0`, Σ=∞ — a kernel não é reversível e isso deve ser reportado, não mascarado (`PROTOCOLO:58-59`).

**Limitação:** Σ é uma medida legítima de **irreversibilidade temporal** (produção de entropia / KL entre processo direto e reverso). Não é memória, e não implica retenção. A afirmação da formalização de que “Σ→0 ⇒ amnésia” (`FORMALIZACAO_TCIF_P1_P3_RAW.md:11`) é uma hipótese adicional, não uma consequência da definição. O V19 não a testa.

**Relação teórico vs empírico:** o valor construído é exato; o empírico usa `alpha=1.0` (`:178`) e `pi` da soma das colunas (`:183`). A suavização de Laplace α=1,0 é grande para T=1000 e enviesa Σ para baixo, especialmente em `d=1` (§4.6). O protocolo não declara α=1,0; ele só declara `eps_c`/`eps_cyc`.

### 3.3 Processo medido e módulos

**Fase B:** estado `(I1,I2,R1,R2)`; os módulos evoluem independentemente. Φ é medido no módulo `I=(I1,I2)`; Σ no módulo `R=(R1,R2)` (`PROTOCOLO:75-84`). O próprio protocolo diz: “Isso é uma definição de medição por módulo, não o Phi/Sigma do sistema completo” (`:80-81`).

**Fase A:** estado `Z=(b1,b2,phi)`, `phi ∈ Z_4`. A transição é

```
P_Z((b,phi) -> (b',phi')) = P_clock(phi,phi') · P_bits(b -> b' | phi)
```

(`DEFINICAO_D_E_ESTABILIDADE_V19.md:45-56`). O relógio é exógeno aos bits; não há realimentação dos bits para o relógio. O documento chama isso de “produto semi-dirigido” (`:49`). O caminho causal é apenas `phi -> g_phi -> b_{t+1}` (`:92-99`).

### 3.4 Conflitos de fonte de verdade

| Constructo | Fonte A | Fonte B | Conflito |
|---|---|---|---|
| Φ | `MAKTUB_ANALISE_TCI_TEORIA_TESTES.txt:12,42` — Φ_MIP | `PROTOCOLO:65-73` — TE média | Definições não equivalentes; nenhuma prova |
| Φ | `FORMALIZACAO_TCIF_P1_P3_RAW.md:11` — TE | `MAKTUB_ANALISE...:12` — Φ_MIP | Duas definições no mesmo corpus |
| Σ | `MAKTUB_ANALISE...:16` — quebra de reversibilidade | `PROTOCOLO:40-59` — produção de entropia | Compatíveis em espírito; a ligação com retenção não é demonstrada |
| Fase B | `run_v19_fase_b.py` | `registros_v19_fase_b.json` | JSON tem campos que o script não gera |
| Fase B | `registros_v19_fase_b.json:558` — PASS/PASS | `FASE_B_V19.md:61` — PASS/PARTIAL | Contradição direta |

---

## 4. Auditoria da Fase B

### 4.1 O que foi executado

Parâmetros: `T=1000`, `burn=100`, `N_SEEDS=200`, `P_FLIP=0.1`, `EPS_X=1e-3`, `EPS_CYC=1e-3` (`run_v19_fase_b.py:8-20`). Grid de Φ: `C_GRID = [0.0, 0.35, 0.60, 0.80, 1.00]` (`:19`). Grid de Σ: `D_GRID = [0.0, 0.25, 0.50, 0.75, 1.00]` (`:20`).

**Desvio de protocolo:** o protocolo define `c ∈ {0, 0.25, 0.50, 0.75, 1.00}` (`PROTOCOLO:93`). O código usa `0.35, 0.60, 0.80`. Não há emenda, pré-registro ou justificativa documentada para a troca. Isso impede saber se a grade foi escolhida antes ou depois de ver os incrementos.

### 4.2 Gate de reversibilidade (kernel construída)

| kernel | `db_error` | `sigma` | simétrica |
|---|---:|---:|---|
| `phi_c0.00` | 2.429e-17 | 3.081e-33 | True |
| `phi_c0.35` | 1.735e-17 | -3.252e-18 | True |
| `phi_c0.60` | 2.255e-17 | -1.152e-19 | True |
| `phi_c0.80` | 6.072e-18 | 9.492e-19 | True |
| `phi_c1.00` | 2.643e-18 | 6.939e-21 | True |
| `sigma_d0.00` | 2.429e-17 | 3.081e-33 | True |

**Veredito:** PASS para o que foi checado. As kernels rotuladas reversíveis são simétricas e têm `db_error ~ 1e-17`, `Sigma ~ 1e-18` ou menos. A calibração numérica independente confirma que `eps_db=1e-12` e `eps_Sigma=1e-10` ficam acima do ruído de máquina (`CALIBRACAO_NUMERICA_V19.md:7-14`; `DEFINICAO:108-164`).

**Ressalva:** o gate implementado é mais estreito que o protocolo. O protocolo exige, para todo `c` e `d`, `pi P = pi` e `P_rev` linha-estocástica no suporte (`PROTOCOLO:118`). O código checa apenas `db_error`, `sigma` e `symmetric` (`run_v19_fase_b.py:209-226`); não checa a estacionariedade nem a soma das linhas de `P_rev` para as kernels de Σ com `d>0`. As kernels de teste passam, mas o gate declarado não foi integralmente implementado.

### 4.3 Separabilidade dos níveis

| c | Φ teórico (bits) | incremento |
|---|---:|---:|
| 0.00 | 0.0000 | — |
| 0.35 | 0.1317 | 0.1317 |
| 0.60 | 0.3315 | 0.1998 |
| 0.80 | 0.5691 | 0.2376 |
| 1.00 | 0.9938 | 0.4247 |

| d | Σ teórico (nats) | incremento |
|---|---:|---:|
| 0.00 | 0.0000 | — |
| 0.25 | 0.6336 | 0.6336 |
| 0.50 | 1.7683 | 1.1347 |
| 0.75 | 3.4320 | 1.6637 |
| 1.00 | 8.2850 | 4.8530 |

**Veredito:** PASS. `min(ΔΦ)=0.1317 ≥ 0.10` e `min(ΔΣ)=0.6336 ≥ 0.20`. A separabilidade dos níveis **construídos** é real.

### 4.4 “Independência”: o teste é tautológico

Este é o problema central da Fase B.

O código calcula os efeitos principais teóricos assim:

```python
me_c_phi = np.mean([phi_theory[1.0] - phi_theory[0.0] for _ in D_GRID])   # :268
me_d_phi = np.mean([phi_theory[c] - phi_theory[c] for c in C_GRID])        # :269  -> 0
me_d_sig = np.mean([sig_theory[1.0] - sig_theory[0.0] for _ in C_GRID])   # :270
me_c_sig = np.mean([sig_theory[d] - sig_theory[d] for d in D_GRID])        # :271  -> 0
```

`me_d_phi` é a média de `phi_theory[c] - phi_theory[c]`, ou seja, **zero por construção**. `me_c_sig` é a média de `sig_theory[d] - sig_theory[d]`, também zero por construção. A “contaminação” `C_d->Phi` e `C_c->Sigma` é, portanto, uma divisão de zero por um efeito, não uma medida de contaminação.

O mesmo ocorre no empírico:

```python
traj_i = simulate(phi_kernels[c], r)   # :241
traj_r = simulate(sig_kernels[d], r)   # :242
```

Cada célula `(c,d)` reinicia o RNG com a mesma seed (`:240`). Logo, para um dado `c`, `traj_i` é **idêntica** em todos os `d`; para um dado `d`, `traj_r` é **idêntica** em todos os `c`. As 25 células são um produto cartesiano de 5 trajetórias de Φ e 5 de Σ, não 25 experimentos independentes. A tabela de células (`FASE_B_V19.md:67-91`) mostra exatamente isso: `Phi emp` é constante ao longo de cada linha, e `Sigma emp` é constante ao longo de cada coluna.

**Consequência:** a Fase B **não testa** independência no mesmo sistema causal. Ela mede dois módulos separados e calcula uma diferença que é zero por construção. O “PASS de independência” (`FASE_B_V19.md:52`) é vacuous. Isso seria aceitável se o relatório dissesse “separabilidade por módulo”; não é aceitável como “independência instrumental” no sentido da TCI.

**Pseudo-replicação:** as 25 células contêm apenas 5 níveis independentes de Φ e 5 de Σ. O N efetivo para o efeito de `c` é 200 trajetórias, não 25 × 200. Os intervalos por célula não são 25 réplicas independentes.

### 4.5 Contaminação cruzada: o módulo Σ gera TE

O código calcula `phi_sig_module_theory` (`run_v19_fase_b.py:231`), o TE do módulo de Σ. O relatório mostra esses valores na coluna “Phi do módulo Sigma” (`FASE_B_V19.md:20-31`):

| d | Φ do módulo Σ (bits) | comparação com `delta_Phi=0.10` |
|---|---:|---|
| 0.00 | 0.0000 | 0% |
| 0.25 | 0.0374 | 37% |
| 0.50 | 0.1206 | **121%** |
| 0.75 | 0.2504 | **250%** |
| 1.00 | 0.4969 | **497%** |

O protocolo é explícito: “verificar numericamente ... que Phi_R(d) ~ 0 (o ciclo nao deve gerar TE cruzada; **se gerar, reportar e nao usar B como calibrador de Phi**)” (`PROTOCOLO:108-110`).

O valor foi reportado, mas a classificação **não** seguiu a instrução: `FASE_B_V19.md:52` marca “Independencia: PASS” e `:55` marca “Overall PASS”. Para `d ≥ 0.50`, o próprio módulo de Σ gera TE acima do efeito mínimo de Φ (0,12–0,50 bits, ou 1,2–5,0 vezes `delta_Phi`). A contaminação exata no sistema combinado não foi medida; o que se pode afirmar é que o módulo Σ **não é Φ-neutro**, e o protocolo já previa que isso invalidaria o uso de B como calibrador de Φ.

**Veredito:** FAIL para a afirmação de que o instrumento Σ é Φ-neutro. A Fase B demonstra o contrário da instrução do protocolo.

**Ressalva importante:** a Fase A não usa o ciclo Qcyc; usa o relógio `P_clock`. A contaminação do relógio sobre Φ **não foi medida**. Portanto, a Fase A pode ou não ter contaminação; o que se pode afirmar é que a Fase B **não** estabelece isso. Para a Fase A, o critério de 20% é `NOT_VERIFIABLE`.

### 4.6 Precisão do estimador empírico

Critério do protocolo para a estimativa empírica: IC95% bootstrap deve conter o valor teórico (`DEFINICAO:162-164`).

**Problema metodológico:** o código não faz bootstrap. Ele usa percentis da distribuição entre as 200 seeds:

```python
"phi_ci": [np.percentile(phi_vals, 2.5), np.percentile(phi_vals, 97.5)]   # :254-255
"sigma_ci": [np.percentile(sig_vals, 2.5), np.percentile(sig_vals, 97.5)] # :257-258
```

Isso é um intervalo de **95% da distribuição entre seeds**, não um IC da média. O IC da média seria mais estreito por um fator ~√200. O relatório chama esses intervalos de “IC95” (`FASE_B_V19.md:65-91`), mas eles não são o IC bootstrap que o protocolo exige.

Ainda assim, usando os intervalos do próprio relatório, o estimador empírico falha em vários pontos:

**Φ:**

| c | Φ teórico | Φ empírico | IC do relatório | Teórico dentro? |
|---|---:|---:|---|---|
| 0.00 | 0.0000 | 0.0014 | [0.0001, 0.0037] | **Não** |
| 0.35 | 0.1317 | 0.1305 | [0.0986, 0.1583] | Sim |
| 0.60 | 0.3315 | 0.3266 | [0.2805, 0.3688] | Sim |
| 0.80 | 0.5691 | 0.5476 | [0.4754, 0.6011] | Sim |
| 1.00 | 0.9938 | 0.2081 | [0.0000, 0.7601] | **Não** |

**Σ:**

| d | Σ teórico | Σ empírico | IC do relatório | Teórico dentro? |
|---|---:|---:|---|---|
| 0.00 | 0.0000 | 0.0050 | [0.0004, 0.0154] | **Não** |
| 0.25 | 0.6336 | 0.5894 | [0.4582, 0.7366] | Sim |
| 0.50 | 1.7683 | 1.6104 | [1.3594, 1.9020] | Sim |
| 0.75 | 3.4320 | 3.0516 | [2.6233, 3.3901] | **Não** |
| 1.00 | 8.2850 | 5.3840 | [5.1442, 5.4374] | **Não** |

Observações:

- O erro em `c=1` é de −79,1% (0,208 vs 0,994). O relatório reconhece a limitação (`FASE_B_V19.md:59`), mas ainda marca “Estimador Empírico: PASS” (`:54`).
- O erro em `d=1` é de −35,0% (5,384 vs 8,285). O relatório reconhece (`:60`).
- O erro em `d=0,75` é de −11,1% (3,052 vs 3,432). **O relatório não menciona** que `d=0,75` também falha o critério “IC contém o teórico”. Ele trata apenas `d=1` como extremo.
- Os controles negativos (`c=0`, `d=0`) têm viés positivo pequeno, mas os ICs **excluem zero**. Pelo critério estrito do protocolo, eles também falham. O relatório não discute esse viés de fundo.
- Os valores `T=20000 → 0,872` e `T=20000, α=0,1 → 8,88` (`FASE_B_V19.md:59-60`) **não têm artefato preservado**. São `NOT_VERIFIABLE`.
- A média empírica `ME_c_phi=0,2067` (`registros_v19_fase_b.json`) é 79,2% menor que a teórica `0,9938`; isso é dominado por `c=1`. O relatório mostra a discrepância, mas não a usa para rebaixar o veredito empírico.

**Veredito:** PARTIAL. O estimador é bom no regime intermediário; falha nos extremos e nos controles negativos sob o critério do próprio protocolo. A linha `:61` (“PASS (construct) / PARTIAL (empirical extremes)”) é a mais correta; as linhas `:54-55` e o JSON `:558` são overclaims.

### 4.7 Controles negativos e extremos

- **Controle negativo construído:** PASS. `P0` e `Q0` são reversíveis; `Sigma` construído ~1e-33.
- **Controle negativo empírico:** PARTIAL. `Phi_emp(c=0)=0,0014` e `Sigma_emp(d=0)=0,0050`; os ICs excluem zero. O viés é pequeno em relação a `delta`, mas existe e não é discutido.
- **Extremos determinísticos:** PARTIAL. `c=1` e `d=1` são reconhecidos; `d=0,75` não. A explicação de mistura lenta (`τ~1/ε=1000`) é plausível para `c=1`; para Σ, a suavização α=1,0 também contribui.
- **Concordância construído vs estimado:** PARTIAL. Excelente para `c ≤ 0,8` e `d ≤ 0,5`; falha em `c=1`, `d=0,75`, `d=1`.

### 4.8 Consistência dos artefatos da Fase B

Há uma contradição direta entre os artefatos:

| Fonte | Afirmação |
|---|---|
| `FASE_B_V19.md:54` | “Veredito Estimador Empirico: **PASS** (limitação em c=1 e d=1)” |
| `FASE_B_V19.md:55` | “**Veredito Overall: PASS (construct) / PASS (empirical extremes)**” |
| `FASE_B_V19.md:61` | “a Fase B está **PASS (construct) / PARTIAL (empirical extremes)**” |
| `registros_v19_fase_b.json:556-558` | `verdict_construct=PASS`, `verdict_empirical=PASS`, `verdict_overall="PASS (construct) / PASS (empirical extremes)"` |

Além disso:

- `empirical_phi_tracking: true` (`registros_v19_fase_b.json:559`) contradiz os próprios dados: `Phi_emp` sobe até `0,5476` em `c=0,8` e **cai** para `0,2081` em `c=1,0`. Não é monotônico; “tracking” não é verdadeiro no sentido usual.
- O script preservado não contém os campos extras nem a seção “Ressalva Empírica”. A seção de classificação com “Veredito Construto / Estimador Empírico / Overall” também não é gerada pelo script; ele escreve apenas `Veredito: {verdict}` (`run_v19_fase_b.py:388`). O JSON e o relatório não são reproduzíveis a partir dele.
- O relatório diz “mean 0.202” para `c=1` (`FASE_B_V19.md:59`), mas o JSON diz `0,2081`. Pequena divergência, mas indica edição manual ou versão diferente.

**Veredito:** NOT_VERIFIABLE para a proveniência; FAIL para a consistência interna da classificação. Não há uma fonte de verdade única para o veredito da Fase B.

### 4.9 Veredito da Fase B

| Item | Status |
|---|---|
| Kernels construídas reversíveis/irreversíveis | PASS |
| Separação dos níveis construídos | PASS |
| Gate completo (estacionariedade, P_rev) | PARTIAL |
| Independência no mesmo sistema | FAIL |
| Contaminação Σ→Φ | FAIL |
| Precisão empírica no regime intermediário | PASS |
| Precisão empírica nos extremos | PARTIAL |
| Controles negativos empíricos | PARTIAL |
| Consistência relatório/JSON/script | FAIL |
| Proveniência | NOT_VERIFIABLE |

**Conclusão da Fase B:** ela é uma **calibração estreita e útil de instrumentos separados**, não uma validação de independência Φ×Σ. O “PASS” global não se sustenta.

---

## 5. Auditoria da Fase A

### 5.1 Existência

Não há implementação. O protocolo declara “NAO implementado, sem dados, sem sobrevivencia” (`PROTOCOLO:3`). Não há `run_v19_fase_a.py`, `registros_v19_fase_a.json` nem pré-registro. Os parâmetros `lambda`, `eps_c`, `g_phi` e `f(phi)` continuam em aberto (`PROTOCOLO:224-225`; `DEFINICAO:177-182`).

**Veredito:** NOT_VERIFIABLE para tudo que depende de execução. A auditoria só pode avaliar o desenho no papel.

### 5.2 Estrutura causal

O sistema é `Z=(b1,b2,phi)` com

```
P_Z((b,phi)->(b',phi')) = P_clock(phi,phi') · P_bits(b->b'|phi)
```

(`DEFINICAO:45-56`). O relógio é exógeno: `phi_{t+1}` depende só de `phi_t`, não de `b_t`. Os bits não realimentam o relógio. O documento chama isso de “produto semi-dirigido” (`:49`) e afirma que “os dois mecanismos atuam sobre o mesmo sistema causal, permitindo interacao” (`PROTOCOLO:137-138`).

**Problema:** compartilhar o espaço de estados não é o mesmo que compartilhar influência causal. A estrutura é modular: `phi -> bits`, sem `bits -> phi`. O único acoplamento é unidirecional. Isso pode gerar dependência estatística, mas não garante uma interação identificável no desfecho.

### 5.3 O problema fatal: `O_t = f(phi_t)` torna `c` irrelevante

O protocolo define:

- `Y1`: prever `O_{t+1}` a partir de `S_t` (acurácia ou `I(S_t;O_{t+1})`) (`PROTOCOLO:143-147`);
- `O_t = f(phi_t)`, com `f` fixo antes dos dados (`DEFINICAO:92-99`).

Derivação:

1. `O_{t+1} = f(phi_{t+1})`.
2. `phi_{t+1}` depende apenas de `phi_t` via `P_clock`; não depende de `b_t`.
3. Logo, condicionado a `phi_t`, `O_{t+1}` é independente de `b_t`.
4. Portanto, `I((b_t,phi_t); O_{t+1}) = I(phi_t; O_{t+1})`.
5. Essa expressão depende de `P_clock` (`lambda`, `eps_c`, `d`) e **não de `c`** nem de `P_bits`.
6. Logo, `∂Y1/∂c = 0` para todo `d`; no modelo linear, `β1 = 0` e `β3 = 0`.
7. Logo, `Δ_int = Y(1,1)-Y(1,0)-Y(0,1)+Y(0,0) = 0` **por construção**.

Isso vale para qualquer `f`, inclusive não injetora: a independência condicional é preservada. A conclusão não depende de simulação; é uma propriedade da fatoração especificada.

Há ainda uma ambiguidade de notação: o protocolo usa `S_t` tanto para o estado de bits quanto para o estado aumentado `Z_t=(S_t,phi_t)`. Nas duas leituras, `c` não entra. Se `S_t` denota o estado aumentado, `O_{t+1}` depende só de `phi_t`; se denota apenas os bits, `O_{t+1}` é independente de `S_t`. Em nenhuma delas a kernel de bits — e, portanto, `c` — afeta a previsão de `O_{t+1}`.

**Consequência:** a Fase A, como está escrita, não pode detectar interação Φ×Σ em `Y1`. Se `S_t` incluir `phi_t`, o resultado esperado é “só efeito de Σ” (`β2>0`, `β3=0`); se `S_t` for só os bits, o desfecho é ainda mais degenerado. Em ambos os casos, `β1=β3=0`, independentemente de a TCI ser verdadeira. Se o protocolo interpretar esse zero como refutação, ele refutará a TCI por um artefato de desenho.

**Para a interação existir**, o desfecho teria que depender também de `b` (por exemplo, `O_t = f(b_t,phi_t)`), ou o relógio teria que receber realimentação dos bits. Nenhuma das duas coisas está no protocolo. O exemplo `O_t = f(phi_t)` é o único especificado.

### 5.4 Definição da interação

O protocolo define:

```
Y(c,d) = beta0 + beta1 c + beta2 d + beta3 c d + erro
Delta_int = Y(1,1) - Y(1,0) - Y(0,1) + Y(0,0)
```

(`PROTOCOLO:151-157`).

**Problemas:**

1. **Interação nos knobs, não nos constructos.** `c` e `d` são parâmetros de sintonia, não Φ e Σ medidos. A hipótese é sobre Φ×Σ; o teste é sobre `c×d`. Se Φ(c) e Σ(d) forem não lineares — e são: incrementos de Φ variam de 0,1317 a 0,4247; de Σ, de 0,6336 a 4,8530 —, `β3` em `c,d` não é o coeficiente de interação em Φ,Σ. O protocolo não verifica linearidade nem ajusta o modelo em Φ_hat,Σ_hat.
2. **Contraste só nos extremos.** `Δ_int` usa apenas `(1,1),(1,0),(0,1),(0,0)`, ignorando os níveis intermediários da grade 5×5. O modelo linear usa todos, mas assume linearidade; o contraste de extremos não.
3. **Não identificabilidade.** Como `Y1` depende só de `d`, `β1=β3=0`. A interação não é identificável no desenho atual.
4. **Confundidores.** O relógio é exógeno; `d` altera a ordem temporal da gating, mas não a média. A afirmação de que “c controla Phi e d controla Sigma no leading order” (`PROTOCOLO:139-141`) não foi verificada para o sistema da Fase A; a Fase B não constrói esse sistema. A contaminação de `d` sobre Φ no relógio é `NOT_VERIFIABLE`.

### 5.5 Desfechos dinâmicos

O protocolo só define `Y1` como previsão de um passo (`PROTOCOLO:143-147`). `Y2` e `Y3` são mencionados como “secundários/exploratórios” (`:146-147`), mas **não são definidos em nenhum lugar** do corpus V19.

Não há:

- **retenção** — memória ao longo de lags, persistência de informação, decaimento;
- **adaptabilidade** — resposta a perturbação, recuperação, mudança de política;
- **desfecho dinâmico** — o processo é uma cadeia estacionária, sem choque externo.

A teoria fala de “manter o atrator funcional sob perturbações externas (vento estocástico, ruído)” (`MAKTUB_ANALISE_TCI_TEORIA_TESTES.txt:13`). O V19 não tem perturbação, não tem atrator funcional, não tem recuperação. `Y1` é informação preditiva de um passo, não resiliência.

**Veredito:** FAIL. O desfecho primário não representa a previsão central da TCI. O pêndulo não entra nesta fase, mas a Fase A também não é uma medida de retenção/adaptabilidade; é uma medida de previsão em cadeia estacionária.

### 5.6 Estatística

| Item | Situação | Evidência |
|---|---|---|
| Tamanho amostral | não definido para a Fase A | `PROTOCOLO:151` só diz “5x5”; não há N |
| Poder | não calculado | nenhum arquivo |
| Unidade de análise | não definida | trajetórias vs passos de tempo |
| Seeds | não definidas para a Fase A | só a Fase B tem `N_SEEDS=200` |
| Pools independentes | não existem | nenhum arquivo |
| Multiplicidade | não definida | um primário, mas β1/β2 também seriam testados |
| IC | não definido para a Fase A | o da Fase B é percentil, não bootstrap |
| Exclusão | não definida | nenhum critério |
| Replicação | não exigida | `PROTOCOLO:211` permite “A PASS/PARTIAL” → pêndulo |

**Pseudo-replicação potencial:** se a Fase A usar T=1000 passos por seed e tratar cada passo como observação, o N efetivo não é `N_seeds × T`; os passos são dependentes. O protocolo não declara a unidade de análise. A Fase B já mostra o padrão: 25 células, mas apenas 5 níveis independentes de cada fator.

**Gate de escalada:** o protocolo diz “Se A PASS/PARTIAL: so entao acoplar o pendulo e rodar sobrevivencia” (`:211`). Isso permite escalar com um resultado **PARTIAL**, que inclui “IC inclui 0” (`:155`). Não há exigência de replicação independente antes do pêndulo. Isso é uma proteção fraca contra falso positivo e contra um resultado inconclusivo ser tratado como sucesso.

### 5.7 Regra de decisão: contradição lógica

O protocolo define:

- PASS: `|Delta_int| >= delta_int` **e** IC95% exclui 0 (`:154`);
- PARTIAL: direção correta, mas `|Delta_int| < delta_int` ou IC inclui 0 (`:155`);
- FAIL: `Delta_int <= 0` ou direção oposta (`:156`).

**Contradição:** se `Delta_int = -0,10` com IC `[-0,15,-0,05]`, então `|Delta_int| = 0,10 >= 0,05` e o IC exclui 0 → **PASS** pela primeira regra; mas `Delta_int <= 0` → **FAIL** pela terceira. As duas regras se contradizem. O uso de valor absoluto permite que uma interação **negativa** seja declarada PASS, o que é o oposto da previsão da TCI.

**PARTIAL** também é mal definido: se o IC inclui 0, não se pode afirmar “direção correta” com confiança. E não há teste de equivalência para distinguir “ausência de efeito” de “efeito menor que δ”.

**FAIL** trata `Delta_int <= 0` como falha, mas um resultado nulo com poder insuficiente deveria ser “inconclusivo”, não “falha”. Sem poder, o protocolo não distingue ausência de efeito de efeito menor que o mínimo relevante.

### 5.8 Veredito da Fase A

| Item | Status |
|---|---|
| Implementação | NOT_VERIFIABLE |
| Pré-registro | NOT_VERIFIABLE |
| Estrutura causal | FAIL |
| Identificação da interação | FAIL |
| Desfecho primário | FAIL |
| Estatística | FAIL |
| Regra de decisão | FAIL |
| Replicação | FAIL |

**Conclusão:** a Fase A não é executável na forma atual e, se fosse executada, não testaria a hipótese. O defeito não é de amostra; é de desenho e de constructo.

---

## 6. Problemas encontrados e evidências

### 6.1 CRÍTICOS

**C1 — Φ é operacionalizado como TE, não como Φ_MIP.**
- Evidência: `PROTOCOLO:65-73` (Φ_TCI = TE média); `MAKTUB_ANALISE_TCI_TEORIA_TESTES.txt:12,42` (Φ_MIP via bipartição e D_KL); `FORMALIZACAO_TCIF_P1_P3_RAW.md:11` (definição concorrente de Φ como TE).
- Impacto: o V19 pode testar uma hipótese TE×Σ, mas não a TCI definida como Φ_MIP×Σ. Não há prova de equivalência. Toda conclusão sobre “Φ” fica sem validade de constructo.

**C2 — `O_t = f(phi_t)` elimina o caminho causal de `c` para `Y1`.**
- Evidência: `PROTOCOLO:135-138` (caminho `phi -> g_phi -> bits`); `:143-147` (Y1); `DEFINICAO:92-99` (`O_t=f(phi_t)`).
- Impacto: `Δ_int=0` por construção. A interação não é identificável. Um resultado nulo seria artefato, não refutação.

**C3 — A “independência” da Fase B é tautológica.**
- Evidência: `PROTOCOLO:75-84` (módulos separados); `run_v19_fase_b.py:268-273` (`me_d_phi` e `me_c_sig` são diferenças de um valor com ele mesmo); `:282-289` (idem no empírico); `:240-244` (mesma seed por célula, trajetórias idênticas).
- Impacto: `C_d->Phi=0` e `C_c->Sigma=0` não são medidos; são impostos. A Fase B não valida independência no mesmo sistema.

**C4 — O módulo Σ gera TE acima de `delta_Phi`.**
- Evidência: `FASE_B_V19.md:20-31` (`Phi do módulo Sigma` = 0,1206 em d=0,5; 0,2504 em d=0,75; 0,4969 em d=1,0); `PROTOCOLO:108-110` (“se gerar, reportar e nao usar B como calibrador de Phi”); `run_v19_fase_b.py:231`.
- Impacto: o instrumento Σ não é Φ-neutro. A Fase B contradiz a instrução do próprio protocolo e ainda marca “Independencia: PASS”.

**C5 — A regra PASS/FAIL da interação é contraditória.**
- Evidência: `PROTOCOLO:154-156` (`|Delta_int| >= delta` e IC exclui 0 vs `Delta_int <= 0`).
- Impacto: uma interação negativa pode ser PASS ou FAIL, dependendo da cláusula. Não há critério direcional único. Isso permite “sucesso” independentemente do sinal.

**C6 — A Fase A não tem implementação, pré-registro, N, poder, pools ou parâmetros fechados.**
- Evidência: `PROTOCOLO:3` (“NAO implementado”); `:224-225` (lambda, eps_c, g_phi, f em aberto); `DEFINICAO:177-182`; ausência de `run_v19_fase_a.py`, `PRE_REGISTRO_V19*`, `registros_v19_fase_a.json`.
- Impacto: não há como executar nem auditar a Fase A como experimento. A autorização seria prematura.

### 6.2 ALTOS

**H1 — A Fase B não mede a contaminação da Fase A.**
- Evidência: `PROTOCOLO:139-141` (critério de 20% para o sistema da Fase A); a Fase B usa módulos separados e o ciclo Qcyc, não o relógio `P_clock`; não há dados da Fase A.
- Impacto: a afirmação de que `c` controla Φ e `d` controla Σ “no leading order” não foi verificada no sistema que será usado. É `NOT_VERIFIABLE`.

**H2 — O desfecho `Y1` não é retenção nem adaptabilidade.**
- Evidência: `PROTOCOLO:143-147`; `Y2/Y3` não definidos; `MAKTUB_ANALISE...:13` (resiliência sob perturbação).
- Impacto: o V19 mede previsão de um passo em cadeia estacionária; a TCI fala de resiliência sob perturbação. São fenômenos diferentes.

**H3 — A interação é definida em `c,d`, não em Φ,Σ medidos.**
- Evidência: `PROTOCOLO:151-157`; não linearidade dos níveis em `FASE_B_V19.md:33-35`.
- Impacto: `β3` em `c,d` não é o coeficiente de Φ×Σ. O contraste de extremos ignora os níveis intermediários.

**H4 — Não há poder, N, pools independentes ou replicação; PARTIAL basta para escalar.**
- Evidência: `PROTOCOLO:203-212`; `:211` (“A PASS/PARTIAL → pêndulo”); ausência de cálculo de poder.
- Impacto: o protocolo não distingue ausência de efeito, efeito menor que δ e resultado inconclusivo. Um PARTIAL pode autorizar o pêndulo.

**H5 — A grade de `c` diverge do protocolo.**
- Evidência: `PROTOCOLO:93` (`0,25/0,50/0,75`) vs `run_v19_fase_b.py:19` (`0,35/0,60/0,80`); `FASE_B_V19.md:20-31`.
- Impacto: não há emenda documentada; não se sabe se a grade foi escolhida antes ou depois de ver os incrementos. A pré-registração da Fase B fica comprometida.

**H6 — Os artefatos da Fase B são inconsistentes e não reproduzíveis.**
- Evidência: `FASE_B_V19.md:54-55` (PASS/PASS) vs `:61` (PASS/PARTIAL); `registros_v19_fase_b.json:556-560` (PASS/PASS + `empirical_phi_tracking=true`); o script preservado não gera esses campos; `Phi_emp` cai de 0,5476 (c=0,8) para 0,2081 (c=1,0), contradizendo “tracking”.
- Impacto: não há fonte de verdade única para o veredito. A proveniência é `NOT_VERIFIABLE`.

**H7 — Os ICs empíricos não são bootstrap.**
- Evidência: `run_v19_fase_b.py:254-258` (`np.percentile` das 200 seeds); `DEFINICAO:162-164` (IC95% bootstrap).
- Impacto: os intervalos são de dispersão entre seeds, não IC da média. O critério “IC contém o teórico” não foi aplicado como o protocolo define. A conclusão qualitativa de viés nos extremos continua válida, mas a inferência estatística está mal rotulada.

### 6.3 MODERADOS

**M1 — Gate incompleto.** `PROTOCOLO:118` exige `pi P = pi` e `P_rev` linha-estocástica para todo `c,d`; `run_v19_fase_b.py:209-226` só checa `db_error`, `sigma` e `symmetric`.

**M2 — Suavização empírica não declarada.** `te_empirical` usa `alpha=1e-6` (`:143`); `sigma_empirical` usa `alpha=1.0` (`:178`). O protocolo só declara `eps_c`/`eps_cyc`. O α=1,0 é a principal causa do viés de Σ em `d=1`.

**M3 — `pi` empírico inconsistente.** `te_empirical` e `sigma_empirical` usam `counts.sum(axis=0)/total` (`:148`, `:183`), não a estacionária de `P` nem a ocupação dos estados. A aproximação é assintótica, mas adiciona viés em T=1000.

**M4 — `te_exact` hardcoda `pi` uniforme.** `run_v19_fase_b.py:90`. Funciona para estas kernels (duplamente estocásticas), mas não é geral e não é verificado.

**M5 — Pseudo-replicação nas 25 células.** As células são um produto de 5 trajetórias de Φ e 5 de Σ; não são 25 réplicas. O N efetivo para cada efeito é 200, não 25×200.

**M6 — Multiplicidade e exclusão não definidas.** O protocolo não diz como corrigir β1/β2/β3, nem critérios de exclusão de trajetórias ou seeds.

**M7 — `eta²` ausente.** `PROTOCOLO:189` exige `eta²` da interação < 0,05; o código e o relatório não calculam `eta²`.

### 6.4 BAIXOS

**L1 — Rótulos de veredito inconsistentes.** `FASE_B_V19.md:54-55` vs `:61`; JSON `:556-558`. Correção editorial, mas afeta a leitura do gate.

**L2 — `empirical_phi_tracking: true` é falso.** Os dados mostram não monotonicidade em `c=1` (`FASE_B_V19.md:87`).

**L3 — `T=20000` sem artefato.** `FASE_B_V19.md:59-60` cita 0,872 e 8,88; não há JSON/dados preservados. `NOT_VERIFIABLE`.

**L4 — “ADENDO 13” ausente.** `run_v19_fase_b.py:6` referencia um adendo que não está no inventário.

**L5 — Divergência 0,202 vs 0,2081.** `FASE_B_V19.md:59` vs `registros_v19_fase_b.json`. Pequena, mas indica versão diferente.

**L6 — Referência “exata” é a matriz racionalizada.** `run_v19_numeric_stability.py:148-150` usa `Fraction(float(x)).limit_denominator(10**12)`. A referência é exata para a matriz racionalizada, não para a matriz analítica ideal. Para erro numérico, é adequado; para afirmar “exato”, é preciso qualificar.

---

## 7. Teste de refutabilidade

| # | Pergunta | Resposta |
|---|---|---|
| 1 | Qual resultado refutaria a previsão central da TCI operacional? | **Nenhum resultado da Fase A, como escrita, refutaria a TCI.** O desenho torna `c` irrelevante para `Y1` (§5.3); um `Δ_int=0` seria artefato. Além disso, a TCI teórica declara falsificação pelo **efeito principal de Φ** (`MAKTUB_ANALISE...:62`), enquanto o V19 testa **interação** (`PROTOCOLO:149-157`). São critérios diferentes. |
| 2 | Qual resultado indicaria somente efeito individual de Φ? | `β1>0` e `β3≈0`. No desenho atual, isso **não pode ocorrer** em `Y1`, porque `Y1` independe de `c`. Se ocorrer, indica vazamento/confundimento, não efeito de Φ. |
| 3 | Qual resultado indicaria somente efeito individual de Σ? | `β2>0` e `β3≈0`. **Esse é o resultado esperado** se `S_t` incluir `phi_t`, porque `Y1` depende só de `d`; se `S_t` for só os bits, o desfecho é ainda mais degenerado. Em nenhuma leitura `c` entra. Não suporta a interação da TCI. |
| 4 | Qual resultado indicaria interação sem consequência dinâmica? | `Δ_int>0` em `Y1`, mas `Y2/Y3` nulos. Como `Y2/Y3` não são definidos, o protocolo não operacionaliza esse caso. |
| 5 | Qual resultado indicaria consequência dinâmica sem interação? | `Y2/Y3` mudam, mas `Δ_int≈0`. Também não operacionalizado, pois `Y2/Y3` não existem. |
| 6 | Quais resultados seriam inconclusivos? | IC inclui 0; `|Δ_int|<δ`; estudo sem poder; estimador empírico com viés nos extremos (c=1, d=0,75, d=1); IC percentil em vez de bootstrap. O protocolo chama parte disso de “PARTIAL”, mas não define equivalência nem poder. |
| 7 | Existe interpretação que permitiria declarar sucesso independentemente dos resultados? | **Sim.** (a) `PASS` usa `|Delta_int|`, então uma interação negativa pode passar (`PROTOCOLO:154`). (b) `PARTIAL` basta para acoplar o pêndulo (`:211`), e `PARTIAL` inclui IC com 0 (`:155`). (c) O relatório da Fase B se declara PASS e PARTIAL ao mesmo tempo (`FASE_B_V19.md:54-55` vs `:61`), permitindo escolher o rótulo conveniente. (d) `Y2/Y3` podem ser usados como “secundários” sem definição, abrindo espaço para reinterpretação. |

---

## 8. Matriz de conformidade

Status: **PASS** = evidência suficiente no domínio testado; **PARTIAL** = evidência limitada ou ressalva relevante; **FAIL** = falha ou contradição; **NOT_VERIFIABLE** = evidência insuficiente/inacessível.

| Elemento | Status | Evidência | Problema |
|---|---|---|---|
| Definição de Φ | **FAIL** | `PROTOCOLO:65-73`; `MAKTUB_ANALISE...:12,42`; `FORMALIZACAO...:11` | TE não é Φ_MIP; duas definições concorrentes; sem prova de equivalência |
| Definição de Σ | **PASS** | `PROTOCOLO:40-59`; `DEFINICAO:58-72` | Produção de entropia é medida válida de irreversibilidade; não é memória, e a ligação com retenção é hipótese extra |
| Estimador de Φ | **PARTIAL** | `run_v19_fase_b.py:89-117`; `:143-175` | Fórmula de TE correta; `pi` uniforme hardcoded; `alpha=1e-6`; não mede Φ_MIP |
| Estimador de Σ | **PARTIAL** | `run_v19_fase_b.py:72-86`; `:178-195` | Exato correto; empírico com `alpha=1.0` e `pi` de colunas; viés em d=0,75 e d=1 |
| Independência instrumental | **FAIL** | `PROTOCOLO:75-84`; `run_v19_fase_b.py:268-273,282-289,240-244` | Teste tautológico; módulos separados; 25 células = 5×5, não 25 réplicas |
| Estrutura causal da Fase A | **FAIL** | `DEFINICAO:45-56`; `PROTOCOLO:135-138` | Produto semi-dirigido; relógio exógeno; bits não realimentam; “mesmo sistema” é nominal |
| Identificação da interação | **FAIL** | `PROTOCOLO:151-157`; `DEFINICAO:92-99` | `O=f(phi)` torna `c` irrelevante; `Δ_int=0` por construção; interação em c,d, não Φ,Σ |
| Desfecho primário | **FAIL** | `PROTOCOLO:143-147` | `Y1` é previsão de um passo; retenção/adaptabilidade não definidas; `Y2/Y3` inexistentes |
| Efeito mínimo relevante | **PARTIAL** | `PROTOCOLO:157,161-173` | `delta_int=0.05` é exemplo, sem justificativa; unidades ambíguas (acurácia vs informação) |
| Poder estatístico | **FAIL** | `PROTOCOLO:151`; ausência de cálculo | Sem N, variância, poder ou unidade de análise para a Fase A |
| Independência dos pools | **FAIL** | `PROTOCOLO:203-212`; nenhum arquivo | Não há pools independentes nem replicação; PARTIAL basta para escalar |
| Critérios de refutação | **FAIL** | `PROTOCOLO:154-156`; `:211`; `MAKTUB_ANALISE...:62` | `|Δ_int|` contradiz `Δ_int≤0`; sem equivalência; critério teórico é efeito principal de Φ, não interação |
| Fase B — separabilidade | **PASS** | `FASE_B_V19.md:20-35`; `run_v19_fase_b.py:229-231` | Incrementos acima de δ; válido para kernels construídas |
| Fase B — gate construído | **PARTIAL** | `run_v19_fase_b.py:209-226`; `PROTOCOLO:112-120` | `db_error`/`sigma` OK; faltam `piP=pi` e `P_rev` linha-estocástica para todo c,d |
| Fase B — contaminação | **FAIL** | `FASE_B_V19.md:20-31`; `PROTOCOLO:108-110` | Φ do módulo Σ chega a 0,4969 bits (5× `delta_Phi`); “Independencia: PASS” contraria o protocolo |
| Fase B — precisão empírica | **PARTIAL** | `FASE_B_V19.md:65-91`; `run_v19_fase_b.py:254-258` | Bom em c≤0,8/d≤0,5; falha em c=1, d=0,75, d=1; IC é percentil, não bootstrap |
| Fase B — controles negativos | **PARTIAL** | `FASE_B_V19.md:67,72,77,82,87` | `Phi_emp(c=0)=0,0014` e `Sigma_emp(d=0)=0,0050`; ICs excluem zero |
| Fase B — extremos | **PARTIAL** | `FASE_B_V19.md:57-61` | `T=20000` sem artefato; `d=0,75` não é discutido |
| Fase B — concordância construído vs estimado | **PARTIAL** | `FASE_B_V19.md:65-91` | Excelente no meio; falha nos extremos |
| Fase B — proveniência | **NOT_VERIFIABLE** | `registros_v19_fase_b.json:556-560`; `run_v19_fase_b.py` | JSON tem campos que o script não gera; relatório tem seção não gerada; versão não preservada |
| Fase A — implementação | **NOT_VERIFIABLE** | `PROTOCOLO:3`; ausência de arquivos | Não há código, dados ou pré-registro |
| Fase A — pré-registro | **NOT_VERIFIABLE** | `run_v19_fase_b.py:6` (“ADENDO 13”); ausência | Não há artefato de pré-registro; grade de c diverge do protocolo |
| Fase A — replicação | **FAIL** | `PROTOCOLO:203-212` | Não exigida; PARTIAL → pêndulo |
| Fase A — exclusão | **FAIL** | nenhum critério | Não definida |
| Fase A — multiplicidade | **NOT_VERIFIABLE** | `PROTOCOLO:151-157` | Não definida para β1/β2/β3 nem para Y2/Y3 |
| Fase A — parâmetros | **FAIL** | `PROTOCOLO:224-225`; `DEFINICAO:177-182` | `lambda`, `eps_c`, `g_phi`, `f(phi)` em aberto |

---

## 9. Correções necessárias por gravidade

Não é uma proposta de novo protocolo; é a lista mínima do que precisa ser resolvido antes de qualquer autorização.

### CRÍTICAS

1. **Resolver o constructo Φ.** Ou implementar Φ_MIP (bipartição + D_KL) e usá-lo como Φ, ou renomear explicitamente a hipótese para “TE×Σ” e retirar a pretensão de testar a TCI. Não se pode chamar TE de Φ sem prova de equivalência.
2. **Dar a `c` um caminho causal até o desfecho.** O desfecho precisa depender de `b` (por exemplo, `O=f(b,phi)`) ou o relógio precisa receber realimentação dos bits. Sem isso, `Δ_int=0` por construção.
3. **Substituir o teste de independência tautológico.** Construir o sistema comum, medir Φ(c,d) e Σ(c,d), calcular os efeitos principais e a contaminação nesse sistema; não usar módulos separados nem diferenças de um valor com ele mesmo.
4. **Corrigir a regra de decisão.** Usar um critério direcional único (ex.: `Δ_int ≥ +δ` com limite inferior do IC > 0) e remover o valor absoluto; definir separadamente “nulo”, “inconclusivo” e “efeito menor que δ”.
5. **Fechar os parâmetros da Fase A** (`lambda`, `eps_c`, `g_phi`, `f(phi)`) antes de qualquer execução.

### ALTAS

6. **Definir `Y1`, `Y2`, `Y3` e o que é retenção/adaptabilidade.** Se a tese é resiliência sob perturbação, incluir perturbação e recuperação; previsão de um passo não é resiliência.
7. **Pré-registrar N, poder, seeds, pools independentes, exclusão e replicação.** Exigir replicação independente antes do pêndulo; não permitir que PARTIAL autorize escalada.
8. **Definir a interação em Φ,Σ medidos** ou verificar linearidade de Φ(c) e Σ(d) na grade. O contraste de extremos em `c,d` não é o coeficiente de Φ×Σ.
9. **Alinhar a grade de `c` ao protocolo** ou documentar uma emenda com justificativa e data; explicar por que `0,35/0,60/0,80` substituiu `0,25/0,50/0,75`.
10. **Reconciliar relatório, JSON e script da Fase B.** Preservar a versão exata que gerou o JSON; remover ou substanciar as afirmações de `T=20000`; corrigir os rótulos PASS/PARTIAL.

### MODERADAS

11. **Completar o gate** com `piP=pi` e `P_rev` linha-estocástica para todo `c,d`; incluir `eta²`.
12. **Documentar `alpha=1,0` e `alpha=1e-6`** e usar a estacionária de `P` para `pi`; usar bootstrap do estimador, não percentil entre seeds.
13. **Relatar o viés dos controles negativos** e aplicar o critério “IC contém o teórico” de forma consistente.
14. **Evitar pseudo-replicação:** declarar que as 25 células são 5×5 e qual é o N efetivo.
15. **Definir multiplicidade e exclusão** para a Fase A.

### BAIXAS

16. Corrigir rótulos `PASS/PARTIAL`, `empirical_phi_tracking`, a divergência `0,202/0,2081`, a referência ao “ADENDO 13” e a qualificação de “exato” para a matriz racionalizada.

---

## 10. Parecer final

```
REPROVADO — ERRO DE CONSTRUCTO OU DESENHO
```

**Fundamentos:**

1. **Constructo:** Φ é operacionalizado como TE, não como Φ_MIP. Não há prova de equivalência. O V19 pode testar uma hipótese TE×Σ, mas não a TCI definida como Φ_MIP×Σ. **Mesmo que a equipe aceite TE como definição operacional de Φ e renomeie a hipótese, o parecer permanece REPROVADO pelos itens 2–4 abaixo.**
2. **Desenho:** a Fase A especifica `O_t=f(phi_t)` e um relógio exógeno; `c` não tem caminho causal até `Y1`. A interação é zero por construção, não por evidência.
3. **Independência:** a Fase B calcula a “contaminação” como diferença de um valor com ele mesmo e simula os módulos separadamente. O PASS de independência é tautológico. Além disso, o módulo Σ gera TE de até 0,4969 bits, acima de `delta_Phi=0,10`.
4. **Decisão:** a regra PASS/FAIL usa `|Δ_int|` e se contradiz com `Δ_int≤0`; não há critério direcional único, nem poder, nem replicação. O protocolo permite escalar com PARTIAL.

**O que se preserva:**

- A Fase B, no domínio estreito das kernels construídas separadas, tem valor: os estimadores de TE e de produção de entropia são matematicamente corretos; a calibração numérica do Σ é sólida; o diagnóstico de zeros estruturais e de subestimação em T=1000 é honesto e útil.
- O reconhecimento das limitações empíricas nos extremos (`FASE_B_V19.md:57-61`) é um ponto positivo.

**O que não se sustenta:**

- O V19 não é um teste válido da TCI.
- A Fase A não é identificável e não está implementada.
- O “PASS” global da Fase B não é suportado pelos próprios artefatos.

**Consequência operacional:** a Fase A **não está autorizada**. Uma nova revisão red team é necessária depois que o constructo, o caminho causal, o desfecho, a estatística e a regra de decisão forem corrigidos. Nenhuma execução deve ocorrer antes disso.

```
AUDITORIA CONCLUÍDA — PARECER EMITIDO — FASE A NÃO AUTORIZADA
```
