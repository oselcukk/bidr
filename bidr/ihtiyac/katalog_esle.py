"""Kurum belge kataloğu → alt ölçüt eşlemesi (`bidr kurum-katalog prepare|apply`).

1. Kural ön elemesi (`bidr/data/kurum_katalog_kurallar.yaml`): ilgisiz alanlar (personel özlük, mali,
   satın alma, idari iç işler…) elenir; kalan öğeler ad/kod desenleriyle aday ölçütlere eşlenir.
2. Kurala uyan öğeler ve elenmeyen bütün yönetmelik/yönerge/usul-esaslar model iş paketlerine (`work/kurum-katalog/kk-NNN.json`, görev
   `kurum_katalog_esle`) konur; ajan `kk-NNN.out.json` yazar, `apply` denetleyip eşlemeye işler.
   Model cevabı kural önerisini aşar (ilgisiz de diyebilir, ölçüt ekleyip çıkarabilir). Kurala
   uymayan form/iş akışı paketlenmez (ilgisiz kalır): katalogun çoğu birimlerin iç işleyişidir.
3. Sonuç `kurum-katalog-esleme.json`: her öğe için ad, kod, tür, bağlantı, ilgili mi, en çok
   `en_cok` ölçüt ve kısa gerekçe. Öğe başına önbellek anahtarı (tür, kod, ad, birim, bölüm):
   katalog yeniden çekildiğinde değişmeyen öğenin model eşlemesi korunur, yeniden paketlenmez.

Paket yoksa ya da cevaplanmadıysa kural eşlemesi kullanılır (`kaynak: kural`).
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

import yaml

from .katalog import TUR_AD
from .tablolar import norm

DATA = Path(__file__).resolve().parents[1] / "data"
KURALLAR_FILE = DATA / "kurum_katalog_kurallar.yaml"
FILE = "kurum-katalog-esleme.json"
TASK = "kurum_katalog_esle"
WORK = Path("work") / "kurum-katalog"
PAKET_BOYU = 60
PKG = r"kk-\d{3}"
GEREKCE_N = 160
MEVZUAT = ("yonetmelik", "yonerge", "usul_esas")   # kurala uymasa da modele sorulur (az sayıda)


class Kurallar:
    def __init__(self, path: Path | str | None = None):
        p = Path(path or KURALLAR_FILE)
        txt = p.read_text(encoding="utf-8")
        raw = yaml.safe_load(txt) or {}
        self.sha = hashlib.sha256(txt.encode("utf-8")).hexdigest()[:16]
        self.en_cok = int(raw.get("en_cok") or 3)

        def rx(xs):
            return [re.compile(str(x)) for x in xs or []]
        self.ele_bolum, self.ele_birim, self.ele_ad = rx(raw.get("ele_bolum")), rx(raw.get("ele_birim")), rx(
            raw.get("ele_ad"))
        self.tut = rx(raw.get("tut"))
        self.esle = [(re.compile(str(r["desen"])), [str(x) for x in r.get("olcutler") or []])
                     for r in raw.get("esle") or []]

    def uygula(self, it: dict) -> dict:
        """{"ilgili", "olcutler", "gerekce"} (yalnız ad/kod/birim/bölüm; içerik yok)."""
        ad = norm(f"{it.get('ad') or ''} {it.get('kod') or ''}")
        tut = any(p.search(ad) for p in self.tut)
        for alan, ps, s in (("bölüm", self.ele_bolum, norm(it.get("bolum"))),
                            ("birim", self.ele_birim, norm(it.get("birim"))), ("ad", self.ele_ad, ad)):
            m = next((p.search(s) for p in ps if s and p.search(s)), None)
            if m and not tut:
                return {"ilgili": False, "olcutler": [], "gerekce": f"ilgisiz alan ({alan}: «{m.group(0)}»)",
                        "elendi": True}
        os_: list[str] = []
        neden: list[str] = []
        for p, cs in self.esle:
            m = p.search(ad)
            if m:
                yeni = [c for c in cs if c not in os_]
                if yeni:
                    os_ += yeni
                    neden.append(f"«{m.group(0)}» → {', '.join(yeni)}")
        os_ = os_[:self.en_cok]
        if not os_:
            return {"ilgili": False, "olcutler": [], "gerekce": "adında ölçütle ilgili ifade yok", "elendi": False}
        return {"ilgili": True, "olcutler": os_, "gerekce": "ad: " + "; ".join(neden)[:GEREKCE_N], "elendi": False}


def _olcut_listesi(cs) -> list[str]:
    out = []
    for c in cs:
        if c.id.count(".") != 2:
            continue
        ys = [s.text.replace("*", "").strip() for s in c.slots if not s.footnote][:3]
        ys = [y if len(y) <= 90 else y[:90].rsplit(" ", 1)[0] + "…" for y in ys]
        out.append(f"{c.id} — {c.title.replace('*', '').strip()}: " + "; ".join(ys))
    return out


def _alanlar(it: dict) -> dict:
    keys = ("id", "anahtar", "ad", "kod", "tur", "baglanti", "en_baglanti", "birim", "bolum", "revizyon",
            "tarihler", "sayfa")
    zorunlu = ("id", "anahtar", "ad", "kod", "tur", "baglanti")
    return {k: it.get(k) or "" if k in zorunlu else it.get(k) for k in keys
            if k in zorunlu or it.get(k) not in (None, "", {})}


def esleme_oku(path: Path) -> dict | None:
    p = Path(path)
    if p.is_dir():
        p = p / FILE
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def _yaz(path: Path, es: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(es, ensure_ascii=False, indent=1), encoding="utf-8")


def prepare(katalog: dict, out_dir: Path, *, cs=None, kurallar: Kurallar | None = None, yeniden: bool = False,
            paket_boyu: int = PAKET_BOYU) -> dict:
    """Kural eşlemesini yazar, model gerektiren öğeleri paketler. Değişmeyen öğenin model eşlemesi korunur."""
    from bidr.criteria.loader import load_criteria
    from bidr.llm.runner import render_task
    from bidr.write.packages import pkg_paths, write_pkg, write_readme
    cs = cs or load_criteria()
    kur = kurallar or Kurallar()
    out_dir = Path(out_dir)
    if (out_dir / FILE).exists() and any((out_dir / WORK).glob("kk-*.out.json")):
        apply(out_dir, cs=cs, model=None)   # uygulanmamış cevaplar yeniden paketlemede kaybolmasın
    eski = esleme_oku(out_dir / FILE) or {}
    onceki = {o["id"]: o for o in eski.get("ogeler") or []}
    guncel = (not yeniden and eski.get("katalog_sha") == katalog.get("sha")
              and eski.get("kurallar_sha") == kur.sha)
    ogeler, bekleyen = [], []
    for it in katalog.get("ogeler") or []:
        r = kur.uygula(it)
        o = {**_alanlar(it), "ilgili": r["ilgili"], "olcutler": r["olcutler"], "gerekce": r["gerekce"],
             "kaynak": "kural", "kural_olcutler": r["olcutler"], "elendi": r["elendi"]}
        p = onceki.get(it["id"])
        if p and p.get("kaynak") == "model" and p.get("anahtar") == it.get("anahtar") and not yeniden:
            o.update({k: p[k] for k in ("ilgili", "olcutler", "gerekce", "kaynak", "model") if k in p})
        elif not r["elendi"] and (r["ilgili"] or it.get("tur") in MEVZUAT):
            bekleyen.append(o)
        ogeler.append(o)
    d = out_dir / WORK
    yeni = 0
    olc = _olcut_listesi(cs)
    for p in pkg_paths(d, PKG) if d.exists() else []:
        if not (d / f"{p.stem}.out.json").exists():
            p.unlink()                                 # cevapsız eski paket: yeniden kurulur
    for i in range(0, len(bekleyen), paket_boyu):
        grup = bekleyen[i:i + paket_boyu]
        girdi = {"olcutler": olc, "en_cok": kur.en_cok,
                 "ogeler": [{"id": o["id"], "ad": o["ad"], "kod": o.get("kod") or "",
                             "tur": TUR_AD.get(o["tur"], o["tur"]), "birim": o.get("birim") or "",
                             "bolum": o.get("bolum") or "", "kural_onerisi": o["kural_olcutler"]} for o in grup]}
        rendered = render_task(TASK, girdi)
        key = f"kk-{i // paket_boyu + 1:03d}"
        yeni += write_pkg(d, key, rendered, {"ids": [o["id"] for o in grup],
                                             "anahtarlar": {o["id"]: o["anahtar"] for o in grup}})
    n_bek = 0
    if bekleyen:
        n_bek = write_readme(d, task=TASK, version=render_task(TASK, {"olcutler": [], "en_cok": 3, "ogeler": []})[
            "version"], cmd="kurum-katalog", pattern=PKG, key="paket",
            rule="`ogeler` listesindeki her öğe için cevapta bir kayıt ver: ilgili alt ölçütler (en çok "
                 f"{kur.en_cok}; ilgisizse boş liste) ve kısa gerekçe. Yalnız belge adına dayan; abartma.")
    es = {"surum": 1, "uretim": datetime.now().isoformat(timespec="seconds"), "kurum": katalog.get("kurum", ""),
          "katalog_sha": katalog.get("sha"), "kurallar_sha": kur.sha, "ogeler": ogeler}
    _yaz(out_dir / FILE, es)
    return {"dosya": out_dir / FILE, "oge": len(ogeler), "elenen": sum(o["elendi"] for o in ogeler),
            "paketlenen": len(bekleyen), "paket": -(-len(bekleyen) // paket_boyu) if bekleyen else 0,
            "yeni_paket": yeni, "bekleyen_paket": n_bek, "klasor": d, "guncel": guncel,
            "model_korunan": sum(1 for o in ogeler if o["kaynak"] == "model")}


def apply(out_dir: Path, *, model: str | None = "ajan:belirtilmemis", cs=None) -> dict:  # noqa: C901
    """`kk-NNN.out.json` cevaplarını denetler ve eşlemeye işler."""
    from bidr.criteria.loader import load_criteria
    from bidr.llm.runner import validate_output
    from bidr.write.packages import pkg_paths, write_invalid
    cs = cs or load_criteria()
    gecerli = {c.id for c in cs if c.id.count(".") == 2}
    out_dir = Path(out_dir)
    es = esleme_oku(out_dir / FILE)
    if es is None:
        raise FileNotFoundError(f"{out_dir / FILE} yok: önce `bidr kurum-katalog prepare`")
    en_cok = Kurallar().en_cok
    by = {o["id"]: o for o in es["ogeler"]}
    d = out_dir / WORK
    gecersiz: dict[str, list[str]] = {}
    islenen, bekleyen = 0, []
    for p in pkg_paths(d, PKG) if d.exists() else []:
        out = d / f"{p.stem}.out.json"
        if not out.exists():
            bekleyen.append(p.stem)
            continue
        pkg = json.loads(p.read_text(encoding="utf-8"))
        val, errs = validate_output(TASK, out.read_text(encoding="utf-8"))
        ids = pkg["meta"]["ids"]
        if val is not None:
            gelen = {x["id"]: x for x in val["ogeler"]}
            if set(gelen) - set(ids):
                errs.append("pakette olmayan id: " + ", ".join(sorted(set(gelen) - set(ids))[:5]))
            if set(ids) - set(gelen):
                errs.append("cevapsız id: " + ", ".join(sorted(set(ids) - set(gelen))[:5]))
            for x in gelen.values():
                bad = [c for c in x["olcutler"] if c not in gecerli]
                if bad:
                    errs.append(f"{x['id']}: geçersiz ölçüt {', '.join(bad)}")
                if len(x["olcutler"]) > en_cok:
                    errs.append(f"{x['id']}: en çok {en_cok} ölçüt")
        if errs:
            gecersiz[p.stem] = errs
            continue
        for x in val["ogeler"]:
            o = by.get(x["id"])
            if o is None or o.get("anahtar") != pkg["meta"]["anahtarlar"].get(x["id"]):
                continue                                   # öğe sonradan değişmiş: eski cevap uygulanmaz
            os_ = list(dict.fromkeys(x["olcutler"]))
            o.update({"ilgili": bool(os_), "olcutler": os_, "gerekce": " ".join(x["gerekce"].split())[:GEREKCE_N],
                      "kaynak": "model",
                      "model": model or o.get("model") or "ajan:belirtilmemis"})
            islenen += 1
    write_invalid(d, TASK, gecersiz) if d.exists() else None
    es["uretim"] = datetime.now().isoformat(timespec="seconds")
    _yaz(out_dir / FILE, es)
    return {"dosya": out_dir / FILE, "islenen": islenen, "bekleyen": bekleyen, "gecersiz": gecersiz,
            "ilgili": sum(1 for o in es["ogeler"] if o["ilgili"])}


def olcut_belgeleri(es: dict | None) -> dict[str, list[dict]]:
    """Ölçüt → ilgili kurum belgeleri (tür, kod sırasıyla)."""
    out: dict[str, list[dict]] = {}
    sira = {t: i for i, t in enumerate(("yonetmelik", "yonerge", "usul_esas", "is_akisi", "anket", "form",
                                        "talimat"))}
    for o in sorted((es or {}).get("ogeler") or [], key=lambda o: (sira.get(o.get("tur"), 9), o.get("kod") or "",
                                                                      o.get("ad") or "")):
        if o.get("ilgili"):
            for c in o.get("olcutler") or []:
                out.setdefault(c, []).append(o)
    return out


def madde_metni(o: dict) -> str:
    """Sade listedeki madde: `Belge adı (kod)` (bağlantı katalog dosyasında kalır, listeye yazılmaz)."""
    ad = o.get("ad") or ""
    kod = o.get("kod") or ""
    return f"{ad} ({kod})" if kod and kod not in ad else ad
