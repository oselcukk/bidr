"""Bölge listesi (maskeleme-raporu.json dosya kaydında `bolgeler`) ve insan kararları.

Her tespit (desen, etiket alanı, imza, okunamayan sayfa) sayfa koordinatında (PDF puanı) bir
bölgedir:

    {"id": "<dosya-sha8>-s<sayfa>-<sıra>", "sayfa": 1, "kutu": [x0, y0, x1, y1],
     "tur": "imza" | "el_yazisi_alan" | "kisisel_veri" | "okunamayan_sayfa",
     "karar": "kapatildi" | "onay_bekliyor" | "birakildi", "neden": "…", "kaynak": "kural adı",
     "guven": 0.0-1.0, "geri_basilan": null, "kapali": true | false}

`kapali`: kutu maskeli kopyada kapatıldı mı. `kapatildi` her zaman kapalıdır; `onay_bekliyor` bölge
çoğunlukla açıktır (inceleme kopyasında renkli kesik çerçeveyle işaretlenir), yalnız metinle örtüşen imza
(ad/unvan yalnız OCR'dan okundu: "geri basma gerekli mi") kapalı tutulur.

Kullanıcı bölgesi (`bidr maskele ciz`): `kaynak`/`tur` `kullanici`, kimlik `<sha8>-s<sayfa>-k<n>`, karar
satırında `kutu` ve `sayfa`; sonraki her maskeleme koşusunda gerçek redaksiyon olarak uygulanır. Silme:
`{"id", "karar": "sil"}` (yalnız kullanıcı bölgesi).

Kimlik kararlıdır: aynı girdi + aynı kurallar → aynı kimlik. Sıra sayfa içinde önce ilk turdaki
tespitler (yukarıdan aşağı, soldan sağa), sonra kapatmadan sonra belirenler ve yeniden taramanın
bulduğu açıklanamayan adaylar.

İnsan kararları `<ws>/maskeleme-kararlari.jsonl` (`{"id", "karar": "kapat"|"birak", "kim", "zaman",
"kutu"?, "tur"?}`; aynı kimliğin son satırı geçerli). Bir sonraki `bidr maskele` bölgeyi kimliğiyle
bulur: "kapat" → kapatılır, "birak" → açık bırakılır; karar verilmiş bölge yeniden sorulmaz. Kararda
kutu kayıtlıysa bölgenin kutusuyla örtüşmesi aranır (kural değişip sıra kaydıysa karar yanlış bölgeye
uygulanmaz; bölge yeniden onay bekler, uyarı verilir).

Bağlantı noktaları (m1 imza, m3 el yazısı şeritleri): `saglayici("imza")` / `saglayici("el_yazisi")`
modülde varsa fonksiyonu döndürür.
- imza (m1, henüz yok): PDF sayfası için `fn(page, rules, ps) -> list[dict]`, görsel için
  `fn(img, rules, scan, olcek) -> list[dict]` (kutu puan; id/karar verilmezse burada atanır). Varsa eski
  imza çıktısından (raster/imza Result) bölge türetilmez.
- el yazısı (m3, `alan.el_yazisi_bolgeleri(img, words, sayfa, dosya, olcek, more, sablonlar, kararlar,
  sira0)`): `raster.add_label_fields` `find_fields` yerine onu çağırır (`olcek=1`, piksel kutu,
  `kararlar` verilmez); m3'ün kimlikleri atılır, kimliği ve kararı bu toplayıcı verir (m1 bölgeleriyle
  kimlik çakışmaz).
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

KARARLAR = "maskeleme-kararlari.jsonl"
KAPATILDI, ONAY, BIRAKILDI = "kapatildi", "onay_bekliyor", "birakildi"
TURLER = ("imza", "el_yazisi_alan", "kisisel_veri", "okunamayan_sayfa", "kullanici")
KULLANICI = "kullanici"
ESLESME = 0.5                       # karar kutusu ↔ bölge kutusu örtüşmesi (küçüğün alanına oranla)

# m1/m3 sağlayıcılarının aranacağı modüller ve fonksiyon adları
_SAGLAYICI = {"imza": (("bidr.mask.yapi", "imza_bolgeleri"), ("bidr.mask.imza", "imza_bolgeleri")),
              "el_yazisi": (("bidr.mask.sablon", "el_yazisi_bolgeleri"), ("bidr.mask.alan", "el_yazisi_bolgeleri"))}


def saglayici(ad: str):
    """m1/m3 bölge fonksiyonu (varsa)."""
    import importlib
    for mod, fn in _SAGLAYICI.get(ad, ()):
        try:
            m = importlib.import_module(mod)
        except ImportError:
            continue
        f = getattr(m, fn, None)
        if callable(f):
            return f
    return None


def yeni(sayfa: int, kutu, tur: str, karar: str, neden: str, kaynak: str, guven: float,
         geri_basilan: str | None = None) -> dict:
    return {"id": None, "sayfa": int(sayfa), "kutu": [round(float(v), 2) for v in kutu], "tur": tur,
            "karar": karar, "neden": neden, "kaynak": kaynak, "guven": round(float(guven), 2),
            "geri_basilan": geri_basilan, "kapali": karar == KAPATILDI}


def alan(k) -> float:
    return max(0.0, k[2] - k[0]) * max(0.0, k[3] - k[1])


def ortusme(a, b) -> float:
    """Kesişim alanı / küçük kutunun alanı."""
    ix = min(a[2], b[2]) - max(a[0], b[0])
    iy = min(a[3], b[3]) - max(a[1], b[1])
    if ix <= 0 or iy <= 0:
        return 0.0
    return ix * iy / max(1e-6, min(alan(a), alan(b)))


# ---------------------------------------------------------------- kararlar dosyası

def kararlar_yolu(ws: Path) -> Path:
    return Path(ws) / KARARLAR


def kararlar_yukle(ws: Path | None) -> dict[str, dict]:
    """id → son karar satırı. Bozuk satırlar atlanır; "sil" satırı kullanıcı bölgesini kaldırır."""
    out: dict[str, dict] = {}
    if ws is None:
        return out
    p = kararlar_yolu(ws)
    if not p.is_file():
        return out
    for ln in p.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            d = json.loads(ln)
        except ValueError:
            continue
        if isinstance(d, dict) and d.get("id") and d.get("karar") in ("kapat", "birak"):
            out[str(d["id"])] = d
        elif isinstance(d, dict) and d.get("id") and d.get("karar") == "sil":
            out.pop(str(d["id"]), None)
    return out


def kullanici_id(ws: Path, sha8: str, sayfa: int) -> str:
    """Yeni kullanıcı bölgesi kimliği `<sha8>-s<sayfa>-k<n>` (silinmişler dahil hiç kullanılmamış n)."""
    p = kararlar_yolu(ws)
    used = set()
    pre = f"{sha8}-s{int(sayfa)}-k"
    if p.is_file():
        for ln in p.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                i = str(json.loads(ln).get("id") or "")
            except (ValueError, AttributeError):
                continue
            if i.startswith(pre) and i[len(pre):].isdigit():
                used.add(int(i[len(pre):]))
    n = 1
    while n in used:
        n += 1
    return f"{pre}{n}"


def satir_yaz(ws: Path, d: dict) -> dict:
    with open(kararlar_yolu(ws), "a", encoding="utf-8") as f:
        f.write(json.dumps(d, ensure_ascii=False) + "\n")
    return d


def karar_yaz(ws: Path, bolge_id: str, karar: str, kim: str | None = None, *, kutu=None, tur=None,
              kaynak=None) -> dict:
    if karar not in ("kapat", "birak"):
        raise ValueError("karar 'kapat' ya da 'birak' olmalı")
    d = {"id": bolge_id, "karar": karar, "kim": kim or os.environ.get("USER") or "?",
         "zaman": datetime.now().astimezone().isoformat(timespec="seconds")}
    if kutu is not None:
        d["kutu"] = list(kutu)
    if tur:
        d["tur"] = tur
    if kaynak:
        d["kaynak"] = kaynak
    p = kararlar_yolu(ws)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(d, ensure_ascii=False) + "\n")
    return d


def dosya_kararlari(kararlar: dict[str, dict], sha8: str) -> dict[str, dict]:
    pre = f"{sha8}-s"
    return {k: v for k, v in kararlar.items() if k.startswith(pre)}


# ---------------------------------------------------------------- dosya bağlamı

class Baglam:
    """Tek dosyanın bölgeleri: kimlik atama ve kararların uygulanması."""

    def __init__(self, sha8: str, kararlar: dict[str, dict] | None = None):
        self.sha8 = sha8
        self.kararlar = kararlar or {}
        self.bolgeler: list[dict] = []
        self.uyarilar: list[str] = []
        self._sira: dict[int, int] = {}

    def _id(self, sayfa: int) -> str:
        n = self._sira.get(sayfa, 0) + 1
        self._sira[sayfa] = n
        return f"{self.sha8}-s{sayfa}-{n}"

    def kullanici_bolgeleri(self, sayfa: int) -> list[dict]:
        """Bu dosyanın `sayfa`'sına kullanıcının çizdiği bölgeler (karar satırından; kimlik hazır)."""
        out = []
        for i, d in sorted(self.kararlar.items()):
            if d.get("kaynak") != KULLANICI or int(d.get("sayfa") or 0) != int(sayfa) or not d.get("kutu"):
                continue
            b = yeni(sayfa, d["kutu"], KULLANICI, KAPATILDI if d.get("karar") == "kapat" else BIRAKILDI,
                     f"kullanıcı çizimi ({d.get('kim') or '?'})", KULLANICI, 1.0)
            b["id"] = i
            b["_etiket"] = "[MASKELI]"
            out.append(b)
        return out

    def _uygula(self, b: dict) -> None:
        d = self.kararlar.get(b["id"])
        if d is None:
            return
        if (d.get("kutu") and ortusme(d["kutu"], b["kutu"]) < ESLESME) or \
                (d.get("tur") and d["tur"] != b["tur"]) or (d.get("kaynak") and d["kaynak"] != b["kaynak"]):
            self.uyarilar.append(f"{b['id']}: karar bu bölgeyle eşleşmiyor (kurallar değişmiş olabilir); "
                                 "karar uygulanmadı")
            return
        b["karar"] = KAPATILDI if d["karar"] == "kapat" else BIRAKILDI
        b["insan"] = {"karar": d["karar"], "kim": d.get("kim"), "zaman": d.get("zaman")}

    def sayfa(self, sayfa: int, bolgeler: list[dict], *, ilk: bool = True) -> list[dict]:
        """Sayfanın bölgelerine kimlik verir ve kararları uygular (yerinde). `ilk`: sayfanın ilk turu
        (geometriye göre sıralanır); sonraki turlar geldiği sırayla eklenir."""
        if ilk:
            bolgeler = sorted(bolgeler, key=lambda b: (round(b["kutu"][1], 0), round(b["kutu"][0], 0),
                                                       TURLER.index(b["tur"]) if b["tur"] in TURLER else 9))
        for b in bolgeler:
            b["sayfa"] = sayfa
            if not b.get("id"):
                b["id"] = self._id(sayfa)
            b.setdefault("geri_basilan", None)
            self._uygula(b)
            b["kapali"] = b["karar"] == KAPATILDI or (b["karar"] == ONAY and bool(b.get("kapali")))
            self.bolgeler.append(b)
        return bolgeler

    def acikla(self, aday: dict, esik: float = ESLESME) -> dict | None:
        """Yeniden taramanın adayı bilinen bir bölgeyle örtüşüyor mu (aynı sayfa, aynı tür: tam sayfa
        okunamayan bölge sayfadaki küçük bir imza kutusuyla "açıklanmasın")."""
        best, bo = None, 0.0
        for b in self.bolgeler:
            if b["sayfa"] != aday["sayfa"] or b["tur"] != aday["tur"]:
                continue
            o = ortusme(b["kutu"], aday["kutu"])
            if o >= esik and o > bo:
                best, bo = b, o
        return best


def onay_bekleyen(bolgeler: list[dict] | None) -> list[dict]:
    return [b for b in bolgeler or [] if b.get("karar") == ONAY]


def ozet(bolgeler: list[dict] | None) -> dict:
    from collections import Counter
    c = Counter(b.get("karar") for b in bolgeler or [])
    return {k: c.get(k, 0) for k in (KAPATILDI, ONAY, BIRAKILDI)}
