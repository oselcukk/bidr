"""Sayfa görüntüsünün algısal karması (pHash): aynı kâğıdın iki ayrı taraması.

Aynı kâğıdın iki taraması farklı baytlardır (sha256 tutmaz) ve OCR'ları farklı gürültü taşır; ama
sayfa görüntüsü aynıdır. Her sayfa gri tonlamaya çevrilir, küçültülüp medyanla benek gürültüsü
atılır, içerik kutusuna kırpılır, `N × N` ızgarada iki boyutlu DCT alınır ve en düşük `K × K`
frekansın (DC hariç) medyana göre işaretinden `K² − 1` bitlik karma çıkar (pHash). Küçük döndürme
(±1°), tarayıcı gürültüsü, JPEG sıkıştırması ve çözünürlük farkı birkaç bit değiştirir; satır
düzeni farklı sayfa (başka uzunlukta yazı, tablo, fotoğraf) çok bit değiştirir.

pHash sayfa DÜZENİNİ ayırır, metni değil: aynı kalıpla yazılmış başka bir yazının ya da aynı
belgenin revizyonunun sayfası karmada yakın düşebilir. O yüzden görüntü tek başına kopya kanıtı
değildir; kopya kararı OCR metin benzerliğiyle (tarihler aynı, iki yönlü kapsama) BİRLİKTE verilir
(bidr/decide/dedup.py `scan_copy_pairs`). dHash denendi: metin sayfasında komşu hücre farkı gürültü
düzeyinde kalıyor, aynı sayfanın iki taraması başka sayfadan ayrılmıyordu.

Kopya kararı (`same_pages`): sayfa sayısı eşit ve her sayfanın karma uzaklığı (Hamming)
≤ `MAX_BITS`. Görüntü ya da kişisel veri saklanmaz; yalnız karma (onaltılık metin) önbelleğe yazılır
(`work/_durum/goruntu-karma.json`, doc_id → karmalar; doc_id içerik özetidir, dosya değişirse değişir).

Görüntü kaynağı: PDF sayfaları `pdftoppm` (OCR için zaten gerekli) ile düşük çözünürlükte; görüntü
dosyaları Pillow ile. Diğer biçimler (docx, xlsx, e-posta) karmasızdır: tarama kopyası sayılmaz
(birebir/yakın metin kopyası bidr/decide/dedup.py'nin metin yoluyla bulunur).
"""
from __future__ import annotations

import json
import math
import shutil
import subprocess
import tempfile
from pathlib import Path

N = 32                    # DCT ızgarası
K = 12                    # düşük frekans bloğu (K² − 1 = 143 bit)
MAX_BITS = 32             # sayfa başına en çok farklı bit (≈ %22). Sentetik ölçüm (tests/test_kopya_tarama.py):
                          # aynı sayfanın ±1° döndürülmüş, gürültülü, JPEG iki taraması 2–24 bit; satır düzeni
                          # farklı sayfa ≥ 46 bit. Aynı düzenli başka yazı 14–44 bit: metin ayırır.
DPI = 40                  # PDF sayfası çizim çözünürlüğü (karma için yeter; hızlı)
MAX_PAGES = 40            # bundan uzun belge karmalanmaz (tarama kopyası adayı değil)
NORM_W = 300              # karma öncesi ortak genişlik (piksel)
TRIM_LEVEL = 200          # kırpma: bundan koyu piksel içerik sayılır (0-255)
IMAGE_EXT = frozenset({".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif", ".webp", ".heic"})
CACHE = Path("work") / "_durum" / "goruntu-karma.json"


_COS = [[math.cos(math.pi * (2 * x + 1) * u / (2 * N)) for x in range(N)] for u in range(K)]


def phash(img) -> int:
    """Pillow görüntüsünün pHash'i (K² − 1 bit, tamsayı)."""
    from PIL import Image, ImageFilter, ImageOps
    g = ImageOps.exif_transpose(img).convert("L")
    # önce küçült + medyan: tarayıcı tozu/benek ve JPEG gürültüsü ortalanır, kırpma kutusunu bozmaz
    g = g.resize((NORM_W, max(1, round(g.height * NORM_W / max(1, g.width)))), Image.Resampling.BOX)
    g = g.filter(ImageFilter.MedianFilter(3))
    g = ImageOps.autocontrast(g, cutoff=1)
    # içerik kutusu: koyu piksellerin sınırı (beyaz pay/ölçek farkı karmayı kaydırmasın)
    box = g.point(lambda v: 255 if v < TRIM_LEVEL else 0).getbbox()
    if box and (box[2] - box[0]) > g.width * 0.2 and (box[3] - box[1]) > g.height * 0.2:
        g = g.crop(box)
    s = g.resize((N, N), Image.Resampling.BOX)
    px = list(s.tobytes())
    rows = [px[y * N:(y + 1) * N] for y in range(N)]
    tmp = [[sum(c[x] * r[x] for x in range(N)) for c in _COS] for r in rows]          # satır DCT (K)
    vals = [sum(_COS[v][y] * tmp[y][u] for y in range(N)) for v in range(K) for u in range(K)][1:]
    med = sorted(vals)[len(vals) // 2]
    bits = 0
    for x in vals:
        bits = (bits << 1) | (x > med)
    return bits


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def same_pages(ha: list[str] | None, hb: list[str] | None, max_bits: int = MAX_BITS) -> bool:
    """İki belgenin sayfa karmaları aynı kâğıdı mı gösteriyor: sayfa sayısı eşit, her sayfa eşikte."""
    if not ha or not hb or len(ha) != len(hb):
        return False
    return all(hamming(int(x, 16), int(y, 16)) <= max_bits for x, y in zip(ha, hb))


def _hex(v: int) -> str:
    return f"{v:0{(K * K + 2) // 4}x}"


def page_hashes(path: Path) -> list[str] | None:
    """Dosyanın sayfa karmaları (onaltılık) ya da None (desteklenmeyen biçim / okunamadı)."""
    path = Path(path)
    ext = path.suffix.lower()
    try:
        if ext in IMAGE_EXT:
            from PIL import Image, ImageSequence
            with Image.open(path) as im:
                frames = [f.copy() for i, f in zip(range(MAX_PAGES + 1), ImageSequence.Iterator(im))]
            if len(frames) > MAX_PAGES:
                return None
            return [_hex(phash(f)) for f in frames]
        if ext == ".pdf":
            return _pdf_hashes(path)
    except Exception:          # bozuk/okunamayan dosya: karma yok (kopya sayılmaz)
        return None
    return None


def _pdf_hashes(path: Path) -> list[str] | None:
    if not shutil.which("pdftoppm"):
        return None
    from PIL import Image
    with tempfile.TemporaryDirectory(prefix="bidr-karma-") as td:
        r = subprocess.run(["pdftoppm", "-r", str(DPI), "-gray", "-png", "-l", str(MAX_PAGES + 1),
                            str(path), str(Path(td) / "s")], capture_output=True, timeout=300)
        if r.returncode != 0:
            return None
        files = sorted(Path(td).glob("s-*.png"), key=lambda p: int(p.stem.rsplit("-", 1)[1]))
        if not files or len(files) > MAX_PAGES:
            return None
        out = []
        for p in files:
            with Image.open(p) as im:
                out.append(_hex(phash(im)))
        return out


class HashCache:
    """doc_id → sayfa karmaları; çalışma alanında önbellekli (yalnız karma). Kaynak dosya envanter
    satırından (`rel_path`; arşiv üyesi açılmış kopyadan) bulunur. Kaynak yoksa karma yok."""

    def __init__(self, ws_root: Path, src_root: Path | None = None):
        self.ws_root = Path(ws_root)
        self.path = self.ws_root / CACHE
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        self.data: dict = data if isinstance(data, dict) and data.get("surum") == self.surum() else {
            "surum": self.surum(), "belgeler": {}}
        self.src_root = Path(src_root) if src_root else self._src_root()
        self._rows: dict | None = None
        self.dirty = False

    @staticmethod
    def surum() -> str:
        return f"phash{N}x{K}-w{NORM_W}-dpi{DPI}-trim{TRIM_LEVEL}"

    def _src_root(self) -> Path | None:
        try:
            from bidr.init.config import load_section
            k = (load_section(self.ws_root) or {}).get("kaynak")
        except Exception:
            k = None
        return Path(k).expanduser() if k else None

    def _row(self, did: str) -> dict | None:
        if self._rows is None:
            self._rows = {}
            inv = self.ws_root / "inventory.csv"
            if inv.exists():
                import csv
                with open(inv, encoding="utf-8", newline="") as f:
                    for r in csv.DictReader(f):
                        d = r.get("doc_id")
                        if d and (d not in self._rows or (self._rows[d].get("dup_of") and not r.get("dup_of"))):
                            self._rows[d] = r
        return self._rows.get(did)

    def get(self, did: str) -> list[str] | None:
        b = self.data["belgeler"]
        if did in b:
            return b[did]
        row = self._row(did)
        h = None
        if row and row.get("rel_path") and self.src_root:
            from bidr.ingest.containers import source_path
            try:
                p = source_path(self.src_root, row["rel_path"], self.ws_root)
            except Exception:
                p = None
            if p is not None:
                h = page_hashes(p)
                b[did] = h                 # dosya bulundu: sonuç (karmasız biçim dahil) önbelleğe
                self.dirty = True
        return h                           # kaynak bulunamadı: önbelleğe yazılmaz (sonra yeniden denenir)

    def save(self) -> None:
        if not self.dirty:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=0), encoding="utf-8")
        self.dirty = False
