# -*- coding: utf-8 -*-
"""OS050 — procedimento de paridade do tokenizer para o ambiente Kaggle.

Este script NÃO é executado nesta OS. Ele é o procedimento reproduzível para
rodar no Kaggle (ou em um ambiente com transformers real), comparando o
tokenizer real com o RealQwenTokenizer da OS041.

Não chama model.generate. Não executa os 64 runs. Não autoriza o piloto.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys

PKG = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.join(PKG, "projetos", "motor_emocional")
SV01 = os.path.join(PROJ, "os028", "sv01")
REV = "b968826d9c46dd6066d109eabc6255188de91218"
DEFAULT_TOKENIZER = os.path.join(
    PKG, "tokenizer", "Qwen3-8B", "snapshots", REV)
DEFAULT_MANIFEST = os.path.join(PKG, "os040", "manifesto_64.json")
DEFAULT_EXPECTED = os.path.join(PKG, "research", "sv01", "PARIDADE_ESPERADA.json")
DEFAULT_OUT = os.path.join(os.getcwd(), "PARIDADE_KAGGLE.json")


def sha_text(t):
    return hashlib.sha256(t.encode("utf-8")).hexdigest()


def sha_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def first_diff(a, b):
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            return i
    return None if len(a) == len(b) else min(len(a), len(b))


def run_parity(args):
    os.environ["SV01_OS040_DIR"] = os.path.join(PKG, "os040")
    os.environ["SV01_OS041_DIR"] = os.path.join(PKG, "os041")
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    for p in (os.path.join(PKG, "os040", "instrumentation"),
              os.path.join(PKG, "os041"), PROJ, SV01):
        if p not in sys.path:
            sys.path.insert(0, p)

    import jinja2
    import tokenizers
    import transformers
    from transformers import AutoTokenizer
    from integration.runner_sv01_integrated import (
        build_prompt_for_spec, load_manifest, select_probe_specs,
    )
    from integration.tokenizer_real import RealQwenTokenizer

    manifest = load_manifest(args.manifest)
    specs = select_probe_specs(manifest)
    expected = json.load(open(args.expected, encoding="utf-8"))
    expected_by_id = {x["run_id"]: x for x in expected["probes"]}

    hf_tok = AutoTokenizer.from_pretrained(
        args.tokenizer_dir, local_files_only=True, trust_remote_code=False)
    os041_tok = RealQwenTokenizer(args.tokenizer_dir, REV)

    rows = []
    for spec in specs:
        prompt = build_prompt_for_spec(spec)
        messages = [{"role": "user", "content": prompt}]
        s041 = os041_tok.apply_chat_template(
            messages, tokenize=False,
            add_generation_prompt=True, enable_thinking=False)
        shf = hf_tok.apply_chat_template(
            messages, tokenize=False,
            add_generation_prompt=True, enable_thinking=False)
        ids041 = os041_tok.encode(s041, add_special_tokens=True)
        idshf = hf_tok.encode(shf, add_special_tokens=True)
        exp = expected_by_id.get(spec.run_id, {}).get(
            "prompt_sha256_rendered")
        rows.append({
            "run_id": spec.run_id,
            "condition_id": spec.condition_id,
            "order_id": spec.order_id,
            "os041_len": len(s041),
            "hf_len": len(shf),
            "os041_sha256": sha_text(s041),
            "hf_sha256": sha_text(shf),
            "string_match": s041 == shf,
            "first_diff": first_diff(s041, shf),
            "os041_ids_len": len(ids041),
            "hf_ids_len": len(idshf),
            "input_ids_match": ids041 == idshf,
            "input_ids_first_diff": first_diff(ids041, idshf),
            "expected_sha256": exp,
            "expected_match": (exp is not None
                               and exp == sha_text(s041) == sha_text(shf)),
        })

    all_ok = all(
        r["string_match"] and r["input_ids_match"] and r["expected_match"]
        for r in rows)
    payload = {
        "os": "OS050-PARIDADE-KAGGLE",
        "status": ("PARIDADE_KAGGLE_APROVADA" if all_ok
                   else "PARIDADE_KAGGLE_DIVERGENTE"),
        "ambiente": {
            "python": sys.version.split()[0],
            "executable": sys.executable,
            "transformers": transformers.__version__,
            "tokenizers": tokenizers.__version__,
            "jinja2": jinja2.__version__,
        },
        "tokenizer": {
            "path": args.tokenizer_dir,
            "revision": REV,
            "classe_hf": type(hf_tok).__name__,
            "classe_os041": type(os041_tok).__name__,
            "arquivos": {
                n: sha_file(os.path.join(args.tokenizer_dir, n))
                for n in ("tokenizer.json", "tokenizer_config.json",
                          "vocab.json", "merges.txt", "config.json")
            },
        },
        "n_probes": len(rows),
        "todos_strings_iguais": all(r["string_match"] for r in rows),
        "todos_hashes_iguais": all(
            r["os041_sha256"] == r["hf_sha256"] for r in rows),
        "todos_input_ids_iguais": all(r["input_ids_match"] for r in rows),
        "todos_esperados": all(r["expected_match"] for r in rows),
        "model_generate_called": False,
        "inference_executed": False,
        "network_used": False,
        "resultados": rows,
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    print(json.dumps({
        "status": payload["status"],
        "n_probes": len(rows),
        "todos_strings_iguais": payload["todos_strings_iguais"],
        "todos_input_ids_iguais": payload["todos_input_ids_iguais"],
        "todos_esperados": payload["todos_esperados"],
        "out": args.out,
    }, ensure_ascii=False, indent=2))
    return 0 if all_ok else 3


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Paridade do tokenizer Qwen3-8B no Kaggle (procedimento)")
    ap.add_argument("--run", action="store_true",
                    help="executa a comparação; sem esta flag apenas mostra o plano")
    ap.add_argument("--tokenizer-dir", default=DEFAULT_TOKENIZER)
    ap.add_argument("--manifest", default=DEFAULT_MANIFEST)
    ap.add_argument("--expected", default=DEFAULT_EXPECTED)
    ap.add_argument("--out", default=DEFAULT_OUT)
    args = ap.parse_args(argv)
    if not args.run:
        print("Plano: usar --run para executar a comparação no Kaggle.")
        print("Tokenizador:", args.tokenizer_dir)
        print("Manifesto:", args.manifest)
        print("Esperado:", args.expected)
        print("Saída:", args.out)
        return 0
    return run_parity(args)


if __name__ == "__main__":
    raise SystemExit(main())
