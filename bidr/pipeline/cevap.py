"""Model cevabının reddi: bütün ajan cevaplı aşamaların ortak kuralı.

Cevabın biçim/doğrulama sorunu işi durdurup yöneticiye düşmez: kod normalleştirebildiğini normalleştirir
(şema enum'unda bilinmeyen değer → `diger`, `normalize_enums`), normalleştiremediğini bir DENEME sayar:

  1. Ret → cevap `<anahtar>.out.json.red<n>.eski` olarak kenara alınır (silinmez). Paket yeniden cevapsızdır:
     ajan var olan cevabın üstüne yazmadan yeni `<anahtar>.out.json` yazar (panelin cevap koruması —
     var olan cevap ezilmez — yeniden yazımı engellemez). Gerekçe aşamanın GECERSIZ.md'sinde kalır.
  2. Aynı nedenle AYNI_NEDEN_SINIRI kez (ya da nedeni ne olursa olsun DENEME_SINIRI kez) ret → öğe
     `elle_bakilmali`: yeniden istenmez, son cevap yerinde kalır (aynı cevap yeniden denenmez), aşamanın
     ELLE-BAKILMALI.md'sine girer, `bidr next` uyarısında görünür ve aşama onu BEKLEMEZ. Öğenin anlamı aşamaya
     göredir (betimleme yok sayılır, karar insan incelemesine düşer, ad kural adında kalır …); bunu aşamanın
     kodu uygular.

Deneme kaydı çalışma alanı kökünde `cevap-denemeleri.json` (paket klasörlerinde değil: hiçbir aşama ya da panel
onu paket sanmaz): {dizin: {anahtar: {parmak, denemeler: [...], elle?: {...}}}}. `parmak` öğenin belgeye özgü
girdisidir (paket istem özeti ya da görüntü özeti): değişirse (yeniden prepare) sayaç ve elle işareti baştan.
Cevap kabul edilince öğenin kaydı silinir.

Sayaçlar aşamanın kendi tur sınırlarından (yeniden yazım turu, doğrulama turu) bağımsızdır: onlar içerik
kararıdır, bu yalnız cevabın biçimi/kod denetimi. Döngü olmaz: her ret bir deneme, sınır en çok DENEME_SINIRI."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from bidr.llm.jsonx import normalize_enums  # noqa: F401  (ortak kuralın parçası; validate_output uygular)

DOSYA = "cevap-denemeleri.json"
AYNI_NEDEN_SINIRI = 2
DENEME_SINIRI = 3
ELLE = "elle_bakilmali"
ELLE_MD = "ELLE-BAKILMALI.md"
_ESKI = {"work/transcribe": "denemeler.json"}   # 4ee6d1c'nin aşama klasöründeki kaydı (taşınır)


def sha(s: str | bytes) -> str:
    return hashlib.sha256(s.encode("utf-8") if isinstance(s, str) else s).hexdigest()


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _load_all(root: Path) -> dict:
    p = root / DOSYA
    try:
        d = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except (OSError, ValueError):
        d = {}
    return d if isinstance(d, dict) else {}


class Denemeler:
    """Bir aşama klasörünün (`dizin`, ws'ye göreli: "work/describe") ret kayıtları."""

    def __init__(self, ws_root: Path, dizin: str):
        self.root, self.dizin = Path(ws_root), dizin
        self._hepsi = _load_all(self.root)
        self.kayit: dict[str, dict] = self._hepsi.setdefault(dizin, {})
        self._eski = None
        if dizin in _ESKI and not self.kayit:
            p = self.root / dizin / _ESKI[dizin]
            try:
                old = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
            except (OSError, ValueError):
                old = {}
            for k, e in (old or {}).items():
                if isinstance(e, dict):
                    self.kayit[k] = {"parmak": e.get("gorsel_sha"), "denemeler": list(e.get("denemeler") or [])}
            self._eski = p if p.exists() else None
        self.kirli = self._eski is not None
        self.cekilen: set[str] = set()

    # -- okuma -----------------------------------------------------------------------------------
    def son(self, key: str) -> dict | None:
        return ((self.kayit.get(key) or {}).get("denemeler") or [None])[-1]

    def kenarda(self, key: str) -> dict | None:
        """Son deneme kenara alındıysa (paket yeni cevap bekliyor) o deneme."""
        s = self.son(key)
        return s if s and s.get("dosya") else None

    def elle(self, key: str, parmak=None) -> dict | None:
        """Öğe elle bakılmalı işaretli mi (`parmak` verilirse yalnız aynı girdiyle)."""
        e = self.kayit.get(key) or {}
        el = e.get("elle")
        if not el or (parmak is not None and el.get("parmak") != parmak):
            return None
        return el

    def elle_hepsi(self) -> dict[str, dict]:
        return {k: e["elle"] for k, e in sorted(self.kayit.items()) if e.get("elle")}

    def elle_ayni(self, key: str, cevap_sha: str, parmak=None) -> dict | None:
        """Bu cevap zaten elle bakılmalı kararı verilmiş cevap mı (yeniden denenmez)."""
        el = self.elle(key, parmak)
        return el if el and el.get("cevap_sha") == cevap_sha else None

    # -- yazma -----------------------------------------------------------------------------------
    def reddet(self, key: str, outp: Path, kod: str, hatalar: list[str], *, parmak, model: str | None = None,
               kenara: bool = True, ek: dict | None = None) -> dict:
        """Ret bir denemedir. Döner: {"sonuc": "yeniden" | "elle", "neden", "deneme", "dosya"?}.
        Sınırın altında cevap kenara alınır (`kenara=False`: aşama kendisi karar verir, dosya yerinde kalır);
        sınırda öğe elle bakılmalı olur ve cevap yerinde kalır."""
        raw = outp.read_bytes() if outp.exists() else b""
        cs = sha(raw)
        e = self.kayit.get(key)
        if not e or e.get("parmak") != parmak:          # yeni girdi: sayaç baştan
            e = self.kayit[key] = {"parmak": parmak, "denemeler": []}
        dn = e["denemeler"]
        if dn and dn[-1].get("cevap_sha") == cs and not dn[-1].get("dosya") and not e.get("elle"):
            dn.pop()                                    # aynı cevap kenara alınmadan yeniden işlendi: bir kez say
        dn.append({"cevap_sha": cs, "neden": kod, "hatalar": list(hatalar)[:8], "model": model,
                   "zaman": _now(), "dosya": None})
        self.kirli = True
        n = len(dn)
        ayni = sum(1 for x in dn if x["neden"] == kod)
        if ayni >= AYNI_NEDEN_SINIRI or n >= DENEME_SINIRI:
            e["elle"] = {"neden": kod, "hatalar": list(hatalar)[:8], "deneme": n, "parmak": parmak,
                         "cevap_sha": cs, "model": model, "zaman": _now(), **(ek or {})}
            return {"sonuc": ELLE, "neden": kod, "deneme": n}
        e.pop("elle", None)
        if kenara and outp.exists():
            name = f"{outp.name}.red{n}.eski"
            outp.replace(outp.parent / name)
            dn[-1]["dosya"] = name
            self.cekilen.add(key)
            return {"sonuc": "yeniden", "neden": kod, "deneme": n, "dosya": name}
        return {"sonuc": "yeniden", "neden": kod, "deneme": n}

    def kenara_al(self, key: str, outp: Path) -> str | None:
        """Aşamanın kendi sayacıyla (ör. yazım kod denetimi) reddettiği cevap yalnız kenara alınır."""
        if not outp.exists():
            return None
        i = 1
        while (outp.parent / f"{outp.name}.red{i}.eski").exists():
            i += 1
        name = f"{outp.name}.red{i}.eski"
        outp.replace(outp.parent / name)
        self.cekilen.add(key)
        return name

    def geri_koy(self, key: str, outp: Path, neden: str = "supheli") -> bool:
        """`--kabul-supheli`: son deneme `neden` ile kenara alındıysa o cevap geri konur (uygulanır)."""
        s = self.son(key)
        if not s or s.get("neden") != neden or not s.get("dosya") or outp.exists():
            return False
        src = outp.parent / s["dosya"]
        if not src.is_file():
            return False
        src.replace(outp)
        s["dosya"] = None
        self.kirli = True
        return True

    def basarili(self, key: str) -> int:
        """Cevap kabul edildi: öğenin kaydı kapanır. Döner: önceki ret sayısı."""
        e = self.kayit.pop(key, None)
        if e is None:
            return 0
        self.kirli = True
        return len(e.get("denemeler") or [])

    def unut(self, keys) -> None:
        for k in list(keys):
            if self.kayit.pop(k, None) is not None:
                self.kirli = True

    def kaydet(self) -> None:
        if self.cekilen:
            # kenara alınan cevap parça bildirimindeki "önceden var olan cevap" değildir: geri konmasın
            from bidr.pipeline.paralel import cevap_cekildi
            cevap_cekildi(self.root, self.dizin, self.cekilen)
            self.cekilen = set()
        if not self.kirli:
            return
        if not self.kayit:
            self._hepsi.pop(self.dizin, None)
        p = self.root / DOSYA
        if self._hepsi:
            tmp = p.with_name(p.name + ".tmp")
            tmp.write_text(json.dumps({k: dict(sorted(v.items())) for k, v in sorted(self._hepsi.items())},
                                      ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(p)
        elif p.exists():
            p.unlink()
        if self._eski is not None:
            self._eski.unlink(missing_ok=True)
            self._eski = None
        self.kirli = False


def elle_kayitlari(ws_root: Path, dizin: str) -> dict[str, dict]:
    """Salt okunur: klasörün elle bakılmalı öğeleri (aşama denetimleri için)."""
    return Denemeler(ws_root, dizin).elle_hepsi()


NEDENLER = {"sema": "şemaya uymuyor", "yapi": "sayfa yapısı", "supheli": "şüpheli (OCR'la örtüşme düşük)",
            "denetim": "kod denetimi", "ad": "ad kurala uymuyor", "karar": "karar listesi eksik/fazla"}


def neden_metni(kod: str | None) -> str:
    return NEDENLER.get(kod or "", kod or "?")


def kenar_notu(y: dict | None, key: str, klasor: bool = False) -> str:
    """GECERSIZ.md satırına: cevap kenara alındı, paket yeniden cevap bekliyor."""
    if not y or not y.get("dosya"):
        return ""
    yol = f"{key}/{y['dosya']}" if klasor else y["dosya"]
    return (f" (deneme {y['deneme']}; cevap `{yol}` olarak kenara alındı: paket yeniden cevap bekliyor, yeni "
            f"`{key}.out.json` yaz)")


def onceki_red_satirlari(den: Denemeler, bekleyen, yazilan: set[str], fmt, klasor: bool = False) -> list[str]:
    """Önceki apply'larda reddedilip hâlâ yeni cevap bekleyenlerin gerekçesi (ajana kaybolmasın).
    `fmt(key)`: GECERSIZ.md satırının başı (ör. "`A.1.1.json`")."""
    out = []
    for k in sorted(bekleyen):
        s = den.kenarda(k)
        if s and k not in yazilan:
            tur = "şüpheli" if s.get("neden") == "supheli" else f"geçersiz cevap ({neden_metni(s.get('neden'))})"
            yol = f"{k}/{s['dosya']}" if klasor else s["dosya"]
            out.append(f"- {fmt(k)} — {tur} (önceki deneme, `{yol}`): "
                       + "; ".join(s.get("hatalar") or []) + f". Yeni `{k}.out.json` bekleniyor.")
    return out


def elle_raporu(d: Path, den: Denemeler, asama: str, anlam: str, nasil: str = "") -> None:
    """Aşama klasörüne ELLE-BAKILMALI.md (öğe yoksa siler)."""
    if not d.exists():
        return
    p = d / ELLE_MD
    el = den.elle_hepsi()
    if not el:
        if p.exists():
            p.unlink()
        return
    rep = [f"# Elle bakılmalı ({asama})", "",
           f"Model cevabı aynı nedenle {AYNI_NEDEN_SINIRI} kez (ya da {DENEME_SINIRI} denemede) reddedildi; yeniden "
           f"istenmez ve aşama bunları beklemez. {anlam}" + (f" {nasil}" if nasil else ""), ""]
    for k, r in el.items():
        rep.append(f"- `{k}` — {neden_metni(r.get('neden'))}, {r.get('deneme')} deneme: "
                   + "; ".join(r.get("hatalar") or []))
    p.write_text("\n".join(rep) + "\n", encoding="utf-8")


def dogrula(validate, task: str, raw):
    """`validate_output` + enum normalleştirme notları: (çıktı | None, hatalar, notlar). Testlerin sahte
    doğrulayıcısı `notlar` almıyorsa notsuz çağrılır."""
    import inspect
    notlar: list[dict] = []
    try:
        ok = "notlar" in inspect.signature(validate).parameters
    except (TypeError, ValueError):
        ok = False
    out, errs = validate(task, raw, notlar=notlar) if ok else validate(task, raw)
    return out, errs, notlar


# -- bölümün kararı (kesin) ------------------------------------------------------------------------------
#
# Elle bakılmalı her öğe review.xlsx İnceleme sayfasında (panelde İncelemeniz) bölümün önüne düşer; karar `bidr audit apply` ya da `bidr elle karar` ile
# `work/<aşama>/elle-kararlar.jsonl`'e yazılır ve KESİNDİR: belgenin içeriği (envanter sha256'sı; ölçüt/alan
# paketlerinde paketin girdisi) değişmedikçe öğe bir daha doğrulanmaz, yeniden sorulmaz, aşamayı bekletmez.
# Karar verilmeyen öğe de raporu durdurmaz: varsayılan "taramadaki metinle kal / betimleme yok / karar yok".

KARAR_DOSYA = "elle-kararlar.jsonl"
KABUL, VARSAYILAN, ATLA = "kabul", "varsayilan", "atla"
KARAR_SECENEKLERI = (KABUL, VARSAYILAN, ATLA)

# aşama → (paket klasörü, öğe türü). write/verify/yön doğrulaması burada değil: onların bölüm kararı panelin
# "Rapor doğrulaması" ekranındadır (bidr write|verify|yonler karar).
ASAMALAR = {
    "transcribe": ("work/transcribe", "belge"),
    "describe": ("work/describe", "belge"),
    "karar_kaba": ("work/coarse", "belge"),
    "karar_ince": ("work/fine", "belge"),
    "name": ("work/name", "belge"),
    "ikinci_arama": ("work/ikinci_arama", "belge"),
    "yonler": ("work/yonler", "alan"),
    "kor_denetim": ("work/kor_denetim", "paket"),
}
SADE_NEDEN = {
    ("transcribe", "supheli"): "Model görseldeki yazıyı taramayla uyuşmayan biçimde okudu",
    ("describe", "supheli"): "Modelin görselde okuduğu yazılar taramayla uyuşmuyor",
    ("transcribe", "sema"): "Modelin okuması beklenen biçimde değildi",
    ("transcribe", "yapi"): "Modelin okumasında sayfa sayısı ya da sırası tutmadı",
    ("describe", "sema"): "Modelin betimlemesi beklenen biçimde değildi",
    ("describe", "denetim"): "Modelin betimlemesi kurallara uymadı (kişi betimlemesi ya da görselde olmayan tarih)",
}
SECENEK_METNI = {
    "transcribe": {KABUL: "Modelin okuduğu doğru, kabul et", VARSAYILAN: "Taramadaki metinle kalsın",
                   ATLA: "Bu belgeyi bu adımda atla"},
    "describe": {KABUL: "Modelin betimlemesi doğru, kabul et", VARSAYILAN: "Betimleme olmasın, taramadaki metinle kalsın",
                 ATLA: "Bu belgeyi bu adımda atla"},
}
# review.xlsx İnceleme sayfasına giren aşamalar (incelemeden önce biten belge aşamaları; ötekiler uyarıda kalır)
INCELEME_ASAMALARI = ("transcribe", "describe", "karar_kaba", "karar_ince", "name", "ikinci_arama")
VARSAYILAN_METIN = {VARSAYILAN: "Model kararı olmadan kalsın", ATLA: "Bu belgeyi bu adımda atla"}


def _inv_sha(root: Path) -> dict[str, str]:
    import csv
    p = root / "inventory.csv"
    if not p.exists():
        return {}
    with open(p, encoding="utf-8", newline="") as f:
        return {r["doc_id"]: r.get("sha256") or "" for r in csv.DictReader(f) if r.get("doc_id")}


def belge_sha(root: Path, asama: str, key: str, parmak=None, inv: dict | None = None) -> str:
    """Kararın bağlı olduğu içerik: belge aşamalarında envanter sha256'sı, ötekilerde paket girdisi."""
    if ASAMALAR.get(asama, ("", "belge"))[1] == "belge":
        return (inv if inv is not None else _inv_sha(root)).get(key, "")
    return str(parmak or "")


def kararlar(root: Path, dizin: str) -> dict[str, dict]:
    p = Path(root) / dizin / KARAR_DOSYA
    out: dict[str, dict] = {}
    if not p.exists():
        return out
    for ln in p.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(ln)
        except ValueError:
            continue
        if isinstance(r, dict) and r.get("anahtar") and r.get("karar") in KARAR_SECENEKLERI:
            out[r["anahtar"]] = r
    return out


class Kesin:
    """Bir aşamanın geçerli (içeriği değişmemiş) bölüm kararları: `kesin.get(key)`."""

    def __init__(self, root: Path, asama: str, parmaklar: dict | None = None):
        self.root, self.asama = Path(root), asama
        self.dizin = ASAMALAR[asama][0]
        self._k = kararlar(self.root, self.dizin)
        self._inv = _inv_sha(self.root) if self._k and ASAMALAR[asama][1] == "belge" else {}
        self._parmak = parmaklar or {}

    def get(self, key: str, parmak=None) -> dict | None:
        r = self._k.get(key)
        if not r:
            return None
        p = parmak if parmak is not None else self._parmak.get(key)
        cur = belge_sha(self.root, self.asama, key, p, self._inv)
        return r if r.get("belge_sha") == cur and cur else None

    def keys(self) -> set[str]:
        return {k for k in self._k if self.get(k)}

    def __contains__(self, key: str) -> bool:
        return self.get(key) is not None


def _cevap_ozeti(raw: str, n: int = 4000) -> str:
    """Modelin son cevabından insanın okuyacağı metin (okunan metin, betimleme, ad …)."""
    try:
        j = json.loads(raw)
    except ValueError:
        return raw[:n]
    parts: list[str] = []
    if isinstance(j, dict):
        for s in j.get("sayfalar") or []:
            if isinstance(s, dict) and s.get("metin"):
                parts.append(str(s["metin"]))
        for g in j.get("gorseller") or []:
            if not isinstance(g, dict):
                continue
            parts.append(str(g.get("betimleme") or ""))
            parts += [f"Görünen yazı: \"{y.get('metin')}\"" for y in g.get("gorunen_yazilar") or [] if isinstance(y, dict)]
        for k in ("kanit_adi", "gerekce"):
            if isinstance(j.get(k), str) and j[k]:
                parts.append(j[k])
    return ("\n".join(x for x in parts if x) or raw)[:n]


def _elle_ogeleri(root: Path) -> list[tuple[str, str, dict]]:
    """(aşama, anahtar, elle kaydı): ortak kayıttan ve transcribe/describe günlüklerinden (4ee6d1c'nin kaydı)."""
    out: dict[tuple[str, str], dict] = {}
    for asama, (dizin, _) in ASAMALAR.items():
        for k, e in elle_kayitlari(root, dizin).items():
            out[(asama, k)] = e
    from bidr.common import read_jsonl
    for asama, log in (("transcribe", "transcribe.jsonl"), ("describe", "describe.jsonl")):
        p = root / log
        for r in (read_jsonl(p) if p.exists() else []):
            if r.get("durum") == ELLE and r.get("doc_id"):
                e = out.setdefault((asama, r["doc_id"]), {})
                for f in ("neden", "hatalar", "deneme", "cikti_sha", "zaman", "tur"):
                    if r.get(f) is not None:
                        e.setdefault(f, r[f])
    return [(a, k, e) for (a, k), e in sorted(out.items())]


def liste(ws_root: Path) -> list[dict]:
    """Elle bakılmalı öğeler (makine okunur; review.xlsx İnceleme satırları): aşama, anahtar, neden (kod + sade),
    modelin son cevabının özeti, varsa belgenin şimdiki (OCR) metni, seçenekler, verilmiş karar."""
    root = Path(ws_root)
    docs = {}
    dp = root / "documents.jsonl"
    if dp.exists():
        from bidr.common import read_jsonl
        docs = {r["doc_id"]: r for r in read_jsonl(dp) if r.get("doc_id")}
    inv_rows = {}
    if (root / "inventory.csv").exists():
        import csv
        with open(root / "inventory.csv", encoding="utf-8", newline="") as f:
            inv_rows = {r["doc_id"]: r for r in csv.DictReader(f) if r.get("doc_id")}
    inv = {k: r.get("sha256") or "" for k, r in inv_rows.items()}
    out = []
    kes = {a: Kesin(root, a) for a in ASAMALAR}
    for asama, k, e in _elle_ogeleri(root):
        dizin, tur = ASAMALAR[asama]
        d = root / dizin
        outp = (d / k / f"{k}.out.json") if (d / k).is_dir() else (d / f"{k}.out.json")
        raw = outp.read_text(encoding="utf-8", errors="replace") if outp.exists() else ""
        neden = e.get("neden")
        kabul = asama in ("transcribe", "describe") and neden == "supheli" and bool(raw)
        sec = SECENEK_METNI.get(asama, VARSAYILAN_METIN)
        metin = ""
        if tur == "belge":
            tp = root / "text_ocr" / f"{k}.txt"
            tp = tp if tp.exists() else root / "text" / f"{k}.txt"
            metin = tp.read_text(encoding="utf-8", errors="replace")[:4000] if tp.exists() else ""
        rel = (inv_rows.get(k) or {}).get("rel_path") or ""
        k_rec = kes[asama].get(k, e.get("parmak"))
        out.append({
            "asama": asama, "anahtar": k, "tur": tur,
            "belge": rel.replace("\\", "/").rsplit("/", 1)[-1] if rel else ((docs.get(k) or {}).get("calisma_adi") or k),
            "kaynak_dosya": rel, "neden": neden, "deneme": e.get("deneme"),
            "neden_metni": SADE_NEDEN.get((asama, neden)) or f"Modelin cevabı iki denemede de kabul edilmedi "
                                                               f"({neden_metni(neden)})",
            "hatalar": list(e.get("hatalar") or [])[:5], "model_cevabi": _cevap_ozeti(raw) if raw else "",
            "belge_metni": metin, "belge_sha": belge_sha(root, asama, k, e.get("parmak"), inv),
            "secenekler": [{"karar": x, "metin": sec[x]} for x in KARAR_SECENEKLERI if x != KABUL or kabul],
            "varsayilan": VARSAYILAN, "karar": k_rec})
    return out


def karar_ver(ws_root: Path, asama: str, key: str, karar: str, *, kim: str = "", notu: str = "") -> dict:
    """Bölümün kararı (kesin): kaydı yazar; `kabul` modelin son cevabını olduğu gibi uygular (transcribe/describe:
    `--kabul-supheli` eşdeğeri). Döner: karar kaydı."""
    root = Path(ws_root)
    if asama not in ASAMALAR:
        raise ValueError(f"aşama '{asama}' elle karar almaz ({', '.join(ASAMALAR)})")
    if karar not in KARAR_SECENEKLERI:
        raise ValueError(f"karar '{karar}' geçersiz ({' | '.join(KARAR_SECENEKLERI)})")
    item = next((x for x in liste(root) if x["asama"] == asama and x["anahtar"] == key), None)
    if item is None:
        raise ValueError(f"{asama} {key}: elle bakılmalı bir öğe değil")
    if karar not in {s["karar"] for s in item["secenekler"]}:
        raise ValueError(f"{asama} {key}: '{karar}' bu öğe için seçenek değil "
                         f"({', '.join(s['karar'] for s in item['secenekler'])})")
    if karar == KABUL:
        if asama == "transcribe":
            from bidr.transcribe import run as T
            st = T.apply(root, model="insan:kabul", accept_suspicious=True, only=[key])
        else:
            from bidr.describe import run as D
            st = D.apply(root, model="insan:kabul", accept_suspicious=True, only=[key])
        if not st.get("islenen") and not st.get("metin_ayni") and not st.get("degismedi"):
            raise ValueError(f"{asama} {key}: modelin son cevabı uygulanamadı")
    rec = {"asama": asama, "anahtar": key, "karar": karar, "belge_sha": item["belge_sha"], "neden": item["neden"],
           "kim": kim, "not": notu, "zaman": _now()}
    d = root / ASAMALAR[asama][0]
    d.mkdir(parents=True, exist_ok=True)
    with open(d / KARAR_DOSYA, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec
