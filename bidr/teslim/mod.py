"""Teslim modu (config.yaml `rapor.teslim`).

- `dekanlik` (varsayılan): rapor ve kanıt dosyaları dekanlığa teslim edilir, yüklemeyi dekanlık
  yapar; bölüm kanıtlara bağlantı vermez. Bağlantısız kanıt bilgi düzeyindedir (yayımı
  engellemez); web kanıtının özgün adresi kanıt listesinde görünür ve `bidr teslim` web
  sayfalarının alınma tarihli PDF kopyasını üretir. Kanıt klasörü kök bağlantısından
  (`baglanti_kaynagi: klasor`) türeyen bağlantı rapora girmez (yükleme bölümün işi değil).
- `baglanti`: birim kanıt klasörünü kendisi yükler ve raporda kanıt adları bağlantılıdır
  (`rapor.kanit_kok_baglanti`, review.xlsx bağlantıları); eski davranış.
"""
from __future__ import annotations

from pathlib import Path

DEKANLIK, BAGLANTI = "dekanlik", "baglanti"
MODLAR = (DEKANLIK, BAGLANTI)
VARSAYILAN = DEKANLIK


def teslim_modu(ws_root: Path | None) -> str:
    """Çalışma alanının teslim modu. Geçersiz değer ValueError (sessizce varsayılana düşmez)."""
    if ws_root is None:
        return VARSAYILAN
    from bidr.write.sources import rapor_section
    v = rapor_section(Path(ws_root)).get("teslim")
    if v is None or str(v).strip() == "":
        return VARSAYILAN
    v = str(v).strip().lower()
    if v not in MODLAR:
        raise ValueError(f"config.yaml rapor.teslim: '{v}' geçersiz (seçenekler: {' | '.join(MODLAR)})")
    return v
