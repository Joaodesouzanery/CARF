"""Busca semântica: embedders intercambiáveis, índice em Parquet e fusão híbrida (RRF)."""

import uuid
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

MODELOS = {
    # nome curto -> (id no fastembed/HF, prefixo de consulta, prefixo de passagem)
    "e5-small": ("intfloat/multilingual-e5-small", "query: ", "passage: "),
    "minilm": ("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2", "", ""),
    "e5-large": ("intfloat/multilingual-e5-large", "query: ", "passage: "),
    "spacy": ("pt_core_news_lg", "", ""),
}
MAX_CARACTERES = 1500
MAX_CARACTERES_ONNX = 800  # modelos transformer: custo cresce com o tamanho; o resto é boilerplate


def _normalizar(m: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(m, axis=1, keepdims=True)
    return m / np.where(n == 0, 1, n)


class Embedder:
    nome: str
    dim: int

    def codificar(self, textos: list[str], consulta: bool = False) -> np.ndarray:  # pragma: no cover
        raise NotImplementedError


class SpacyVetores(Embedder):
    """Média dos vetores de palavras do modelo spaCy. Sem download; qualidade menor."""

    nome = "spacy"

    def __init__(self):
        import spacy

        # só tokenizador + vetores estáticos: nenhum componente treinado é necessário
        nlp = spacy.load("pt_core_news_lg")
        self.nlp = spacy.load("pt_core_news_lg", exclude=list(nlp.pipe_names))
        self.dim = self.nlp.vocab.vectors_length

    def codificar(self, textos, consulta=False):
        out = np.zeros((len(textos), self.dim), dtype=np.float32)
        for i, doc in enumerate(self.nlp.pipe((t[:MAX_CARACTERES] for t in textos), batch_size=64)):
            vs = [t.vector for t in doc if t.has_vector and not t.is_stop and t.is_alpha]
            if vs:
                out[i] = np.mean(vs, axis=0)
        return _normalizar(out)


class FastEmbedModelo(Embedder):
    """Modelos ONNX via fastembed (sem PyTorch). Os pesos vêm do Hugging Face."""

    def __init__(self, nome: str):
        from fastembed import TextEmbedding
        from fastembed.common.model_description import ModelSource, PoolingType

        self.nome = nome
        hf_id, self.pq, self.pp = MODELOS[nome]
        if nome == "e5-small":  # fora da lista nativa do fastembed
            try:
                TextEmbedding.add_custom_model(
                    model=hf_id, pooling=PoolingType.MEAN, normalization=True,
                    sources=ModelSource(hf=hf_id), dim=384, model_file="onnx/model.onnx",
                    size_in_gb=0.47)
            except ValueError:
                pass  # já registrado
        self.modelo = TextEmbedding(hf_id)
        self.dim = len(next(iter(self.modelo.embed(["teste"]))))

    def codificar(self, textos, consulta=False):
        pre = self.pq if consulta else self.pp
        v = np.array(list(self.modelo.embed([pre + t[:MAX_CARACTERES_ONNX] for t in textos], batch_size=32)),
                     dtype=np.float32)
        return _normalizar(v)


def criar_embedder(nome: str) -> Embedder:
    if nome not in MODELOS:
        raise ValueError(f"modelo desconhecido: {nome} (opções: {', '.join(MODELOS)})")
    return SpacyVetores() if nome == "spacy" else FastEmbedModelo(nome)


class Indice:
    """Vetores float16 em Parquet (`data/embeddings/<modelo>/`), buscados em memória."""

    def __init__(self, raiz: Path, modelo: str):
        self.dir = Path(raiz) / "embeddings" / modelo
        self.modelo = modelo
        self.ids: np.ndarray = np.array([], dtype=object)
        self.mat: np.ndarray = np.zeros((0, 0), dtype=np.float32)

    def ids_existentes(self) -> set[str]:
        ids: set[str] = set()
        for f in self.dir.glob("part-*.parquet") if self.dir.exists() else []:
            ids.update(pq.read_table(f, columns=["id"]).column("id").to_pylist())
        return ids

    def gravar(self, ids: list[str], vetores: np.ndarray):
        self.dir.mkdir(parents=True, exist_ok=True)
        tab = pa.table({"id": ids, "vec": [v.astype(np.float16).tobytes() for v in vetores],
                        "dim": [vetores.shape[1]] * len(ids)})
        tmp = self.dir / f".part-{uuid.uuid4().hex}.tmp"
        pq.write_table(tab, tmp, compression="zstd")
        tmp.rename(self.dir / f"part-{uuid.uuid4().hex}.parquet")

    def carregar(self) -> "Indice":
        ids, blocos = [], []
        for f in sorted(self.dir.glob("part-*.parquet")):
            t = pq.read_table(f).to_pydict()
            ids += t["id"]
            blocos.append(np.stack([np.frombuffer(b, dtype=np.float16) for b in t["vec"]]))
        if ids:
            mat = np.concatenate(blocos).astype(np.float32)
            # deduplica por id: vale o último gravado
            _, ult = np.unique(np.array(ids[::-1], dtype=object), return_index=True)
            manter = sorted(len(ids) - 1 - ult)
            self.ids, self.mat = np.array(ids, dtype=object)[manter], mat[manter]
        return self

    def buscar(self, vetor: np.ndarray, k=100, permitidos: set[str] | None = None):
        if not len(self.ids):
            return []
        sim = self.mat @ vetor.astype(np.float32)
        if permitidos is not None:
            # np.isin sobre ids em texto leva ~10 s com 70 mil vetores; pertinência em conjunto, ~10 ms
            ok = np.fromiter((i in permitidos for i in self.ids), bool, len(self.ids))
            sim = np.where(ok, sim, -np.inf)
        k = min(k, len(sim))
        top = np.argpartition(-sim, k - 1)[:k]
        top = top[np.argsort(-sim[top])]
        return [(str(self.ids[i]), float(sim[i])) for i in top if sim[i] > -np.inf]


def indexar(con, indice: Indice, embedder: Embedder, lote=256, limite=None, log=print) -> int:
    """Vetoriza ementas ainda sem vetor (ementa anonimizada + decisão curta). Retoma sozinho."""
    feitos = indice.ids_existentes()
    linhas = con.execute("SELECT id, ementa FROM acordaos WHERE ementa IS NOT NULL ORDER BY id").fetchall()
    pend = [(i, e) for i, e in linhas if i not in feitos and e.strip()]
    if limite:
        pend = pend[:limite]
    for ini in range(0, len(pend), lote):
        parte = sorted(pend[ini : ini + lote], key=lambda x: len(x[1]))  # menos preenchimento
        indice.gravar([i for i, _ in parte], embedder.codificar([e for _, e in parte]))
        log(f"[embed] {min(ini + lote, len(pend))}/{len(pend)}")
    return len(pend)


def rrf(listas: list[list[str]], k: int = 60) -> list[tuple[str, float]]:
    """Reciprocal Rank Fusion: junta rankings de fontes diferentes sem calibrar escalas."""
    pontos: dict[str, float] = {}
    for lista in listas:
        for pos, id_ in enumerate(lista):
            pontos[id_] = pontos.get(id_, 0.0) + 1.0 / (k + pos + 1)
    return sorted(pontos.items(), key=lambda x: -x[1])

