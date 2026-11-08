import json
import math
import os
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPRO = os.path.join(HERE, "reproducao")
os.makedirs(REPRO, exist_ok=True)

# ---------------------------------------------------------------------------
# Parametros fixados ANTES dos dados (ver ADENDO 13)
# ---------------------------------------------------------------------------
T = 1000
BURN = 100
N_SEEDS = 200
DELTA_PHI = 0.10
DELTA_SIGMA = 0.20
DELTA_INT = 0.05
EPS_DB = 1e-12
EPS_SIGMA = 1e-10
P_FLIP = 0.1
EPS_X = 1e-3
EPS_CYC = 1e-3
C_GRID = [0.0, 0.35, 0.60, 0.80, 1.00]
D_GRID = [0.0, 0.25, 0.50, 0.75, 1.00]

BS = [(0, 0), (0, 1), (1, 0), (1, 1)]
BIX = {s: i for i, s in enumerate(BS)}
LN2 = math.log(2.0)

# ---------------------------------------------------------------------------
# Kernels
# ---------------------------------------------------------------------------

def independent_flip(p=P_FLIP):
    P = np.zeros((4, 4))
    for i, (b1, b2) in enumerate(BS):
        for j, (c1, c2) in enumerate(BS):
            P[i, j] = (p if b1 != c1 else 1 - p) * (p if b2 != c2 else 1 - p)
    return P


def swap_smoothed(eps=EPS_X):
    Ps = np.zeros((4, 4))
    for i, (b1, b2) in enumerate(BS):
        Ps[i, BIX[(b2, b1)]] = 1.0
    U = np.full((4, 4), 1.0 / 4.0)
    return (1 - eps) * Ps + eps * U


def cycle_smoothed(eps=EPS_CYC):
    Q = np.zeros((4, 4))
    for i in range(4):
        Q[i, (i + 1) % 4] = 1.0
    U = np.full((4, 4), 1.0 / 4.0)
    return (1 - eps) * Q + eps * U


P0 = independent_flip()
PX = swap_smoothed()
Q0 = independent_flip()
QCYC = cycle_smoothed()

# ---------------------------------------------------------------------------
# Medidas exatas
# ---------------------------------------------------------------------------

def stationary(P):
    n = P.shape[0]
    A = P.T - np.eye(n)
    A[-1, :] = 1.0
    b = np.zeros(n)
    b[-1] = 1.0
    return np.linalg.solve(A, b)


def sigma_exact(P):
    pi = stationary(P)
    n = P.shape[0]
    R = np.zeros_like(P)
    for i in range(n):
        if pi[i] > 0:
            R[i, :] = pi * P[:, i] / pi[i]
    s = 0.0
    for i in range(n):
        if pi[i] <= 0:
            continue
        for j in range(n):
            if P[i, j] > 0:
                s += pi[i] * P[i, j] * math.log(P[i, j] / R[i, j])
    return s


def te_exact(P):
    pi = np.ones(4) / 4.0
    pj = np.outer(pi, np.ones(4)) * P
    ps = pj.sum(axis=1)

    def cb2(si, b2p):
        return sum(pj[si, BIX[(a, b2p)]] for a in (0, 1)) / ps[si]

    def cb1(si, b1p):
        return sum(pj[si, BIX[(b1p, b)]] for b in (0, 1)) / ps[si]

    def mb2(b2, b2p):
        return sum(pj[BIX[(a, b2)], BIX[(c, b2p)]]
                   for a in (0, 1) for c in (0, 1)) / sum(
                       ps[BIX[(a, b2)]] for a in (0, 1))

    def mb1(b1, b1p):
        return sum(pj[BIX[(b1, a)], BIX[(b1p, c)]]
                   for a in (0, 1) for c in (0, 1)) / sum(
                       ps[BIX[(b1, a)]] for a in (0, 1))

    t12 = t21 = 0.0
    for si, (b1, b2) in enumerate(BS):
        for sj, (c1, c2) in enumerate(BS):
            p = pj[si, sj]
            if p > 0:
                t12 += p * math.log(cb2(si, c2) / mb2(b2, c2))
                t21 += p * math.log(cb1(si, c1) / mb1(b1, c1))
    return 0.5 * (t12 + t21) / LN2


def db_error(P):
    pi = stationary(P)
    n = P.shape[0]
    return float(np.max(np.abs(np.outer(pi, np.ones(n)) * P
                               - np.outer(np.ones(n), pi) * P.T)))


# ---------------------------------------------------------------------------
# Simulacao e estimadores empiricos
# ---------------------------------------------------------------------------

def simulate(P, rng, T=T, burn=BURN):
    n = P.shape[0]
    s = rng.integers(n)
    for _ in range(burn):
        s = rng.choice(n, p=P[s])
    traj = np.empty(T, dtype=int)
    for t in range(T):
        traj[t] = s
        s = rng.choice(n, p=P[s])
    return traj


def te_empirical(traj, alpha=1e-6):
    counts = np.full((4, 4), alpha)
    for t in range(len(traj) - 1):
        counts[traj[t], traj[t + 1]] += 1.0
    P = counts / counts.sum(axis=1, keepdims=True)
    pi = counts.sum(axis=0) / counts.sum()
    pj = np.outer(pi, np.ones(4)) * P
    ps = pj.sum(axis=1)

    def cb2(si, b2p):
        return sum(pj[si, BIX[(a, b2p)]] for a in (0, 1)) / ps[si]

    def cb1(si, b1p):
        return sum(pj[si, BIX[(b1p, b)]] for b in (0, 1)) / ps[si]

    def mb2(b2, b2p):
        return sum(pj[BIX[(a, b2)], BIX[(c, b2p)]]
                   for a in (0, 1) for c in (0, 1)) / sum(
                       ps[BIX[(a, b2)]] for a in (0, 1))

    def mb1(b1, b1p):
        return sum(pj[BIX[(b1, a)], BIX[(b1p, c)]]
                   for a in (0, 1) for c in (0, 1)) / sum(
                       ps[BIX[(b1, a)]] for a in (0, 1))

    t12 = t21 = 0.0
    for si, (b1, b2) in enumerate(BS):
        for sj, (c1, c2) in enumerate(BS):
            p = pj[si, sj]
            if p > 0:
                t12 += p * math.log(cb2(si, c2) / mb2(b2, c2))
                t21 += p * math.log(cb1(si, c1) / mb1(b1, c1))
    return 0.5 * (t12 + t21) / LN2


def sigma_empirical(traj, alpha=1.0):
    counts = np.full((4, 4), alpha)
    for t in range(len(traj) - 1):
        counts[traj[t], traj[t + 1]] += 1.0
    P = counts / counts.sum(axis=1, keepdims=True)
    pi = counts.sum(axis=0) / counts.sum()
    R = np.zeros_like(P)
    for i in range(4):
        if pi[i] > 0:
            R[i, :] = pi * P[:, i] / pi[i]
    s = 0.0
    for i in range(4):
        if pi[i] <= 0:
            continue
        for j in range(4):
            if P[i, j] > 0:
                s += pi[i] * P[i, j] * math.log(P[i, j] / R[i, j])
    return s


# ---------------------------------------------------------------------------
# Grid
# ---------------------------------------------------------------------------

def main():
    rng = np.random.default_rng(20261106)

    # Kernels por nivel
    phi_kernels = {c: (1 - c) * P0 + c * PX for c in C_GRID}
    sig_kernels = {d: (1 - d) * Q0 + d * QCYC for d in D_GRID}

    # Gate de reversibilidade (kernel construida)
    gate = {}
    for c, P in phi_kernels.items():
        gate[f"phi_c{c:.2f}"] = {
            "db_error": db_error(P),
            "sigma": sigma_exact(P),
            "symmetric": bool(np.allclose(P, P.T)),
        }
    gate["sigma_d0.00"] = {
        "db_error": db_error(sig_kernels[0.0]),
        "sigma": sigma_exact(sig_kernels[0.0]),
        "symmetric": bool(np.allclose(sig_kernels[0.0], sig_kernels[0.0].T)),
    }

    gate_pass = all(
        v["db_error"] < EPS_DB and abs(v["sigma"]) < EPS_SIGMA
        for k, v in gate.items()
    )

    # Valores teoricos
    phi_theory = {c: te_exact(P) for c, P in phi_kernels.items()}
    sig_theory = {d: sigma_exact(P) for d, P in sig_kernels.items()}
    phi_sig_module_theory = {d: te_exact(P) for d, P in sig_kernels.items()}

    # Simulacao: por celula (c,d), modulos independentes
    cells = []
    for c in C_GRID:
        for d in D_GRID:
            phi_vals = []
            sig_vals = []
            for seed in range(N_SEEDS):
                r = np.random.default_rng(20261106 + seed)
                traj_i = simulate(phi_kernels[c], r)
                traj_r = simulate(sig_kernels[d], r)
                phi_vals.append(te_empirical(traj_i))
                sig_vals.append(sigma_empirical(traj_r))
            phi_vals = np.array(phi_vals)
            sig_vals = np.array(sig_vals)
            cells.append({
                "c": c,
                "d": d,
                "phi_theory": phi_theory[c],
                "sigma_theory": sig_theory[d],
                "phi_sig_module_theory": phi_sig_module_theory[d],
                "phi_mean": float(phi_vals.mean()),
                "phi_ci": [float(np.percentile(phi_vals, 2.5)),
                           float(np.percentile(phi_vals, 97.5))],
                "sigma_mean": float(sig_vals.mean()),
                "sigma_ci": [float(np.percentile(sig_vals, 2.5)),
                             float(np.percentile(sig_vals, 97.5))],
            })

    # Separacao teorica
    phi_levels = [phi_theory[c] for c in C_GRID]
    sig_levels = [sig_theory[d] for d in D_GRID]
    phi_inc = [phi_levels[i + 1] - phi_levels[i] for i in range(len(C_GRID) - 1)]
    sig_inc = [sig_levels[i + 1] - sig_levels[i] for i in range(len(D_GRID) - 1)]

    # Efeitos principais e contaminacao (teoricos)
    me_c_phi = np.mean([phi_theory[1.0] - phi_theory[0.0] for _ in D_GRID])
    me_d_phi = np.mean([phi_theory[c] - phi_theory[c] for c in C_GRID])
    me_d_sig = np.mean([sig_theory[1.0] - sig_theory[0.0] for _ in C_GRID])
    me_c_sig = np.mean([sig_theory[d] - sig_theory[d] for d in D_GRID])
    c_d_phi = abs(me_d_phi) / abs(me_c_phi) if me_c_phi != 0 else float("inf")
    c_c_sig = abs(me_c_sig) / abs(me_d_sig) if me_d_sig != 0 else float("inf")

    # Efeitos principais e contaminacao (empiricos, celula a celula)
    def get(c, d, key):
        for cell in cells:
            if cell["c"] == c and cell["d"] == d:
                return cell[key]
        raise KeyError((c, d, key))

    me_c_phi_emp = np.mean([get(1.0, d, "phi_mean") - get(0.0, d, "phi_mean")
                            for d in D_GRID])
    me_d_phi_emp = np.mean([get(c, 1.0, "phi_mean") - get(c, 0.0, "phi_mean")
                            for c in C_GRID])
    me_d_sig_emp = np.mean([get(c, 1.0, "sigma_mean") - get(c, 0.0, "sigma_mean")
                            for c in C_GRID])
    me_c_sig_emp = np.mean([get(1.0, d, "sigma_mean") - get(0.0, d, "sigma_mean")
                            for d in D_GRID])
    c_d_phi_emp = (abs(me_d_phi_emp) / abs(me_c_phi_emp)
                   if me_c_phi_emp != 0 else float("inf"))
    c_c_sig_emp = (abs(me_c_sig_emp) / abs(me_d_sig_emp)
                   if me_d_sig_emp != 0 else float("inf"))

    sep_phi = min(phi_inc) >= DELTA_PHI
    sep_sig = min(sig_inc) >= DELTA_SIGMA
    indep = c_d_phi < 0.20 and c_c_sig < 0.20

    if gate_pass and sep_phi and sep_sig and indep:
        verdict = "PASS"
    elif gate_pass and (sep_phi or sep_sig):
        verdict = "PARTIAL"
    else:
        verdict = "FAIL"

    report = {
        "params": {
            "T": T, "BURN": BURN, "N_SEEDS": N_SEEDS,
            "DELTA_PHI": DELTA_PHI, "DELTA_SIGMA": DELTA_SIGMA,
            "DELTA_INT": DELTA_INT, "EPS_DB": EPS_DB,
            "EPS_SIGMA": EPS_SIGMA, "P_FLIP": P_FLIP,
            "EPS_X": EPS_X, "EPS_CYC": EPS_CYC,
            "C_GRID": C_GRID, "D_GRID": D_GRID,
        },
        "gate": gate,
        "gate_pass": bool(gate_pass),
        "phi_theory": phi_theory,
        "sigma_theory": sig_theory,
        "phi_sig_module_theory": phi_sig_module_theory,
        "phi_levels": phi_levels,
        "sigma_levels": sig_levels,
        "phi_inc": phi_inc,
        "sigma_inc": sig_inc,
        "main_effects_theory": {
            "me_c_phi": float(me_c_phi), "me_d_phi": float(me_d_phi),
            "me_d_sigma": float(me_d_sig), "me_c_sigma": float(me_c_sig),
            "c_d_phi": float(c_d_phi), "c_c_sigma": float(c_c_sig),
        },
        "main_effects_empirical": {
            "me_c_phi": float(me_c_phi_emp), "me_d_phi": float(me_d_phi_emp),
            "me_d_sigma": float(me_d_sig_emp), "me_c_sigma": float(me_c_sig_emp),
            "c_d_phi": float(c_d_phi_emp), "c_c_sigma": float(c_c_sig_emp),
        },
        "sep_phi": bool(sep_phi),
        "sep_sigma": bool(sep_sig),
        "independence": bool(indep),
        "verdict": verdict,
        "cells": cells,
    }

    with open(os.path.join(REPRO, "registros_v19_fase_b.json"), "w") as f:
        json.dump(report, f, indent=2)

    # Markdown
    L = []
    L.append("# Fase B — validacao dos instrumentos (v19)")
    L.append("")
    L.append("Parametros fixados antes dos dados: T=%d, burn=%d, seeds=%d." % (T, BURN, N_SEEDS))
    L.append("")
    L.append("## Gate de reversibilidade (kernel construida)")
    L.append("")
    L.append("| kernel | db_error | sigma | simetrica |")
    L.append("|---|---|---|---|")
    for k, v in gate.items():
        L.append(f"| {k} | {v['db_error']:.3e} | {v['sigma']:.3e} | {v['symmetric']} |")
    L.append("")
    L.append(f"Gate: {'PASS' if gate_pass else 'FAIL'} (eps_db={EPS_DB}, eps_sigma={EPS_SIGMA})")
    L.append("")
    L.append("## Niveis teoricos")
    L.append("")
    L.append("| c | Phi (bits) | d | Sigma (nats) | Phi do modulo Sigma (bits) |")
    L.append("|---|---|---|---|---|")
    for c in C_GRID:
        L.append(f"| {c:.2f} | {phi_theory[c]:.4f} | | | |")
    for d in D_GRID:
        L.append(f"| | | {d:.2f} | {sig_theory[d]:.4f} | {phi_sig_module_theory[d]:.4f} |")
    L.append("")
    L.append("Incrementos Phi: " + ", ".join(f"{x:.4f}" for x in phi_inc))
    L.append("")
    L.append("Incrementos Sigma: " + ", ".join(f"{x:.4f}" for x in sig_inc))
    L.append("")
    L.append("## Efeitos principais e contaminacao")
    L.append("")
    L.append("| | teorico | empirico |")
    L.append("|---|---|---|")
    L.append(f"| ME_c_phi | {me_c_phi:.4f} | {me_c_phi_emp:.4f} |")
    L.append(f"| ME_d_phi | {me_d_phi:.4f} | {me_d_phi_emp:.4f} |")
    L.append(f"| C_d->Phi | {c_d_phi:.4f} | {c_d_phi_emp:.4f} |")
    L.append(f"| ME_d_sigma | {me_d_sig:.4f} | {me_d_sig_emp:.4f} |")
    L.append(f"| ME_c_sigma | {me_c_sig:.4f} | {me_c_sig_emp:.4f} |")
    L.append(f"| C_c->Sigma | {c_c_sig:.4f} | {c_c_sig_emp:.4f} |")
    L.append("")
    L.append("## Classificacao")
    L.append("")
    L.append(f"- Separacao Phi: {'PASS' if sep_phi else 'FAIL'} (min={min(phi_inc):.4f}, delta={DELTA_PHI})")
    L.append(f"- Separacao Sigma: {'PASS' if sep_sig else 'FAIL'} (min={min(sig_inc):.4f}, delta={DELTA_SIGMA})")
    L.append(f"- Independencia: {'PASS' if indep else 'FAIL'} (C_d->Phi={c_d_phi:.4f}, C_c->Sigma={c_c_sig:.4f})")
    L.append(f"- **Veredito: {verdict}**")
    L.append("")
    L.append("## Celulas (todas guardadas)")
    L.append("")
    L.append("| c | d | Phi teo | Phi emp (IC95) | Sigma teo | Sigma emp (IC95) |")
    L.append("|---|---|---|---|---|---|")
    for cell in cells:
        L.append(
            f"| {cell['c']:.2f} | {cell['d']:.2f} | {cell['phi_theory']:.4f} | "
            f"{cell['phi_mean']:.4f} [{cell['phi_ci'][0]:.4f},{cell['phi_ci'][1]:.4f}] | "
            f"{cell['sigma_theory']:.4f} | "
            f"{cell['sigma_mean']:.4f} [{cell['sigma_ci'][0]:.4f},{cell['sigma_ci'][1]:.4f}] |"
        )
    with open(os.path.join(REPRO, "FASE_B_V19.md"), "w") as f:
        f.write("\n".join(L) + "\n")

    print("\n".join(L))


if __name__ == "__main__":
    main()
