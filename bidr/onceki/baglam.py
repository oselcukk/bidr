"""`onceki-yil.json` → yazım ve doğrulama paketlerine eklenen karşılaştırma bölümü.

Bölüm yalnız raporu olan (çalışma alanında `onceki-yil.json` bulunan) birimde ve yalnız o ölçütün geçen yıl
kaydı varsa eklenir. Temel istemin DIŞINDADIR: `write prepare` metnin güncelliğini temel istem özetiyle
(`temel_istem_sha`) ölçer, bu bölüm o özete girmez. Böylece:
  - raporu olmayan bölümde paketler, istem özetleri ve metin kayıtları bayt bayt aynı kalır;
  - raporu sonradan yüklenen bölümde var olan metinler kendiliğinden yeniden yazılmaz; bölüm, bir sonraki
    yazımda ya da yeniden yazımda (yeni kanıt, OD değişimi, doğrulama reddi, `--redo`, `--only`) pakete girer;
  - var olan metinlere tek seferlik ekleme `bidr write karsilastirma` ile (bidr/onceki/karsilastirma.py).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .oku import DOSYA, SURUM

YAZIM_SINIRI = 1200      # yazım paketinde geçen yılın açıklamasından en çok bu kadar karakter
DOGRULAMA_SINIRI = 4000  # doğrulama paketinde (karşılaştırma iddiası buna karşı denetlenir)
KANIT_ADI_EN_COK = 10


def yol(ws_root: Path) -> Path:
    return Path(ws_root) / DOSYA


def yukle(ws_root: Path) -> dict | None:
    """Çalışma alanındaki `onceki-yil.json` (yoksa, bozuksa ya da sürümü farklıysa None)."""
    p = yol(ws_root)
    if not p.is_file():
        return None
    try:
        v = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(v, dict) or v.get("surum") != SURUM or not isinstance(v.get("olcutler"), dict):
        return None
    return v


def kayit(veri: dict | None, olcut: str) -> dict | None:
    """Ölçütün geçen yıl kaydı; açıklaması boşsa None (karşılaştırılacak metin yok)."""
    r = ((veri or {}).get("olcutler") or {}).get(olcut)
    return r if r and (r.get("aciklama") or "").strip() else None


def kisalt(metin: str, sinir: int) -> str:
    """Cümle sınırında kısaltır (sınır aşılırsa sonuna "[…]")."""
    metin = " ".join(metin.split())
    if len(metin) <= sinir:
        return metin
    kes = metin[:sinir]
    m = max(kes.rfind(". "), kes.rfind("]. "))
    if m > sinir * 0.5:
        kes = kes[:m + 1]
    return kes.rstrip() + " […]"


def yil_adi(donem: int | None) -> str:
    return str(donem - 1) if donem else "geçen yıl"


def _od_satiri(r: dict) -> str:
    od = r.get("od")
    if not od:
        return "geçen yıl OD: raporda belirtilmemiş"
    isaretli = r.get("od_isaretli") or []
    if len(isaretli) > 1:
        return f"geçen yıl OD: {min(isaretli)}–{max(isaretli)} (raporda birden çok düzey işaretli)"
    kay = {"isaret": "rubrikte işaretli", "kanit_kodlari": "kanıt kodlarındaki en yüksek düzey"}.get(r.get("od_kaynak"), "")
    return f"geçen yıl OD: {od}" + (f" ({kay})" if kay else "")


_ESKI_ATIF = re.compile(r"\s*\[[^\[\]]{0,30}OD\s*\d\s*\]")


def atifsiz(metin: str) -> str:
    """Geçen yılın kanıt atıfları (`[1_OD2]`, `[A.1.1-1-OD3]`, `[1-OD3]`) atılır: bu yılın atıf biçimiyle
    karışmasın, model geçen yılın numarasını bu yılın kanıtı sanmasın."""
    return _ESKI_ATIF.sub("", metin)


def ozet(r: dict, sinir: int) -> str:
    """Ölçütün geçen yıl özeti: OD, açıklama (kısaltılmış, atıfsız), kanıt adları (numarasız; kanıt değildir)."""
    lines = [_od_satiri(r), "geçen yılın açıklaması (atıfları çıkarıldı):",
             kisalt(atifsiz(r.get("aciklama") or ""), sinir)]
    adlar = [k["ad"] for k in r.get("kanitlar") or [] if k.get("ad")]
    if adlar:
        ek = len(adlar) - KANIT_ADI_EN_COK
        lines.append("geçen yıl gösterilen belgelerin adları: " + "; ".join(adlar[:KANIT_ADI_EN_COK])
                     + (f"; (+{ek} belge)" if ek > 0 else ""))
    return "\n".join(lines)


_YAZIM = Path(__file__).resolve().parents[1] / "tasks" / "write_criterion" / "onceki_yil.md"
_DOGRULAMA = Path(__file__).resolve().parents[1] / "tasks" / "verify_text" / "onceki_yil.md"
_KARSILASTIRMA_ISARETI = re.compile(r"\{\{(\w+)\}\}")


def _doldur(sablon: Path, **alan: str) -> str:
    return _KARSILASTIRMA_ISARETI.sub(lambda m: alan.get(m.group(1), m.group(0)), sablon.read_text(encoding="utf-8")).strip()


def yazim_bolumu(veri: dict | None, olcut: str, donem: int | None) -> str | None:
    """Yazım paketinin istemine eklenecek bölüm (yoksa None)."""
    r = kayit(veri, olcut)
    if r is None:
        return None
    return _doldur(_YAZIM, yil=yil_adi(donem), ozet=ozet(r, YAZIM_SINIRI))


def dogrulama_bolumu(veri: dict | None, olcut: str, donem: int | None) -> str | None:
    """Doğrulama paketinin istemine eklenecek bölüm (yoksa None)."""
    r = kayit(veri, olcut)
    if r is None:
        return None
    return _doldur(_DOGRULAMA, yil=yil_adi(donem), ozet=ozet(r, DOGRULAMA_SINIRI))


def iz(veri: dict | None, olcut: str) -> dict | None:
    """Pakete ve metin kaydına yazılan iz: hangi rapordan, hangi OD (karşılaştırma bağlamı kullanıldı)."""
    r = kayit(veri, olcut)
    if r is None:
        return None
    return {"kaynak_sha": ((veri or {}).get("kaynak") or {}).get("sha256", "")[:16], "od": r.get("od")}
