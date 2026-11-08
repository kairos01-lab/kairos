"""Memória por Triangulação - Versão simplificada com ChromaDB.

Implementa armazenamento e recuperação de memórias usando ChromaDB como backend.
Focado em estabilidade - evita APIs complexas do ChromaDB que mudam entre versões.
"""
import numpy as np
import time
import chromadb


class TriangulationMemory:
    """Memória que armazena contextos através de embeddings triangulados.
    
    Cada memória é codada como um vetor em espaço 3D formado por:
    [ Sistema, Alvo, Ameaça ]
    Permitindo recuperação por similaridade de cosseno.
    
    O sistema usa ChromaDB localmente para persistência e recuperação.
    """
    
    def __init__(self, embedding_dim: int = 3, collection_name: str = "triangulation_mem",
                 persist_path: str = None, metric: str = None,
                 recreate_on_metric_mismatch: bool = False):
        """Inicializar memória por triangulação com ChromaDB backend.

        Args:
            metric: Métrica de distância explícita ("cosine", "l2", "ip").
                    None preserva o comportamento legado (default do ChromaDB = l2).
            recreate_on_metric_mismatch: Se True e a coleção persistida usar métrica
                    diferente da solicitada, recria a coleção. Usado apenas pela
                    ContextMemory (a PolicyMemory nunca deve ser recriada).
        """
        self.embedding_dim = embedding_dim
        self.collection_name = collection_name
        self.metric = metric

        # Configurar ChromaDB client
        if persist_path:
            self.client = chromadb.PersistentClient(path=persist_path)
        else:
            self.client = chromadb.EphemeralClient()

        metadata = {"embedding_dim": embedding_dim}
        if metric:
            metadata["hnsw:space"] = metric

        # Tentar obter a coleção existente e validar a métrica efetiva em runtime
        try:
            self.collection = self.client.get_collection(name=collection_name)
            effective = self._effective_metric()
            if metric and effective != metric:
                if not recreate_on_metric_mismatch:
                    raise RuntimeError(
                        f"[TriangulationMemory] Coleção '{collection_name}' usa "
                        f"métrica '{effective}', mas foi solicitada '{metric}'."
                    )
                self.client.delete_collection(name=collection_name)
                self.collection = self.client.create_collection(
                    name=collection_name, metadata=metadata
                )
        except RuntimeError:
            raise
        except Exception:
            self.collection = self.client.create_collection(
                name=collection_name, metadata=metadata
            )

    def _effective_metric(self) -> str:
        """Métrica realmente aplicada pela coleção (não a solicitada)."""
        meta = getattr(self.collection, "metadata", None) or {}
        return meta.get("hnsw:space", "l2")

    def describe(self) -> dict:
        """Diagnóstico auditável: qual coleção foi aberta e com qual métrica."""
        return {
            "collection_name": self.collection_name,
            "count": self.collection.count(),
            "requested_metric": self.metric,
            "effective_metric": self._effective_metric(),
            "metadata": dict(getattr(self.collection, "metadata", None) or {}),
        }
    
    def _generate_embedding(self, system: str, target: str, threat: str) -> np.ndarray:
        """Gerar embedding a partir dos três textos de triangulação.
        
        Usa hash determinístico para criar embedding consistente.
        """
        # Hash simples baseado nos textos para criar embedding consistente
        hash_val = hash(f"{system}|{target}|{threat}") % (2 ** 31)
        # Criar vetor 3D baseado no hash
        v1 = (hash_val & 0xFF) / 255.0
        v2 = ((hash_val >> 8) & 0xFF) / 255.0
        v3 = ((hash_val >> 16) & 0xFF) / 255.0
        embedding = np.array([v1, v2, v3], dtype=np.float32)
        
        # Garantir que não seja vetor nulo
        if np.linalg.norm(embedding) == 0:
            embedding = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        
        return embedding
    
    def store(self, system: str, target: str, threat: str,
              embedding: np.ndarray = None, context: dict = None) -> str:
        """Armazenar memória triangulada no ChromaDB.
        
        Args:
            system: O Sistema que processou a memória.
            target: O Alvo da memória.
            threat: A Ameaça ou contexto associado.
            embedding: Vetor de embedding (se None, gera a partir dos textos).
            context: Dicionário com metadados adicionais.
            
        Returns:
            ID da memória armazenada.
        """
        # Gerar embedding se não fornecido
        if embedding is None:
            embedding = self._generate_embedding(system, target, threat)
        
        # Normalizar embedding
        norm = np.linalg.norm(embedding)
        if norm > 0:
            embedding = embedding / norm
        embedding = embedding.astype(np.float32)
        
        # Preparar metadados
        metadata = {
            "system": system,
            "target": target,
            "threat": threat,
            "embedding_dim": self.embedding_dim,
            "timestamp": time.time(),
            **(context or {})
        }
        
        # Preparar documento para busca textual
        document = f"{system} | {target} | {threat}"
        mem_id = f"mem_{int(time.time() * 1000)}"

        # Inserir no ChromaDB
        try:
            self.collection.add(
                embeddings=[embedding.tolist()],
                documents=[document],
                metadatas=[metadata],
                ids=[mem_id]
            )
            self._last_id = mem_id
            return self._last_id
        except Exception as e:
            print(f"[TriangulationMemory] Erro ao armazenar: {e}")
            # Fallback simples - tentar de qualquer jeit
            try:
                fallback_id = hashlib.md5(f"{system}_{target}_{threat}".encode()).hexdigest()[:12]
                embedding_norm = embedding / np.linalg.norm(embedding) if np.linalg.norm(embedding) > 0 else embedding
                self.collection.add(
                    embeddings=[embedding_norm.tolist()],
                    documents=[f"{system} | {target} | {threat}"],
                    metadatas=[{"system": system, "target": target, "threat": threat, "fallback": True, "timestamp": time.time()}],
                    ids=[fallback_id]
                )
                self._last_id = fallback_id
                return self._last_id
            except:
                self._last_id = None
                return None
    
    def retrieve(self, system: str = None, target: str = None, threat: str = None, 
                 top_k: int = 5, min_similarity: float = 0.1,
                 include_distances: bool = False) -> list:
        """Recuperar memórias baseado na triangulação.
        
        Args:
            system: Filtrar pelo Sistema (opcional).
            target: Filtrar pelo Alvo (opcional).
            threat: Filtrar pela Ameaça (opcional).
            top_k: Número de resultados mais relevantes.
            min_similarity: Piso mínimo. Default 0.1 preserva o comportamento
                histórico da PolicyMemory. A ContextMemory usa -2.0 para que
                NENHUM candidato seja descartado silenciosamente.
            include_distances: Se True, solicita ao ChromaDB a distância BRUTA
                segundo a métrica efetiva da coleção (usado pela ContextMemory).
                False preserva o caminho legado (recomputa cosseno manual).

        Returns:
            Lista com 'similarity' (1 - distância) e 'distance' (bruta do ChromaDB).
        """
        # Gerar query embedding
        query_emb = self._generate_embedding(system or "", target or "", threat or "")

        try:
            # Buscar no ChromaDB usando sintaxe nativa do where
            # ChromaDB exige: 0 filtros -> None | 1 filtro -> dict simples | 2+ filtros -> $and
            filters = []
            if system:
                filters.append({"system": system})
            if target:
                filters.append({"target": target})
            if threat:
                filters.append({"threat": threat})

            if len(filters) == 0:
                where_filter = None
            elif len(filters) == 1:
                where_filter = filters[0]
            else:
                where_filter = {"$and": filters}

            include_fields = ["metadatas", "embeddings", "documents"]
            if include_distances:
                include_fields.append("distances")

            # Buscar - precisar passar query_embeddings obrigatoriamente
            results = self.collection.query(
                query_embeddings=[query_emb.tolist()],
                where=where_filter,
                n_results=top_k,
                include=include_fields
            )
            
            # Processar resultados
            retrieved = []
            if results["ids"] and len(results["ids"]) > 0 and results["ids"][0]:
                metadatas = results.get("metadatas", [{}])[0] or []
                stored_embeddings = results.get("embeddings", [])[0] if results.get("embeddings") else []
                stored_distances = results.get("distances", [0])[0] if results.get("distances") else []
                
                # Calcular similaridade a partir de distancias do ChromaDB
                if len(stored_distances) > 0:
                    for i in range(len(results["ids"][0])):
                        distance = float(stored_distances[i])
                        similarity = 1.0 - distance  # única convenção: sim = 1 - dist
                        if similarity > min_similarity:  # piso configurável
                            retrieved.append({
                                "memory": {
                                    "system": metadatas[i].get("system", system or "") if i < len(metadatas) else system or "",
                                    "target": metadatas[i].get("target", target or "") if i < len(metadatas) else target or "",
                                    "threat": metadatas[i].get("threat", threat or "") if i < len(metadatas) else threat or "",
                                    "context": {k: v for k, v in metadatas[i].items() if k not in
                                                ["system", "target", "threat", "embedding_dim", "timestamp", "fallback"]},
                                    "embedding": stored_embeddings[i] if i < len(stored_embeddings) else None,
                                    "timestamp": metadatas[i].get("timestamp", time.time()) if i < len(metadatas) else time.time(),
                                    "id": results["ids"][0][i]
                                },
                                "similarity": round(similarity, 4),
                                "distance": 0.0 if abs(distance) < 1e-6 else round(distance, 6),
                            })
                
                # Se nao temos distancias, calcular a partir de embeddings armazenados
                elif len(stored_embeddings) > 0:
                    for i in range(len(results["ids"][0])):
                        if i < len(stored_embeddings) and stored_embeddings[i] is not None:
                            # Calcular similaridade de cosseno manual
                            sim = float(np.dot(query_emb, np.array(stored_embeddings[i])) / (np.linalg.norm(query_emb) * np.linalg.norm(stored_embeddings[i])))
                            if sim > min_similarity:
                                retrieved.append({
                                    "memory": {
                                        "system": metadatas[i].get("system", system or "") if i < len(metadatas) else system or "",
                                        "target": metadatas[i].get("target", target or "") if i < len(metadatas) else target or "",
                                        "threat": metadatas[i].get("threat", threat or "") if i < len(metadatas) else threat or "",
                                        "context": {k: v for k, v in metadatas[i].items() if k not in
                                                    ["system", "target", "threat", "embedding_dim", "timestamp", "fallback"]},
                                        "embedding": stored_embeddings[i],
                                        "timestamp": metadatas[i].get("timestamp", time.time()) if i < len(metadatas) else time.time(),
                                        "id": results["ids"][0][i]
                                    },
                                    "similarity": round(sim, 4),
                                    "distance": 0.0 if abs(1.0 - sim) < 1e-6 else round(1.0 - sim, 6),
                                })
            
            # Ordenar por similaridade e retornar top_k
            retrieved.sort(key=lambda x: x["similarity"], reverse=True)
            return retrieved[:top_k] if retrieved else []
            
        except Exception as e:
            print(f"[TriangulationMemory] Erro na recuperacao: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def get_stats(self) -> dict:
        """Retornar estatisticas da memoria."""
        try:
            count = self.collection.count()
        except Exception:
            count = 0
        
        return {
            "total": count,
            "embedding_dim": self.embedding_dim,
            "persistent": self.client._persist_dir is not None if hasattr(self.client, '_persist_dir') else False,
            "collection_name": self.collection_name
        }
    
    def reset(self):
        """Resetar a memoria - remove da ChromaDB e limpa in-memory."""
        try:
            self.client.delete_collection(name=self.collection_name)
        except Exception:
            pass
        # Recriar colecao vazia
        try:
            self.collection = self.client.create_collection(
                name=self.collection_name,
                metadata={"embedding_dim": self.embedding_dim}
            )
        except Exception:
            pass
    
    def get_collection_info(self) -> dict:
        """Retornar informacoes sobre a colecao ChromaDB."""
        try:
            coll = self.client.get_collection(name=self.collection_name)
            return {
                "name": self.collection_name,
                "total_items": coll.count(),
                "metadata": coll.metadata,
                "persist_dir": self.client._persist_dir if hasattr(self.client, '_persist_dir') else None
            }
        except Exception as e:
            return {"name": self.collection_name, "total_items": 0, "error": str(e)}


# Factory function para criacao rapida
def create_memory_client(persist_path: str = None) -> TriangulationMemory:
    """Factory function para criar cliente de memoria.
    
    Args:
        persist_path: Caminho para persistencia ChromaDB.
        
    Returns:
        Instancia configurada de TriangulationMemory.
    """
    return TriangulationMemory(embedding_dim=3, persist_path=persist_path)