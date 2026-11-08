# Protocolo v19 — desacoplamento Phi x Sigma (corrigido)

Status: protocolo corrigido, NAO implementado, sem dados, sem sobrevivencia.
Este documento incorpora a revisao do GPT: B = validacao dos instrumentos;
A = teste de interacao no mesmo sistema causal; pendulo so depois.

## 0. Principios

- Nao alterar a teoria.
- Nao executar sobrevivencia.
- Ordem: hipotese de manipulacao -> protocolo -> codigo -> pre-registro -> dados.
- B responde: controlamos Phi e Sigma independentemente?
- A responde: quando Phi e Sigma coexistem no mesmo sistema causal, existe
  interacao entre eles?
- Pendulo responde: essa estrutura tem consequencia comportamental observavel?
- Se B falhar, paramos. Nao vamos ao pendulo para "salvar" a hipotese.

## 1. Definicoes operacionais exatas

### 1.1 Processo medido e matriz de transicao

- Espaco de estados finito S. Para a Fase 1 (B), cada modulo e uma cadeia de
  Markov autonoma. Para a Fase 2 (A), o processo medido e o estado aumentado
  Z_t = (S_t, fase_do_drive_t), para que a cadeia seja Markov e pi seja unica.
- P_fwd(i,j) = Pr(Z_{t+1}=j | Z_t=i), estimada por contagem empirica
  normalizada (T=1000 por seed, varias seeds) ou construida exatamente.
- pi: distribuicao estacionaria, solucao de pi = pi P_fwd, pi_i >= 0,
  soma pi_i = 1. Se houver mais de uma, usar a alcancada a partir da
  distribuicao inicial; reportar qual foi usada. Verificar pi P = pi.
- Suporte: S+ = {i : pi_i > 0}. Estados fora do suporte sao excluidos da
  reversao e da soma de Sigma; nao se aplica suavizacao arbitraria.
- Suporte completo obrigatorio no experimento: todas as entradas das kernels
  serao > 0, com eps de suavizacao declarado. Zeros estruturais sao proibidos,
  porque o estimador retorna Sigma=inf sob perturbacao (ver
  DEFINICAO_D_E_ESTABILIDADE_V19.md).
- Duas estimativas separadas: (i) kernel construida (analitica) para o gate de
  reversibilidade e para Phi/Sigma primarios; (ii) kernel empirica (contagem)
  para verificar o estimador e gerar Y1. Nao misturar as duas.

### 1.2 P_rev (construcao passo a passo)

1. Construir/estimar P_fwd no espaco Z.
2. Calcular pi (autovetor esquerdo de P_fwd associado a autovalor 1,
   normalizado; ou solve linear com a condicao de soma 1).
3. Para cada i em S+, definir
   P_rev(i,j) = pi_j * P_fwd(j,i) / pi_i.
4. Verificar que P_rev e linha-estocastica no suporte:
   soma_j P_rev(i,j) = 1 para todo i em S+.
5. Definir
   Sigma_irrev = soma_{i em S+} pi_i * soma_j P_fwd(i,j) *
                 log( P_fwd(i,j) / P_rev(i,j) ),
   com 0*log(0/.) = 0. Unidade: nats por transicao.
6. Medida secundaria de assimetria:
   A = 0.5 * soma_{i,j} | pi_i P_fwd(i,j) - pi_j P_fwd(j,i) |.
   Reportar Sigma (primaria) e A (secundaria).
7. Salvar pi, P_fwd, P_rev e Sigma para auditoria.

Observacao: se P_fwd(i,j) > 0 e P_rev(i,j) = 0, o termo e +infinito; nesse
caso a kernel nao e reversivel e isso deve ser reportado, nao mascarado.

Nota de suporte: o gate eps_Sigma=1e-10 aplica-se a kernel construida. Para a
estimativa empirica, o erro amostral de T=1000 e ~1e-2 e propaga para Sigma_hat;
usar IC bootstrap e comparar com o valor teorico, nunca exigir Sigma_hat < 1e-10.

### 1.3 Phi_TCI

- TE(X->Y) = soma_{x_t,y_t,y_{t+1}} p(x_t,y_t,y_{t+1}) *
  log[ p(y_{t+1}|x_t,y_t) / p(y_{t+1}|y_t) ].
- Phi_TCI = 0.5 * [ TE(b1->b2) + TE(b2->b1) ].
- A distribuicao conjunta de (S_t, S_{t+1}) vem de pi_Z e P_Z, marginalizando
  a fase do drive quando ela existir. Nao usar suavizacao adicional alem do
  suporte.
- O mesmo estimador e usado em todas as condicoes; reportar o estimador.

### 1.4 Medicao modular na Fase 1 (B)

- Estado = (I1,I2,R1,R2); os modulos evoluem independentemente.
- Phi_TCI e medido no modulo I = (I1,I2).
- Sigma_irrev e medido no modulo R = (R1,R2).
- Isso e uma definicao de medicao por modulo, nao o Phi/Sigma do sistema
  completo. Declarar isso explicitamente em todos os resultados.
- O sistema completo e o produto dos modulos; pi = pi_I (x) pi_R; a soma de
  Sigma dos dois modulos e Sigma_I + Sigma_R, mas a medida usada para o
  criterio e a do modulo designado.

## 2. Fase 1 (B): validacao dos instrumentos

### 2.1 Modulo Phi (2 bits, reversivel)

- P0: flips independentes, reversivel, TE=0, Sigma=0.
- Px: kernel cruzada simetrizada, Px = 0.5*(C + C^T), C um mapa
  deterministico que copia um bit no outro.
- P_I(c) = (1-c) P0 + c Px, c em {0, 0.25, 0.50, 0.75, 1.00}.
- Por construcao P_I(c) e simetrica (P_I = P_I^T); com pi uniforme,
  detalhado balanco vale e Sigma_I(c) = 0 para todo c.
- REQUISITO: provar numericamente Sigma_I(c) ~ 0 pela definicao operacional
  (secao 1.2), nao assumir.

### 2.2 Modulo Sigma (2 bits, direcionado)

- Q0: kernel reversivel de base, suporte completo (ex.: uniforme ou flips
  independentes com suavizacao).
- Qcyc: ciclo direcionado suavizado de suporte completo:
  Qcyc = (1-eps_cyc) Q_4cycle + eps_cyc U, eps_cyc=1e-3 (Sigma ~ 8.285 nats,
  estavel; ver calibracao).
- P_R(d) = (1-d) Q0 + d Qcyc, d em {0, 0.25, 0.50, 0.75, 1.00}.
- Por construcao Sigma_R(d) cresce com d; para d=0, Sigma_R(0) = 0.
- REQUISITO: verificar numericamente Sigma_R(0) ~ 0 e que Phi_R(d) ~ 0
  (o ciclo nao deve gerar TE cruzada; se gerar, reportar e nao usar B como
  calibrador de Phi).

### 2.3 Checagens de sanidade (gate obrigatorio, antes da grade)

- Para todo c: max_{i,j} |pi_i P_I(i,j) - pi_j P_I(j,i)| < eps_db
  (eps_db = 1e-12) e Sigma_I(c) < eps_Sigma (eps_Sigma = 1e-10 nats).
  Este gate roda na kernel CONSTRUIDA (analitica), nao na estimativa empirica.
- Para d=0: Sigma_R(0) < eps_Sigma (kernel construida).
- Para todo c e d: pi P = pi e P_rev linha-estocastica no suporte.
- Se qualquer checagem falhar, a kernel nao recebe o rotulo "reversivel" e o
  protocolo para para revisao.

## 3. Fase 2 (A): interacao no mesmo sistema causal

### 3.1 Sistema acoplado

- Estado aumentado Z = (b1,b2,phi), phi em Z_4. Definicao completa em
  DEFINICAO_D_E_ESTABILIDADE_V19.md.
- Relogio direcionado de suporte completo:
  P_clock = (1-eps_c) P_ring + eps_c U, com P_ring(phi,phi)=lambda,
  P_ring(phi,phi+1)=(1-lambda)d, P_ring(phi,phi-1)=(1-lambda)(1-d).
  pi_clock uniforme; Sigma_clock = (1-eps_c)(1-lambda)(2d-1)log(d/(1-d)).
- Bits fase-gated: P_bits(b->b'|phi) = (1-g_phi)delta + g_phi P_sym(c),
  com g_phi fixo antes dos dados.
- P_Z((b,phi)->(b',phi')) = P_clock(phi,phi') P_bits(b->b'|phi).
- Caminho causal: phi gateia a atualizacao dos bits; O_t = f(phi_t) com f
  fixo antes dos dados, para que a fase carregue informacao sobre O_{t+1}.
- Em ambos os casos, os dois mecanismos atuam sobre o mesmo sistema causal,
  permitindo interacao.
- A priori, Sigma_Z = Sigma_clock (parte dos bits reversivel por construcao);
  c controla Phi e d controla Sigma no leading order. O residuo e medido pelo
  criterio de contaminacao < 20%.

### 3.2 Desfecho da Fase 2 (Y1 aprovado)

Desfecho primario: Y1, prever O_{t+1} a partir de S_t (acuracia ou
I(S_t;O_{t+1})). Y2 e Y3 ficam como secundarios/exploratorios e nao podem
substituir Y1 depois de inspecionar resultados.

### 3.3 Teste de interacao

- Grade c x d (5x5), mesma sequencia exogena por seed.
- Ajustar Y(c,d) = beta0 + beta1 c + beta2 d + beta3 c d + erro.
- Efeito de interacao: Delta_int = Y(1,1) - Y(1,0) - Y(0,1) + Y(0,0).
- PASS: |Delta_int| >= delta_int (pre-registrado) e IC95% exclui 0.
- PARTIAL: direcao correta, mas |Delta_int| < delta_int ou IC inclui 0.
- FAIL: Delta_int <= 0 ou direcao oposta.
- delta_int deve ser definido antes dos dados (ex.: 0.05 nas unidades de Y).

## 4. Criterios quantitativos auditaveis

### 4.1 Magnitudes e separacao minima

- delta_Phi e delta_Sigma definidos ANTES dos dados, com justificativa.
  Aprovados provisoriamente:
  delta_Phi = 0.10 bits; delta_Sigma = 0.20 nats/transicao;
  delta_int = 0.05 nas unidades de Y.
  Registro explicito: sao margens operacionais pre-especificadas de relevancia
  experimental, NAO previsoes derivadas da TCI-F.
- Separacao entre niveis (espectro funcional):
  min_k [ Phi(c_{k+1}, d=0) - Phi(c_k, d=0) ] >= delta_Phi
  min_k [ Sigma(c=0, d_{k+1}) - Sigma(c=0, d_k) ] >= delta_Sigma.
- Se a separacao minima nao for atingida, aumentar a forca/amplitude do
  mecanismo ou trocar o mecanismo; nao prosseguir com a grade.

### 4.2 Formulas exatas dos "20%"

- Efeito principal de c sobre Phi:
  ME_c^Phi = media_d Phi(c=1,d) - media_d Phi(c=0,d).
- Efeito principal de d sobre Phi:
  ME_d^Phi = media_c Phi(c,d=1) - media_c Phi(c,d=0).
- Contaminacao de d sobre Phi: C_{d->Phi} = |ME_d^Phi| / |ME_c^Phi|.
- Efeito principal de d sobre Sigma:
  ME_d^Sigma = media_c Sigma(c,d=1) - media_c Sigma(c,d=0).
- Efeito principal de c sobre Sigma:
  ME_c^Sigma = media_d Sigma(c=1,d) - media_d Sigma(c=0,d).
- Contaminacao de c sobre Sigma: C_{c->Sigma} = |ME_c^Sigma| / |ME_d^Sigma|.
- PASS de independencia (Fase 1): C_{d->Phi} < 0.20 e C_{c->Sigma} < 0.20,
  com ME_c^Phi >= delta_Phi e ME_d^Sigma >= delta_Sigma (evita divisao por
  efeito nulo), e eta^2 da interacao < 0.05.
- Reportar ME, C, IC e eta^2; nao usar apenas p-valor.

### 4.3 Prova numerica de Sigma ~ 0

- Rodar a checagem da secao 2.3 para todas as kernels rotuladas reversiveis.
- Reportar max |pi_i P(i,j) - pi_j P(j,i)| e Sigma.
- Sem essa prova, nenhuma kernel e chamada de reversivel.
- O gate usa a kernel CONSTRUIDA. A estimativa empirica e reportada com IC
  bootstrap e comparada ao teorico; nao se aplica eps_Sigma a Sigma_hat.
- Justificativa numerica: float64 deu db_err ~ 1e-17 e Sigma ~ 1e-17 em
  matrizes reversiveis; eps_db=1e-12 e eps_Sigma=1e-10 ficam 5-6 ordens acima
  do ruido de maquina e abaixo do menor efeito de interesse (>= 0.2).

## 5. Ordem de execucao

1. Aprovar este protocolo, incluindo delta_Phi, delta_Sigma, delta_int e o
   desfecho Y da Fase 2.
2. Implementar B + checagem numerica de reversibilidade.
3. Pre-registrar (arquivos de pre-registro antes de rodar).
4. Rodar B (sem pendulo, sem sobrevivencia).
5. Se B PASS: implementar A e rodar a interacao (sem pendulo).
6. Se A PASS/PARTIAL: so entao acoplar o pendulo e rodar sobrevivencia.
7. Se B FAIL: parar e redesenhar.

## 6. Decisoes pendentes antes do codigo

1. delta_Phi, delta_Sigma e delta_int: APROVADOS provisoriamente como margens
   operacionais (0.10 bits, 0.20 nats, 0.05).
2. Desfecho Y da Fase 2: APROVADO Y1 como primario; Y2/Y3 secundarios.
3. Definicao de D: PROPOSTA D-relogio em
   DEFINICAO_D_E_ESTABILIDADE_V19.md; aguardando aprovacao formal.
4. Sigma na Fase 1 medido no modulo R: APROVADO (validacao operacional, nao
   ontologica).
5. Tolerancias: PROPOSTAS eps_db=1e-12 e eps_Sigma=1e-10 para kernel
   construida; estimativa empirica por bootstrap. Aguardando aprovacao.
6. Parametros concretos ainda em aberto: lambda, eps_c, g_phi e f(phi).
