"""Ortak yardımcılar. Sahibi: şef (lane'ler değiştirmez, ihtiyaç olursa raporda ister)."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterable, Iterator

DOC_ID_LEN = 16


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while b := f.read(chunk):
            h.update(b)
    return h.hexdigest()


def doc_id_from_sha(sha: str) -> str:
    """Belge kimliği = içerik sha256'sının ilk 16 hanesi. Dosya adına asla dayanmaz."""
    return sha[:DOC_ID_LEN]


def doc_id(path: Path) -> str:
    return doc_id_from_sha(sha256_file(path))


def read_jsonl(path: Path) -> Iterator[dict]:
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def write_jsonl(path: Path, rows: Iterable[dict]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            n += 1
    tmp.replace(path)
    return n


class Workspace:
    """Çalışma klasörü düzeni (repo dışında, gerçek veri burada).

    <ws>/inventory.csv        ingest: her dosya bir satır
    <ws>/text/<doc_id>.txt    ingest: çıkarılan metin; sayfalar '\\f' ile ayrılır
    <ws>/documents.jsonl      identify: belge türü, tarih, çalışma adı
    <ws>/labels.jsonl         labels: insan etiketleri (değerlendirme seti)
    """

    def __init__(self, root: Path):
        self.root = Path(root).expanduser().resolve()

    @property
    def inventory(self) -> Path:
        return self.root / "inventory.csv"

    @property
    def text_dir(self) -> Path:
        return self.root / "text"

    def text_path(self, did: str) -> Path:
        return self.text_dir / f"{did}.txt"

    @property
    def documents(self) -> Path:
        return self.root / "documents.jsonl"

    @property
    def labels(self) -> Path:
        return self.root / "labels.jsonl"

    def ensure(self) -> "Workspace":
        self.root.mkdir(parents=True, exist_ok=True)
        self.text_dir.mkdir(exist_ok=True)
        return self
