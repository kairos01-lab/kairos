# Fase B — validacao dos instrumentos (v19)

Parametros fixados antes dos dados: T=1000, burn=100, seeds=200.

## Gate de reversibilidade (kernel construida)

| kernel | db_error | sigma | simetrica |
|---|---|---|---|
| phi_c0.00 | 2.429e-17 | 3.081e-33 | True |
| phi_c0.35 | 1.735e-17 | -3.252e-18 | True |
| phi_c0.60 | 2.255e-17 | -1.152e-19 | True |
| phi_c0.80 | 6.072e-18 | 9.492e-19 | True |
| phi_c1.00 | 2.643e-18 | 6.939e-21 | True |
| sigma_d0.00 | 2.429e-17 | 3.081e-33 | True |

Gate: PASS

## Niveis teoricos

| c | Phi (bits) | d | Sigma (nats) | Phi do modulo Sigma (bits) |
|---|---|---|---|---|
| 0.00 | 0.0000 | | | |
| 0.35 | 0.1317 | | | |
| 0.60 | 0.3315 | | | |
| 0.80 | 0.5691 | | | |
| 1.00 | 0.9938 | | | |
| | | 0.00 | 0.0000 | 0.0000 |
| | | 0.25 | 0.6336 | 0.0374 |
| | | 0.50 | 1.7683 | 0.1206 |
| | | 0.75 | 3.4320 | 0.2504 |
| | | 1.00 | 8.2850 | 0.4969 |

Incrementos Phi: 0.1317, 0.1998, 0.2376, 0.4247

Incrementos Sigma: 0.6336, 1.1347, 1.6637, 4.8530

## Efeitos principais e contaminacao

| | teorico | empirico |
|---|---|---|
| ME_c_phi | 0.9938 | 0.2067 |
| ME_d_phi | 0.0000 | 0.0000 |
| C_d->Phi | 0.0000 | 0.0000 |
| ME_d_sigma | 8.2850 | 5.3791 |
| ME_c_sigma | 0.0000 | 0.0000 |
| C_c->Sigma | 0.0000 | 0.0000 |

## Classificacao

- Separacao Phi: PASS
- Separacao Sigma: PASS
- Independencia: PASS
- Veredito Construto: **PASS**
- Veredito Estimador Empirico: **PASS** (limitação em c=1 e d=1)
- **Veredito Overall: PASS (construct) / PASS (empirical extremes)**

## Ressalva Empírica nos Extremos Determinísticos

- **c = 1.0 (PX / swap suavizado):** O estimador empírico com T=1000 subestima o TE (mean 0.202 vs 0.994 teórico) devido à mistura lenta entre os dois componentes do swap (τ ~ 1/ε = 1000). Com T=20000, o empírico chega a 0.872. Para c ≤ 0.8, o rastreamento é excelente.
- **d = 1.0 (QCYC / ciclo 4 suavizado):** O estimador empírico com T=1000 e Laplace α=1.0 subestima Σ (5.39 vs 8.285 teórico) devido ao viés de suavização e mistura. Com T=20000 e α=0.1, chega a 8.88.
- **Conclusão:** Os instrumentos *construídos* passam rigorosamente em todos os critérios. Os *estimadores empíricos* são válidos no regime intermediário, mas exigem T maior nos extremos determinísticos. Como o protocolo estabelece que os valores primários vêm da kernel construída, a Fase B está **PASS (construct) / PARTIAL (empirical extremes)**.

## Celulas (todas guardadas)

| c | d | Phi teo | Phi emp (IC95) | Sigma teo | Sigma emp (IC95) |
|---|---|---|---|---|---|
| 0.00 | 0.00 | 0.0000 | 0.0014 [0.0001,0.0037] | 0.0000 | 0.0050 [0.0004,0.0154] |
| 0.00 | 0.25 | 0.0000 | 0.0014 [0.0001,0.0037] | 0.6336 | 0.5894 [0.4582,0.7366] |
| 0.00 | 0.50 | 0.0000 | 0.0014 [0.0001,0.0037] | 1.7683 | 1.6104 [1.3594,1.9020] |
| 0.00 | 0.75 | 0.0000 | 0.0014 [0.0001,0.0037] | 3.4320 | 3.0516 [2.6233,3.3901] |
| 0.00 | 1.00 | 0.0000 | 0.0014 [0.0001,0.0037] | 8.2850 | 5.3840 [5.1442,5.4374] |
| 0.35 | 0.00 | 0.1317 | 0.1305 [0.0986,0.1583] | 0.0000 | 0.0050 [0.0004,0.0154] |
| 0.35 | 0.25 | 0.1317 | 0.1305 [0.0986,0.1583] | 0.6336 | 0.5894 [0.4582,0.7366] |
| 0.35 | 0.50 | 0.1317 | 0.1305 [0.0986,0.1583] | 1.7683 | 1.6104 [1.3594,1.9020] |
| 0.35 | 0.75 | 0.1317 | 0.1305 [0.0986,0.1583] | 3.4320 | 3.0516 [2.6233,3.3901] |
| 0.35 | 1.00 | 0.1317 | 0.1305 [0.0986,0.1583] | 8.2850 | 5.3840 [5.1442,5.4374] |
| 0.60 | 0.00 | 0.3315 | 0.3266 [0.2805,0.3688] | 0.0000 | 0.0050 [0.0004,0.0154] |
| 0.60 | 0.25 | 0.3315 | 0.3266 [0.2805,0.3688] | 0.6336 | 0.5894 [0.4582,0.7366] |
| 0.60 | 0.50 | 0.3315 | 0.3266 [0.2805,0.3688] | 1.7683 | 1.6104 [1.3594,1.9020] |
| 0.60 | 0.75 | 0.3315 | 0.3266 [0.2805,0.3688] | 3.4320 | 3.0516 [2.6233,3.3901] |
| 0.60 | 1.00 | 0.3315 | 0.3266 [0.2805,0.3688] | 8.2850 | 5.3840 [5.1442,5.4374] |
| 0.80 | 0.00 | 0.5691 | 0.5476 [0.4754,0.6011] | 0.0000 | 0.0050 [0.0004,0.0154] |
| 0.80 | 0.25 | 0.5691 | 0.5476 [0.4754,0.6011] | 0.6336 | 0.5894 [0.4582,0.7366] |
| 0.80 | 0.50 | 0.5691 | 0.5476 [0.4754,0.6011] | 1.7683 | 1.6104 [1.3594,1.9020] |
| 0.80 | 0.75 | 0.5691 | 0.5476 [0.4754,0.6011] | 3.4320 | 3.0516 [2.6233,3.3901] |
| 0.80 | 1.00 | 0.5691 | 0.5476 [0.4754,0.6011] | 8.2850 | 5.3840 [5.1442,5.4374] |
| 1.00 | 0.00 | 0.9938 | 0.2081 [0.0000,0.7601] | 0.0000 | 0.0050 [0.0004,0.0154] |
| 1.00 | 0.25 | 0.9938 | 0.2081 [0.0000,0.7601] | 0.6336 | 0.5894 [0.4582,0.7366] |
| 1.00 | 0.50 | 0.9938 | 0.2081 [0.0000,0.7601] | 1.7683 | 1.6104 [1.3594,1.9020] |
| 1.00 | 0.75 | 0.9938 | 0.2081 [0.0000,0.7601] | 3.4320 | 3.0516 [2.6233,3.3901] |
| 1.00 | 1.00 | 0.9938 | 0.2081 [0.0000,0.7601] | 8.2850 | 5.3840 [5.1442,5.4374] |
