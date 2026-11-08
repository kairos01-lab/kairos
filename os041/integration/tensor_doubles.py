# -*- coding: utf-8 -*-
"""OS041 — tensores mínimos para o limite de `model.generate`.

Não são tensores de PyTorch. Existem apenas para que o backend instrumentado
da OS040 receba a mesma *forma* de argumentos que receberia do tokenizer real:
`input_ids`, `attention_mask`, `.shape`, `.to(device)`, `.numel()` e indexação.

Nenhuma inferência é executada. O modelo real nunca é carregado.
"""
from __future__ import annotations


class FakeTensor:
    """Vetor 1-D ou 2-D mínimo, com a interface usada pelo backend."""

    def __init__(self, data, shape=None):
        self._data = [int(x) for x in data]
        if shape is None:
            shape = (len(self._data),)
        self.shape = tuple(shape)

    def __getitem__(self, key):
        if isinstance(key, slice):
            sub = self._data[key]
            return FakeTensor(sub, shape=(len(sub),))
        if isinstance(key, int) and len(self.shape) > 1 and key == 0:
            # tensor[0] -> vetor 1-D
            return FakeTensor(self._data, shape=(len(self._data),))
        return self._data[key]

    def tolist(self):
        return list(self._data)

    def numel(self):
        return len(self._data)

    def __len__(self):
        return len(self._data)

    def __int__(self):
        if len(self._data) != 1:
            raise TypeError(
                f"FakeTensor com {len(self._data)} elementos não pode virar int"
            )
        return int(self._data[0])

    def __repr__(self):
        preview = self._data[:8]
        sufixo = "..." if len(self._data) > 8 else ""
        return f"FakeTensor(shape={self.shape}, data={preview}{sufixo})"


class FakeBatch(dict):
    """Resultado de `tokenizer(texto, return_tensors='pt')`."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.device = None

    def to(self, device):
        self.device = device
        return self


class FakeOutput:
    """Resultado de `model.generate(...)`: `out[0]` é a sequência."""

    def __init__(self, sequence):
        self._sequence = [int(x) for x in sequence]

    def __getitem__(self, key):
        if key != 0:
            raise IndexError("FakeOutput só suporta out[0]")
        return FakeTensor(self._sequence, shape=(len(self._sequence),))

    def __repr__(self):
        return f"FakeOutput(len={len(self._sequence)})"
