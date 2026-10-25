from collections import Counter

from . import rules
from .ner import Allowlist, palavras_minusculas, propagar
from .rules import Span


class Anonymizer:
    """Aplica regras determinísticas e NER; só o texto limpo deve ser persistido."""

    def __init__(self, nomes=None, allowlist=None, mascarar_cnpj=True):
        self.nomes = nomes
        self.allowlist = allowlist or Allowlist()
        self.mascarar_cnpj = mascarar_cnpj

    def anonymize(self, text: str | None, permitidos=()) -> tuple[str, Counter]:
        if not text:
            return text or "", Counter()
        spans = rules.detectar(text, self.mascarar_cnpj)
        if self.nomes is not None:
            extra = Allowlist(permitidos)
            protegidos = [(s.start, s.end) for s in spans]
            mascarar, permitir = [], []
            for sp in self.nomes.detectar(text):
                if any(sp.start < e and s < sp.end for s, e in protegidos):
                    continue
                nome = text[sp.start : sp.end]
                oficial = sp.label == "OFICIAL"
                permitido = oficial or self.allowlist.permite(nome) or extra.permite(nome)
                (permitir if permitido else mascarar).append(sp)
            mascarar = [Span(sp.start, sp.end, "NOME") for sp in mascarar]
            spans += mascarar + [
                sp for sp in propagar(text, mascarar, permitir + mascarar, palavras_minusculas(text))
                if not any(sp.start < e and s < sp.end for s, e in protegidos)
            ]
        limpo, stats = rules.aplicar(text, rules.unir(spans))
        # As regras são idempotentes; se algo ainda for detectado, mascara de novo.
        for _ in range(2):
            resto = rules.detectar(limpo, self.mascarar_cnpj)
            if not resto:
                break
            limpo, extra_stats = rules.aplicar(limpo, resto)
            stats += extra_stats
        return limpo, stats


def residual_pii(text: str | None, mascarar_cnpj=True) -> list[str]:
    """Rótulos de identificadores ainda detectáveis por regras no texto (deve ser vazio)."""
    if not text:
        return []
    return [s.label for s in rules.detectar(text, mascarar_cnpj)]
