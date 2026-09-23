"""Cofre temporário dos arquivos que os agentes produzem (Word revisado, planilhas).

Uma ferramenta devolve TEXTO ao modelo, não arquivo. Então o arquivo fica aqui
por algumas horas com um id, o modelo cita esse id na resposta e a tela troca o
id por um botão de download. Memória do processo mesmo: é entrega do momento, não
acervo — o que precisa durar vai para o Drive do escritório.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

_FUSO = timezone(timedelta(hours=-3))
# Tempo de vida: o usuário baixa na hora; passou disso, é lixo ocupando memória.
VALIDADE = timedelta(hours=3)
# Teto de arquivos guardados ao mesmo tempo (o servidor gratuito tem 512 MB).
_MAX_ARQUIVOS = 40


@dataclass
class ArquivoGerado:
    """Um arquivo pronto para download, preso ao escritório que o gerou."""

    nome: str
    tipo: str
    dados: bytes
    escritorio_id: str
    criado_em: datetime = field(default_factory=lambda: datetime.now(_FUSO))

    @property
    def vencido(self) -> bool:
        return datetime.now(_FUSO) - self.criado_em > VALIDADE


class CofreArquivos:
    """Guarda por id os arquivos gerados na conversa."""

    def __init__(self) -> None:
        self._itens: dict[str, ArquivoGerado] = {}

    def guardar(self, arquivo: ArquivoGerado) -> str:
        self._limpar()
        identificador = uuid.uuid4().hex[:16]
        self._itens[identificador] = arquivo
        return identificador

    def pegar(self, identificador: str, escritorio_id: str) -> ArquivoGerado | None:
        """Devolve o arquivo — só para o escritório que o gerou."""
        arquivo = self._itens.get(identificador)
        if arquivo is None or arquivo.vencido or arquivo.escritorio_id != escritorio_id:
            return None
        return arquivo

    def _limpar(self) -> None:
        for identificador in [i for i, a in self._itens.items() if a.vencido]:
            self._itens.pop(identificador, None)
        excedente = len(self._itens) - _MAX_ARQUIVOS
        if excedente > 0:
            antigos = sorted(self._itens.items(), key=lambda par: par[1].criado_em)
            for identificador, _ in antigos[:excedente]:
                self._itens.pop(identificador, None)
