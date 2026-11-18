"""Kılavuz biçim kuralları (FR-0833 "Yazım Kuralları" ve "Kanıt Gösterimi"; kurumsal gereksinim K31).

Değerler config.yaml `rapor.denetim` ile (anahtar anahtar) ve CLI ile değiştirilebilir.

Paragraf sonrası aralık: kılavuz metni "sonrası 0,6 nk" der; render 6 pt yazar (geçen yılın
raporlarında uygulanan değer, yazım hatası kabul edildi). Hangisinin doğru olduğu kuruma
sorulacak; o güne dek varsayılan render ile aynı 6 pt'dir. Kurum 0,6 nk derse
`rapor.denetim.paragraf_sonrasi_nk: 0.6` (ya da `bidr denetle --paragraf-sonrasi 0.6`).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields

KILAVUZ_SONRASI_NK = 0.6     # kılavuz metnindeki değer (bilgi; varsayılan değil)


@dataclass
class Rules:
    yazi_tipi: str = "Times New Roman"
    govde_punto: float = 10
    baslik_punto: float = 12
    aciklama_punto: float = 10          # şekil/tablo açıklaması (üstte, sağa dayalı, italik)
    paragraf_oncesi_nk: float = 0
    paragraf_sonrasi_nk: float = 6      # kılavuz "0,6 nk"; kurumdan doğrulanacak (yukarıda)

    def twip(self, nk: float) -> int:
        return round(nk * 20)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["not"] = (f"paragraf_sonrasi_nk={self.paragraf_sonrasi_nk:g}; kılavuz metni "
                    f"'{KILAVUZ_SONRASI_NK:g} nk' der, render 6 pt yazar — kurumdan doğrulanacak")
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
