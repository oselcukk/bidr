"""Kılavuz biçim kuralları (FR-0833 "Yazım Kuralları" ve "Kanıt Gösterimi"; kurumsal gereksinim K31).

Değerler config.yaml `rapor.denetim` ile (anahtar anahtar) ve CLI ile değiştirilebilir.

Paragraf sonrası aralık: kılavuzdaki "sonrası 0,6 nk" kurumca doğrulandı (2026-11-19); render de
0,6 nk yazar. Başka bir değer gerekirse `rapor.denetim.paragraf_sonrasi_nk` (ya da
`bidr denetle --paragraf-sonrasi`).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields

KILAVUZ_SONRASI_NK = 0.6     # kılavuz metnindeki değer (kurumca doğrulandı)


@dataclass
class Rules:
    yazi_tipi: str = "Times New Roman"
    govde_punto: float = 10
    baslik_punto: float = 12
    aciklama_punto: float = 10          # şekil/tablo açıklaması (üstte, sağa dayalı, italik)
    paragraf_oncesi_nk: float = 0
    paragraf_sonrasi_nk: float = KILAVUZ_SONRASI_NK

    def twip(self, nk: float) -> int:
        return round(nk * 20)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["not"] = (f"paragraf_sonrasi_nk={self.paragraf_sonrasi_nk:g}; kılavuz metni "
                    f"'{KILAVUZ_SONRASI_NK:g} nk' der (kurumca doğrulandı)")
        return d


def load_rules(section: dict | None = None, **override) -> Rules:
    """`section`: config.yaml `rapor.denetim` sözlüğü; `override`: CLI (None olanlar yok sayılır)."""
    r = Rules()
    names = {f.name for f in fields(Rules)}
    for src in (section or {}, override):
        for k, v in src.items():
            if k in names and v is not None:
                setattr(r, k, str(v) if isinstance(getattr(r, k), str) else float(v))
    return r
