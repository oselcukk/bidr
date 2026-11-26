"""Süre sınırlı süreç havuzu: her iş kendi alt sürecinde, iş başına süre sınırıyla.

`concurrent.futures.ProcessPoolExecutor` tek bir işi kesemez: takılan bir dosya (ör. dev sayfalı taranmış PDF'de
saatlerce süren OCR) bütün koşuyu bekletir. Burada her iş ayrı bir süreçtir (kendi süreç grubunda: OCR için başlattığı
`tesseract` alt süreçleriyle birlikte kesilir); sınırı aşan iş öldürülür ve yerine çağıranın verdiği "süre aşıldı"
sonucu konur, öbür işler sürer. Çökmüş (sonuç göndermeden biten) iş de koşuyu düşürmez: "beklenmedik bitiş" sonucu.

Maskeleme sonucunu belirlemez (yalnız iş dağıtımı): `bidr/mask` dışında, maskeleme önbelleğinin kod izine girmez.
"""
from __future__ import annotations

import multiprocessing as mp
import os
import signal
import time
from multiprocessing.connection import wait as _bekle

ORTAM_DOSYA = "BIDR_MASKE_DOSYA_SURESI"    # dosya başına taban süre sınırı (sn); 0: sınırsız
ORTAM_SAYFA = "BIDR_MASKE_SAYFA_SURESI"    # PDF'de sayfa başına ek süre (sn)
ORTAM_MB = "BIDR_MASKE_MB_SURESI"          # PDF dışı dosyada (görsel, arşiv, e-posta) MB başına ek süre (sn)
VARSAYILAN_DOSYA = 120.0
VARSAYILAN_SAYFA = 30.0
VARSAYILAN_MB = 10.0


def _ortam_sayi(ad: str, varsayilan: float) -> float:
    try:
        v = os.environ.get(ad)
        return float(v) if v not in (None, "") else varsayilan
    except ValueError:
        return varsayilan


def sure_ayari(dosya: float | None = None, sayfa: float | None = None, mb: float | None = None) -> dict | None:
    """Süre sınırı ayarı (komut satırı > ortam > varsayılan). Taban 0 ya da eksi: sınır yok (None)."""
    d = _ortam_sayi(ORTAM_DOSYA, VARSAYILAN_DOSYA) if dosya is None else float(dosya)
    if d <= 0:
        return None
    return {"dosya": d,
            "sayfa": max(0.0, _ortam_sayi(ORTAM_SAYFA, VARSAYILAN_SAYFA) if sayfa is None else float(sayfa)),
            "mb": max(0.0, _ortam_sayi(ORTAM_MB, VARSAYILAN_MB) if mb is None else float(mb))}


def pdf_sayfa_sayisi(yol) -> int | None:
    try:
        from pypdf import PdfReader
        r = PdfReader(str(yol))
        if r.is_encrypted:
            r.decrypt("")
        return len(r.pages)
    except Exception:          # noqa: BLE001 — okunamayan PDF: boyuta göre
        return None


def dosya_siniri(yol, ayar: dict | None) -> float | None:
    """Bir dosyanın süre sınırı (sn): taban + PDF'de sayfa başına, başka biçimde MB başına ek süre. Uzun ama olağan
    belgeler (170 sayfalık PDF, ekli e-posta arşivi) düz bir sınıra takılmasın; tek bir dosya koşuyu saatlerce
    tutmasın. `ayar` None: sınır yok."""
    if not ayar:
        return None
    s = float(ayar["dosya"])
    try:
        boyut = os.path.getsize(yol) / 1e6
    except OSError:
        boyut = 0.0
    sayfa = pdf_sayfa_sayisi(yol) if str(yol).lower().endswith(".pdf") else None
    if sayfa is not None:
        return s + ayar["sayfa"] * sayfa
    return s + ayar["mb"] * boyut


def _cocuk(fn, is_, conn) -> None:
    if hasattr(os, "setsid"):
        try:
            os.setsid()                     # kendi süreç grubu: kesilince alt süreçleri (tesseract) de gider
        except OSError:
            pass
    try:
        sonuc = ("tamam", fn(is_))
    except BaseException as e:              # noqa: BLE001 — sonuç olarak döner, koşu düşmez
        sonuc = ("istisna", f"{type(e).__name__}: {str(e)[:300]}")
    try:
        conn.send(sonuc)
    finally:
        conn.close()


def _oldur(p) -> None:
    if hasattr(os, "killpg"):
        try:
            if os.getpgid(p.pid) == p.pid:
                os.killpg(p.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            pass
    try:
        p.kill()
    except (OSError, AttributeError):
        pass
    p.join(10)


def calistir(fn, isler: list, *, isci: int = 1, sinir=None, zaman_asimi=None, beklenmedik=None, bitti=None,
             olduruldu=None, aralik: float = 1.0) -> list:
    """`fn(is)` her iş için ayrı alt süreçte, en çok `isci` eşzamanlı. → iş sırasıyla sonuçlar.

    `sinir(is)` → sn ya da None (sınır yok); aşılırsa süreç (grubuyla) öldürülür, sonuç `zaman_asimi(is, sn)`.
    Sonuç göndermeden biten ya da istisna fırlatan iş: `beklenmedik(is, neden)`. `bitti(i, k, sonuc)`:
    tamamlanma sırasıyla (i: kaçıncı biten, k: iş sırası). `olduruldu(pid)`: süreci öldürülen ya da sonuçsuz biten
    işin ardından (ör. sürecin bıraktığı ilerleme dosyasını silmek). `sinir` hiç verilmemişse ve tek işçiyse işler bu
    süreçte sırayla koşar (eski davranış)."""
    n = len(isler)
    sonuclar: list = [None] * n
    if sinir is None and isci <= 1:
        for k, j in enumerate(isler):
            sonuclar[k] = fn(j)
            if bitti:
                bitti(k + 1, k, sonuclar[k])
        return sonuclar
    ctx = mp.get_context()
    sira = list(range(n))
    calisan: dict[int, tuple] = {}            # k → (süreç, bağlantı, başlangıç, sınır)
    biten = 0

    def bitir(k: int, deger) -> None:
        nonlocal biten
        sonuclar[k] = deger
        biten += 1
        if bitti:
            bitti(biten, k, deger)

    try:
        while sira or calisan:
            while sira and len(calisan) < max(1, isci):
                k = sira.pop(0)
                al, ver = ctx.Pipe(duplex=False)
                p = ctx.Process(target=_cocuk, args=(fn, isler[k], ver))
                p.start()
                ver.close()
                lim = sinir(isler[k]) if sinir else None
                calisan[k] = (p, al, time.monotonic(), lim)
            hedefler = [x for p, al, _, _ in calisan.values() for x in (al, p.sentinel)]
            _bekle(hedefler, timeout=aralik)
            simdi = time.monotonic()
            for k, (p, al, bas, lim) in list(calisan.items()):
                deger, oldu, kesik = None, False, False
                if al.poll():
                    try:
                        durum, d = al.recv()
                    except (EOFError, OSError):
                        p.join(5)
                        durum, d = "istisna", f"süreç sonuç göndermeden bitti (çıkış {p.exitcode})"
                        kesik = True
                    p.join(30)
                    if durum == "tamam":
                        deger = d
                    else:
                        deger = beklenmedik(isler[k], d) if beklenmedik else None
                    oldu = True
                elif not p.is_alive():
                    p.join(5)
                    neden = f"süreç sonuç göndermeden bitti (çıkış {p.exitcode})"
                    deger = beklenmedik(isler[k], neden) if beklenmedik else None
                    oldu = kesik = True
                elif lim is not None and simdi - bas > lim:
                    _oldur(p)
                    deger = zaman_asimi(isler[k], lim) if zaman_asimi else None
                    oldu = kesik = True
                if oldu:
                    if kesik and olduruldu:
                        olduruldu(p.pid)
                    al.close()
                    del calisan[k]
                    bitir(k, deger)
    finally:
        for p, al, _, _ in calisan.values():       # kesinti (KeyboardInterrupt …): yetim süreç kalmasın
            _oldur(p)
            al.close()
    return sonuclar
