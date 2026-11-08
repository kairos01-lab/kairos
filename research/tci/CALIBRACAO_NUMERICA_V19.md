# Calibracao numerica do estimador Sigma (v19)

Nao e o experimento B; sao matrizes de teste para justificar eps_db e eps_Sigma.

## Diagnostico por matriz (float64)

| Matriz | sigma | sigma_exato | erro | db_err | stat_err | norm_err | cond | pi_diff |
|---|---|---|---|---|---|---|---|---|
| random_symmetric_0 | -1.179612e-17 | 0E-120 | 1.1796119636642291e-17 | 1.388e-17 | 5.551e-17 | 0.000e+00 | 4.398e+00 | 1.665e-16 |
| random_symmetric_1 | 4.738757e-18 | 0E-120 | 4.7387568124244436e-18 | 4.163e-17 | 5.551e-17 | 0.000e+00 | 3.932e+00 | 5.551e-17 |
| ring_reversible_d0.50 | 0.000000e+00 | 0E-65 | 0.0 | 0.000e+00 | 0.000e+00 | 0.000e+00 | 3.606e+00 | 1.110e-16 |
| ring_irreversible_d0.90 | 1.740202e+00 | 1.74020186525028575117006845528528071616162504359123513154776 | 2.2184904913603527e-16 | 1.980e-01 | 0.000e+00 | 0.000e+00 | 2.877e+00 | 1.665e-16 |
| smoothed_cycle_eps1e-3 | 8.285006e+00 | 8.28500605935261219831348362044342608492122788070257083109256 | 1.2795911353327419e-15 | 2.498e-01 | 1.110e-16 | 0.000e+00 | 2.614e+00 | 3.053e-16 |
| modular_product_d0.90 | 1.740202e+00 | 1.74020186525028569330544004295755419722234509725410196345084 | 2.79713677548363e-16 | 2.228e-02 | 1.804e-16 | 1.110e-16 | 1.532e+01 | 1.388e-16 |

## Sensibilidade de sigma a perturbacoes

| Matriz | ruido | media | desvio | max desvio vs base |
|---|---|---|---|---|
| random_symmetric_0 | 1e-12 | 4.954370e-18 | 1.520e-17 | 4.302e-17 |
| random_symmetric_0 | 1e-10 | 7.244205e-18 | 1.828e-17 | 5.759e-17 |
| random_symmetric_0 | 1e-08 | 7.016124e-16 | 5.262e-16 | 2.238e-15 |
| random_symmetric_1 | 1e-12 | 3.892550e-18 | 2.015e-17 | 5.619e-17 |
| random_symmetric_1 | 1e-10 | 5.212633e-19 | 1.931e-17 | 5.890e-17 |
| random_symmetric_1 | 1e-08 | 6.312024e-16 | 6.610e-16 | 4.820e-15 |
| ring_reversible_d0.50 | 1e-12 | inf | nan | inf |
| ring_reversible_d0.50 | 1e-10 | inf | nan | inf |
| ring_reversible_d0.50 | 1e-08 | inf | nan | inf |
| ring_irreversible_d0.90 | 1e-12 | inf | nan | inf |
| ring_irreversible_d0.90 | 1e-10 | inf | nan | inf |
| ring_irreversible_d0.90 | 1e-08 | inf | nan | inf |
| smoothed_cycle_eps1e-3 | 1e-12 | 8.285006e+00 | 1.842e-09 | 4.829e-09 |
| smoothed_cycle_eps1e-3 | 1e-10 | 8.285006e+00 | 2.011e-07 | 7.143e-07 |
| smoothed_cycle_eps1e-3 | 1e-08 | 8.285006e+00 | 2.231e-05 | 6.441e-05 |
| modular_product_d0.90 | 1e-12 | inf | nan | inf |
| modular_product_d0.90 | 1e-10 | inf | nan | inf |
| modular_product_d0.90 | 1e-08 | inf | nan | inf |

## Leitura

- Matrizes reversiveis devem ter db_err ~ 1e-16 e sigma ~ 0.
- Matrizes irreversiveis devem ter sigma finito e estavel.
- eps_db e eps_Sigma devem ficar acima do ruido observado e abaixo
  do menor sigma nao nulo de interesse.
