"""Ponte de Memória Contextual - Integração Córtex-Memória.

Responsabilidade única: recuperar memórias semanticamente relevantes da
ContextMemory e formatá-las para o Córtex.

Convenção ÚNICA de similaridade (a mesma de TriangulationMemory.retrieve):
    similarity = 1.0 - distance
    distance   = distância bruta devolvida pelo ChromaDB (cosine, nesta coleção)

Esta ponte NÃO recalcula similaridade a partir da similaridade já calculada
(isso foi o bug de dupla inversão da versão anterior).
"""
import json
from typing import Dict, Any, Optional

from .triangulation_memory import TriangulationMemory

# Piso de elegibilidade: abaixo disso a memória não entra no prompt,
# mas PERMANECE registrada em `records` (sem viés de seleção silencioso).
DEFAULT_THRESHOLD = 0.7


class MemoryContextBridge:
    def __init__(self, context_memory: TriangulationMemory):
        self.context_memory = context_memory

    def describe(self) -> Dict[str, Any]:
        """Prova auditável de qual coleção foi aberta e qual métrica ela usa."""
        return self.context_memory.describe()

    def build_context(
        self,
        system: str,
        target: str,
        threat: str,
        top_k: int = 2,
        threshold: float = DEFAULT_THRESHOLD,
    ) -> Dict[str, Any]:
        """Recupera e formata memórias elegíveis.

        Returns:
            {
              retrieval_success: bool,
              memory_id: str | None,
              similarity: float | None,
              distance: float | None,
              formatted_context: str,   # "" quando não há memória elegível
              records: list,            # TODOS os candidatos, com 'eligible'
              eligible_count: int,
            }
        """
        # min_similarity=-2.0: não descartar candidatos; a elegibilidade é
        # decidida aqui e registrada explicitamente.
        raw = self.context_memory.retrieve(
            system=system, target=target, threat=threat,
            top_k=top_k, min_similarity=-2.0, include_distances=True,
        )

        records = []
        eligible = []
        for r in raw:
            similarity = float(r["similarity"])          # já calculada: 1 - dist
            distance = float(r.get("distance", 1.0 - similarity))
            record = {
                "id": r["memory"].get("id") or r.get("id"),
                "similarity": round(similarity, 4),       # consumida, nunca recomputada
                "distance": 0.0 if abs(distance) < 1e-12 else round(distance, 6),
                "eligible": similarity >= threshold,
                "content": r["memory"].get("context", {}),
            }
            records.append(record)
            if record["eligible"]:
                eligible.append(record)

        eligible.sort(key=lambda x: x["similarity"], reverse=True)

        formatted = "\n".join(
            f"<R_MEMORIA id='{rec['id']}' sim='{rec['similarity']:.2f}'> "
            f"{json.dumps(rec['content'], ensure_ascii=False)} </R_MEMORIA>"
            for rec in eligible
        )

        top = eligible[0] if eligible else None

        return {
            "retrieval_success": bool(eligible),
            "memory_id": top["id"] if top else None,
            "similarity": top["similarity"] if top else None,
            "distance": top["distance"] if top else None,
            "formatted_context": formatted,   # vazio, não texto fixo
            "records": records,
            "eligible_count": len(eligible),
        }
