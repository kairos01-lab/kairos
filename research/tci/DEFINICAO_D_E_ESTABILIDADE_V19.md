# Definicao matematica de D e calibracao numerica (v19)

Status: fechamento de (c) e (e). Nada do experimento B foi implementado; nenhum
dado experimental novo. Apenas definicao matematica e calibracao do estimador.

## 1. Decisao sobre D: relogio direcionado de suporte completo

### 1.1 Espaco de estados

Z_t = (b1_t, b2_t, phi_t), com b1,b2 em {0,1} e phi em Z_4 = {0,1,2,3}.

- (b1,b2) e o modulo de integracao (Phi).
- phi e o relogio/fase (Sigma).
- O estado aumentado garante Markovidade e pi unica.

### 1.2 Transicao do relogio

P_clock = (1-eps_c) P_ring + eps_c U,

com U a matriz uniforme 4x4 (1/4 em cada entrada) e P_ring a caminhada viesada
no anel com auto-laco:

  P_ring(phi, phi)        = lambda
  P_ring(phi, phi+1 mod 4) = (1-lambda) d
  P_ring(phi, phi-1 mod 4) = (1-lambda) (1-d)

Parametros: lambda em [0,1) (lazy), eps_c > 0 (suavizacao de suporte completo),
d em [0,1] (vies direcional).

Forma explizita das entradas:
  P_clock(phi, phi)        = (1-eps_c) lambda + eps_c/4
  P_clock(phi, phi+1)      = (1-eps_c)(1-lambda) d + eps_c/4
  P_clock(phi, phi-1)      = (1-eps_c)(1-lambda)(1-d) + eps_c/4
  P_clock(phi, phi+2)      = eps_c/4

Soma das linhas = 1. A matriz e circulante; pi_clock = (1/4,1/4,1/4,1/4).

### 1.3 Transicao dos bits (fase-gated)

P_bits(b -> b' | phi) = (1-g_phi) delta_{b,b'} + g_phi P_sym(c)(b -> b'),

com g_phi em [0,1] pre-especificado (ex.: g = (0.2,0.5,0.8,1.0)) e
P_sym(c) = (1-c) P0 + c Px, P0 reversivel independente, Px cruzada simetrica.

### 1.4 Processo conjunto

P_Z((b,phi) -> (b',phi')) = P_clock(phi,phi') * P_bits(b -> b' | phi).

Como o relogio nao recebe realimentacao dos bits (produto semi-dirigido), a
distribuicao estacionaria e

  pi_Z(b,phi) = (1/4) * pi_b(phi),

onde pi_b(phi) e a estacionaria da kernel de bits condicional a phi. Se a
kernel de bits for a mesma em todas as fases (ou a gating for simetrica),
pi_b(phi) e uniforme e pi_Z e uniforme.

### 1.5 Sigma do processo conjunto

Como o relogio e independente dos bits e cada kernel condicional de bits e
reversivel (mistura de identidade e P_sym(c)), a producao de entropia se
decompoe:

  Sigma_Z = Sigma_clock + E_phi[ Sigma_bits|phi ] = Sigma_clock + 0.

Para a construcao acima:

  Sigma_clock = (1-eps_c)(1-lambda)(2d-1) log( d / (1-d) ).

Em d=0.5, Sigma=0; para d>0.5, Sigma cresce com d; para d<0.5, o sinal inverte.
Unidade: nats por transicao. A suavizacao eps_c e o lazy lambda apenas escalam
o termo direcionado; nao adicionam producao de entropia (componentes simetricas).

### 1.6 Por que D altera Sigma sem introduzir TE relevante (a priori)

1. O relogio e exogeno aos bits: phi_{t+1} nao depende de (b1_t,b2_t). Logo,
   nao ha caminho causal dos bits para o relogio.
2. A gating e simetrica entre b1 e b2: g_phi atua sobre a atualizacao conjunta,
   nao sobre a condicional de um bit especifico. A TE entre b1 e b2 na fase phi
   e g_phi * TE(P_sym(c)); a identidade contribui com TE=0.
3. Na media estacionaria, TE_marginal = E[g] * TE(P_sym(c)), que depende de c e
   da media da gating, nao do vies d do relogio. O vies d muda a ordem temporal
   da gating, nao a media.
4. Sigma_Z vem do relogio (equacao 1.5); a parte dos bits tem Sigma=0 por
   construcao (cada kernel condicional e reversivel).
5. Portanto, no leading order, c controla Phi e d controla Sigma. Um efeito
   residual de d sobre Phi so pode surgir por (i) nao estacionariedade, (ii)
   gating assimetrica entre bits, ou (iii) correlacao entre phi e b na
   inicializacao. O protocolo usa gating simetrica, inicializacao independente
   e burn-in; o criterio de contaminacao < 20% mede esse residuo.

### 1.7 Caminho causal para a Fase 2

O relogio gateia a atualizacao dos bits (phi -> g_phi -> b_{t+1}), entao ha
caminho causal de Sigma para o estado. Para que a interacao com Phi seja
testavel em Y1, a sequencia de observacoes sera pre-especificada como funcao
da fase (ex.: O_t = f(phi_t) com f fixo antes dos dados), de modo que a fase
carregue informacao sobre O_{t+1}. Isso cria a possibilidade de interacao
causal, sem tunar depois de ver resultados.

### 1.8 Alternativas (fallback, nao recomendadas como primeira escolha)

- D-ciclo: ciclo 4 direcionado suavizado nos bits. Sigma e TE crescem juntos;
  contaminacao esperada. So usar se o relogio falhar no teste de interacao.
- D-vies: vies direcional na marginal de um bit. Altera a estacionaria e pode
  alterar TE; menos limpo.

## 2. Calibracao numerica (fechamento de e)

Script: run_v19_numeric_stability.py. Matrizes de teste, nao dados de B.
Precisao: float64; referencia de alta precisao com Fracoes + Decimal (60 digitos).

### 2.1 Resultados

| Matriz | Sigma | Sigma exato | erro | db_err | stat_err | cond |
|---|---|---|---|---|---|---|
| random_symmetric_0 | -1.18e-17 | 0 | 1.18e-17 | 1.39e-17 | 5.55e-17 | 4.40 |
| random_symmetric_1 | 4.74e-18 | 0 | 4.74e-18 | 4.16e-17 | 5.55e-17 | 3.93 |
| ring_reversivel_d0.50 | 0 | 0 | 0 | 0 | 0 | 3.61 |
| ring_irreversivel_d0.90 | 1.740202 | 1.740201865... | 2.22e-16 | 1.98e-01 | 0 | 2.88 |
| smoothed_cycle_eps1e-3 | 8.285006 | 8.285006059... | 1.28e-15 | 2.50e-01 | 1.11e-16 | 2.61 |
| modular_product_d0.90 | 1.740202 | 1.740201865... | 2.80e-16 | 2.23e-02 | 1.80e-16 | 15.3 |

### 2.2 Achado 1: zeros estruturais quebram o estimador sob perturbacao

O anel viesado e o produto modular tem uma entrada zero por linha (o estado
oposto). Ao perturbar a matriz, o ruido pode criar uma aresta de mao unica
(P_ij>0 com P_ji=0), e o estimador retorna Sigma=inf. Isso nao e irreversibilidade
real: e artefato de suporte. A solucao e usar suporte completo (eps_c>0) ou
mascarar o suporte. O relogio da secao 1.2 e de suporte completo por construcao.

### 2.3 Achado 2: o gate Sigma~0 vale para a kernel construida, nao para a empirica

- Na kernel construida (float64): db_err ~ 1e-17, Sigma_reversivel ~ 1e-17.
  eps_db=1e-12 e eps_Sigma=1e-10 ficam 5-6 ordens acima do ruido de maquina.
- Na estimativa empirica com T=1000, o erro amostral de P_hat e ~sqrt(P(1-P)/T)
  ~ 1e-2. Esse erro propaga para Sigma_hat em ordem 1e-2, nao 1e-10. Portanto,
  NAO se pode exigir Sigma_hat < 1e-10 de uma estimativa empirica.
- Consequencia para o protocolo: o gate de reversibilidade usa a kernel
  construida (analitica). A estimativa empirica de Sigma e reportada com IC
  bootstrap e comparada ao valor teorico; a tolerancia e baseada no erro
  amostral, nao em eps_Sigma.

### 2.4 Sensibilidade de Sigma (smoothed cycle, suporte completo)

| ruido na kernel | max desvio de Sigma |
|---|---|
| 1e-12 | 4.8e-9 |
| 1e-10 | 7.1e-7 |
| 1e-8 | 6.4e-5 |

O erro de maquina em float64 (~1e-16) produz desvios < 1e-11, compativel com
eps_Sigma=1e-10. O erro amostral de T=1000 e muito maior e deve ser tratado
separadamente (bootstrap).

### 2.5 Tolerancias propostas (justificadas)

- eps_db = 1e-12: acima do db_err observado (~4e-17) e abaixo de qualquer
  assimetria real de interesse (>= 1e-2).
- eps_Sigma = 1e-10 nats: acima do Sigma de maquina (~1e-17) e abaixo do menor
  Sigma nao nulo de interesse (>= 0.2). Aplicavel somente a kernels construidas.
- Para a estimativa empirica: IC95% bootstrap; PASS de reversibilidade empirica
  se o IC contem o valor teorico (0 para reversivel) e a largura do IC e
  reportada. Nao usar eps_Sigma como teste empirico.

## 3. Consequencias para o protocolo v19

1. Todas as kernels experimentais terao suporte completo (sem zeros
   estruturais), com eps de suavizacao declarado.
2. O gate de reversibilidade (eps_db, eps_Sigma) roda na kernel construida.
3. A estimativa empirica de Sigma usa bootstrap e e comparada ao teorico.
4. Phi e Sigma primarios sao calculados da kernel construida; a simulacao
   serve para verificar o estimador e gerar Y1 (trajetoria).
5. D e o relogio da secao 1.2; a gating g_phi e fixa antes dos dados.
6. Nenhum dado de sobrevivencia/pendulo nesta etapa.

## 4. Pendencias que permanecem

- Confirmar lambda, eps_c e a gating g_phi (valores concretos).
- Confirmar a funcao O_t = f(phi_t) da Fase 2.
- Aprovar eps_db=1e-12 e eps_Sigma=1e-10 com a distincao construida/empirica.
- Aprovar D-relogio como definicao oficial.
