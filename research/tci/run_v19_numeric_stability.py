import json
import math
import os
from decimal import Decimal, getcontext
from fractions import Fraction

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPRO = os.path.join(HERE, "reproducao")
os.makedirs(REPRO, exist_ok=True)

getcontext().prec = 60
np.set_printoptions(precision=6, suppress=False)


# ---------------------------------------------------------------------------
# Estimador operacional
# ---------------------------------------------------------------------------

def stationary_linear(P):
    n = P.shape[0]
    A = P.T - np.eye(n)
    A[-1, :] = 1.0
    b = np.zeros(n)
    b[-1] = 1.0
    pi = np.linalg.solve(A, b)
    cond = np.linalg.cond(A)
    return pi, cond


def stationary_eig(P):
    vals, vecs = np.linalg.eig(P.T)
    idx = int(np.argmin(np.abs(vals - 1.0)))
    pi = np.real(vecs[:, idx])
    pi = pi / pi.sum()
    return pi


def reverse_matrix(P, pi):
    n = P.shape[0]
    R = np.zeros_like(P)
    for i in range(n):
        if pi[i] > 0:
            R[i, :] = pi * P[:, i] / pi[i]
    return R


def sigma_irrev(P, pi):
    R = reverse_matrix(P, pi)
    s = 0.0
    inf_flag = False
    for i in range(P.shape[0]):
        if pi[i] <= 0:
            continue
        for j in range(P.shape[1]):
            p = P[i, j]
            q = R[i, j]
            if p > 0:
                if q <= 0:
                    inf_flag = True
                    continue
                s += pi[i] * p * math.log(p / q)
    if inf_flag:
        return float("inf"), R
    return s, R


def asymmetry(P, pi):
    n = P.shape[0]
    a = 0.0
    for i in range(n):
        for j in range(n):
            a += abs(pi[i] * P[i, j] - pi[j] * P[j, i])
    return 0.5 * a


def diagnostics(P):
    pi_lin, cond = stationary_linear(P)
    pi_eig = stationary_eig(P)
    pi = pi_lin
    s, R = sigma_irrev(P, pi)
    db = np.max(np.abs(np.outer(pi, np.ones(len(pi))) * P
                       - np.outer(np.ones(len(pi)), pi) * P.T))
    stat = np.max(np.abs(pi @ P - pi))
    norm = abs(pi.sum() - 1.0)
    rowsum = np.max(np.abs(R.sum(axis=1) - 1.0))
    return {
        "pi": pi.tolist(),
        "pi_eig": pi_eig.tolist(),
        "pi_diff": float(np.max(np.abs(pi - pi_eig))),
        "cond": float(cond),
        "normalization_error": float(norm),
        "stationarity_error": float(stat),
        "detailed_balance_error": float(db),
        "sigma": float(s),
        "asymmetry": float(asymmetry(P, pi)),
        "prev_rowsum_error": float(rowsum),
        "min_pi": float(pi.min()),
    }


# ---------------------------------------------------------------------------
# Referencia de alta precisao (Fracoes + Decimal)
# ---------------------------------------------------------------------------

def solve_fraction(A, b):
    n = len(A)
    M = [list(A[i]) + [b[i]] for i in range(n)]
    for col in range(n):
        piv = None
        for r in range(col, n):
            if M[r][col] != 0:
                piv = r
                break
        if piv is None:
            raise ValueError("matriz singular")
        M[col], M[piv] = M[piv], M[col]
        pv = M[col][col]
        M[col] = [x / pv for x in M[col]]
        for r in range(n):
            if r != col and M[r][col] != 0:
                f = M[r][col]
                M[r] = [M[r][c] - f * M[col][c] for c in range(n + 1)]
    return [M[i][n] for i in range(n)]


def exact_sigma(P_frac):
    n = len(P_frac)
    A = [[P_frac[j][i] - (Fraction(1) if i == j else Fraction(0))
          for j in range(n)] for i in range(n)]
    A[-1] = [Fraction(1)] * n
    b = [Fraction(0)] * (n - 1) + [Fraction(1)]
    pi = solve_fraction(A, b)
    s = Decimal(0)
    for i in range(n):
        if pi[i] <= 0:
            continue
        for j in range(n):
            p = P_frac[i][j]
            if p <= 0:
                continue
            q = pi[j] * P_frac[j][i] / pi[i]
            if q <= 0:
                return Decimal("Infinity")
            pd = Decimal(p.numerator) / Decimal(p.denominator)
            qd = Decimal(q.numerator) / Decimal(q.denominator)
            pid = Decimal(pi[i].numerator) / Decimal(pi[i].denominator)
            s += pid * pd * (pd.ln() - qd.ln())
    return s


def to_fraction_matrix(P):
    return [[Fraction(float(x)).limit_denominator(10**12) for x in row]
            for row in P]


# ---------------------------------------------------------------------------
# Matrizes de teste
# ---------------------------------------------------------------------------

def random_symmetric(n=4, seed=0):
    rng = np.random.default_rng(seed)
    A = rng.integers(1, 10, size=(n, n))
    A = A + A.T
    P = A / A.sum(axis=1, keepdims=True)
    return P


def biased_ring(d=0.9, lazy=0.01):
    n = 4
    P = np.zeros((n, n))
    for i in range(n):
        P[i, i] = lazy
        P[i, (i + 1) % n] = (1 - lazy) * d
        P[i, (i - 1) % n] = (1 - lazy) * (1 - d)
    return P


def smoothed_cycle(eps=1e-3):
    n = 4
    Q = np.zeros((n, n))
    for i in range(n):
        Q[i, (i + 1) % n] = 1.0
    U = np.full((n, n), 1.0 / n)
    return (1 - eps) * Q + eps * U


def modular_product(seed=0, d=0.9, lazy=0.01):
    PI = random_symmetric(4, seed)
    PR = biased_ring(d, lazy)
    return np.kron(PI, PR)


def perturb(P, sigma, rng):
    Q = P + rng.normal(0.0, sigma, size=P.shape)
    Q = np.clip(Q, 0.0, None)
    rs = Q.sum(axis=1, keepdims=True)
    rs[rs == 0] = 1.0
    return Q / rs


# ---------------------------------------------------------------------------
# Execucao
# ---------------------------------------------------------------------------

def main():
    rng = np.random.default_rng(12345)
    tests = {
        "random_symmetric_0": random_symmetric(4, 0),
        "random_symmetric_1": random_symmetric(4, 1),
        "ring_reversible_d0.50": biased_ring(0.50, 0.01),
        "ring_irreversible_d0.90": biased_ring(0.90, 0.01),
        "smoothed_cycle_eps1e-3": smoothed_cycle(1e-3),
        "modular_product_d0.90": modular_product(0, 0.90, 0.01),
    }

    report = {}
    for name, P in tests.items():
        d = diagnostics(P)
        Pfrac = to_fraction_matrix(P)
        try:
            exact = exact_sigma(Pfrac)
            d["sigma_exact"] = str(exact)
            d["sigma_abs_error"] = float(abs(Decimal(d["sigma"]) - exact)) if exact.is_finite() else float("inf")
        except Exception as exc:
            d["sigma_exact"] = "erro: " + str(exc)
            d["sigma_abs_error"] = None
        report[name] = d

    # Sensibilidade a perturbacoes numericas
    noise_levels = [1e-12, 1e-10, 1e-8]
    reps = 100
    sens = {}
    for name, P in tests.items():
        base, _ = sigma_irrev(P, stationary_linear(P)[0])
        row = {}
        for nl in noise_levels:
            vals = []
            for _ in range(reps):
                Q = perturb(P, nl, rng)
                pi = stationary_linear(Q)[0]
                s, _ = sigma_irrev(Q, pi)
                vals.append(s)
            vals = np.array(vals)
            row[f"{nl:.0e}"] = {
                "mean": float(vals.mean()),
                "std": float(vals.std(ddof=1)),
                "max_abs_dev_from_base": float(np.max(np.abs(vals - base))),
                "min": float(vals.min()),
                "max": float(vals.max()),
            }
        sens[name] = row
    report["_sensibilidade"] = sens

    with open(os.path.join(REPRO, "registros_v19_estabilidade.json"), "w") as f:
        json.dump(report, f, indent=2)

    # Resumo legivel
    lines = []
    lines.append("# Calibracao numerica do estimador Sigma (v19)")
    lines.append("")
    lines.append("Nao e o experimento B; sao matrizes de teste para justificar eps_db e eps_Sigma.")
    lines.append("")
    lines.append("## Diagnostico por matriz (float64)")
    lines.append("")
    lines.append("| Matriz | sigma | sigma_exato | erro | db_err | stat_err | norm_err | cond | pi_diff |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for name, d in report.items():
        if name.startswith("_"):
            continue
        lines.append(
            f"| {name} | {d['sigma']:.6e} | {d['sigma_exact']} | "
            f"{d['sigma_abs_error']} | {d['detailed_balance_error']:.3e} | "
            f"{d['stationarity_error']:.3e} | {d['normalization_error']:.3e} | "
            f"{d['cond']:.3e} | {d['pi_diff']:.3e} |"
        )
    lines.append("")
    lines.append("## Sensibilidade de sigma a perturbacoes")
    lines.append("")
    lines.append("| Matriz | ruido | media | desvio | max desvio vs base |")
    lines.append("|---|---|---|---|---|")
    for name, row in sens.items():
        for nl, v in row.items():
            lines.append(
                f"| {name} | {nl} | {v['mean']:.6e} | {v['std']:.3e} | "
                f"{v['max_abs_dev_from_base']:.3e} |"
            )
    lines.append("")
    lines.append("## Leitura")
    lines.append("")
    lines.append("- Matrizes reversiveis devem ter db_err ~ 1e-16 e sigma ~ 0.")
    lines.append("- Matrizes irreversiveis devem ter sigma finito e estavel.")
    lines.append("- eps_db e eps_Sigma devem ficar acima do ruido observado e abaixo")
    lines.append("  do menor sigma nao nulo de interesse.")
    with open(os.path.join(REPRO, "CALIBRACAO_NUMERICA_V19.md"), "w") as f:
        f.write("\n".join(lines) + "\n")

    print("\n".join(lines))


if __name__ == "__main__":
    main()
