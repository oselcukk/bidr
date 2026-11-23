"""Model aşamalarını paralel ajanlara bölme: `bidr parcala` ve `bidr parca-denetle`.

Bölünebilir aşamanın (pipeline.yaml `paralel.bolunebilir: true`) cevapsız paketleri N AYRIK parça
listesine bölünür; her ajan yalnız kendi listesindeki paketlere cevap (`.out.json`) yazar, apply'ı tek
seferde (hepsi bitince) çalışan yazar. Parça ajanının talimatı tek ajanınkiyle aynıdır (paketin `istem`i);
yalnız paket listesi farklıdır. Belgeler arası bağlantılar (PUKÖ zinciri, faaliyet, OD) modelsiz
aşamalarda (faaliyet, audit) bütün kararlardan kurulur: kimin hangi paketi yazdığı sonucu değiştirmez.

Klasör düzeni (`work/<aşama>/_parca/`; `_` ile başlayan ad hiçbir aşamada paket sayılmaz):
  <k>.txt            k. parçanın paket listesi (satır başına WS'ye göreli paket yolu)
  parcalar.json      bildirim: aşama, parçalar, paket izi, bölmeden önce var olan liste dışı cevapların sha'sı
  yedek/             liste dışı var olan cevapların kopyası (ezilirse geri konur)
  reddedilen/        denetimin reddettiği (liste dışı yazılmış ya da ezilmiş) cevaplar

Ezme koruması: `parca-denetle` (ve her apply'dan önce `apply_oncesi`) bildirime bakar. Bölmeden sonra
listelerin hiçbirinde olmayan bir pakete yazılan cevap ya da önceden var olan liste dışı bir cevabın
değişmesi/silinmesi ihlaldir: yazılan dosya `reddedilen/`'e taşınır, varsa eski cevap geri konur. Paketler
bölmeden sonra değiştiyse (yeniden prepare) bildirim eskidir ve yok sayılır (tek ajanlı iş engellenmez).
Hangi parçanın hangi dosyayı yazdığını dosya sistemi söylemez; bunu panel işleyicisi çağrı başına
(stream-json araç kayıtlarıyla) ayrıca denetler.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
from datetime import datetime
from pathlib import Path

from bidr.common import Workspace

PARCA = "_parca"
BILDIRIM = "parcalar.json"
VARSAYILAN = {"taban": 2, "esik": 20, "adim": 20, "azami": 20}
TAVAN = 20                      # kesin üst sınır (ayar bunu aşamaz)
ENV_AZAMI = "BIDR_PARALEL_AZAMI"


class ParcaHatasi(RuntimeError):
    pass


# -- ayarlar -----------------------------------------------------------------------------------------

def bilgi(sid: str) -> dict | None:
    """pipeline.yaml `paralel` alanı (yoksa None: aşama model aşaması değil)."""
    from .state import stage
    return stage(sid).get("paralel")


def ayarlar(ws_root: Path, *, azami: int | None = None, esik: int | None = None,
            adim: int | None = None, taban: int | None = None) -> dict:
    """Taban/eşik/adım/tavan: komut bayrağı > config.yaml `rapor.paralel_{taban,esik,adim,azami}` > varsayılan.
    Tavan ayrıca `BIDR_PARALEL_AZAMI` ortam değişkeniyle düşürülebilir (kota); hiçbiri 20'yi (TAVAN) aşamaz."""
    from bidr.write.sources import rapor_section
    r = rapor_section(ws_root)

    def _int(v, ad):
        if v is None or v == "":
            return None
        try:
            n = int(v)
        except (TypeError, ValueError) as e:
            raise ParcaHatasi(f"{ad} tamsayı olmalı: {v!r}") from e
        if n < 1:
            raise ParcaHatasi(f"{ad} en az 1 olmalı: {n}")
        return n

    out = {}
    for k in ("taban", "esik", "adim"):
        out[k] = _int({"taban": taban, "esik": esik, "adim": adim}[k], k) or _int(r.get(f"paralel_{k}"), f"rapor.paralel_{k}") \
            or VARSAYILAN[k]
    tavanlar = [TAVAN, _int(azami, "azami"), _int(r.get("paralel_azami"), "rapor.paralel_azami"),
                _int(os.environ.get(ENV_AZAMI), ENV_AZAMI)]
    out["azami"] = min(t for t in tavanlar if t)
    return out


def parca_sayisi(n_paket: int, *, taban: int = VARSAYILAN["taban"], esik: int = VARSAYILAN["esik"],
                 adim: int = VARSAYILAN["adim"], azami: int = VARSAYILAN["azami"]) -> int:
    """Paket sayısına göre artan ajan sayısı: ≤ esik → `taban`; sonra her `adim` pakette +1; en çok
    `azami`, TAVAN ve paket sayısı. 0 paket → 0. Varsayılanla (2/20/20/20) bu
    min(20, n, 2 + (n-1)//20) demektir: 1 → 1, 2–20 → 2, 21–40 → 3, 41–60 → 4, …, 361+ → 20."""
    if n_paket <= 0:
        return 0
    n = taban if n_paket <= esik else taban + math.ceil((n_paket - esik) / adim)
    return max(1, min(azami, TAVAN, n_paket, n))


# -- paketler ------------------------------------------------------------------------------------------

def _dizin(ws: Workspace, info: dict) -> Path:
    return ws.root / info["dizin"]


def _paket_yolu(d: Path, info: dict, k: str) -> Path:
    return d / k / f"{k}.json" if info.get("duzen") == "klasor" else d / f"{k}.json"


def cikti_yolu(d: Path, info: dict, k: str) -> Path:
    return d / k / f"{k}.out.json" if info.get("duzen") == "klasor" else d / f"{k}.out.json"


def _anahtar_uyar(info: dict, k: str) -> bool:
    if k.startswith("_") or k in ("README", "YENIDEN"):
        return False
    pat = info.get("anahtar")
    return bool(re.fullmatch(pat, k)) if pat else True


def paketler(ws: Workspace, info: dict) -> dict[str, Path]:
    """Aşama klasöründeki iş paketleri: anahtar → paket dosyası (cevaplar ve yardımcı dosyalar hariç)."""
    d = _dizin(ws, info)
    if not d.exists():
        return {}
    out = {}
    if info.get("duzen") == "klasor":
        for p in d.glob("*/*.json"):
            if p.stem == p.parent.name and _anahtar_uyar(info, p.stem):
                out[p.stem] = p
    else:
        for p in d.glob("*.json"):
            if p.name.endswith(".out.json") or not _anahtar_uyar(info, p.stem):
                continue
            try:
                pkg = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(pkg, dict) and "istem" in pkg:
                out[p.stem] = p
    return dict(sorted(out.items()))


def cevaplar(ws: Workspace, info: dict) -> dict[str, Path]:
    """Aşama klasöründeki bütün cevaplar (`.out.json`): anahtar → dosya (paketi olmasa da)."""
    d = _dizin(ws, info)
    if not d.exists():
        return {}
    pat = "*/*.out.json" if info.get("duzen") == "klasor" else "*.out.json"
    out = {}
    for p in d.glob(pat):
        k = p.name[:-len(".out.json")]
        if PARCA in p.parts or (info.get("duzen") == "klasor" and p.parent.name != k):
            continue
        out[k] = p
    return dict(sorted(out.items()))


def agirlik(p: Path, info: dict) -> int:
    """Kaba iş ölçüsü: paketin (klasör düzeninde klasörün: sayfa görüntüleri) bayt boyutu."""
    try:
        if info.get("duzen") == "klasor":
            return max(1, sum(f.stat().st_size for f in p.parent.iterdir()
                              if f.is_file() and not f.name.endswith((".out.json", ".eski"))))
        return max(1, p.stat().st_size)
    except OSError:
        return 1


def _gecersiz(d: Path) -> set[str]:
    g = d / "GECERSIZ.md"
    if not g.exists():
        return set()
    rx = re.compile(r"^- `([^`/]+?)(?:/|\.out\.json|\.json)?`")
    return {m.group(1) for ln in g.read_text(encoding="utf-8").splitlines() if (m := rx.match(ln))}


def bekleyen(ws_root: Path, sid: str) -> list[str]:
    """Cevap bekleyen paketler. Yönetilen çalışma alanında aşamanın tamamlanma denetimi söyler (aşama
    ajan işinde değilse boş); yönetilmeyende klasör taraması (cevapsız ya da GECERSIZ.md'de)."""
    from bidr.init.config import load_section

    from .state import evaluate
    ws = Workspace(Path(ws_root))
    info = bilgi(sid) or {}
    pk = paketler(ws, info) if info.get("dizin") else {}
    if load_section(ws.root) is not None:
        st = evaluate(ws.root, until=sid).get(sid)
        if st.kim != "ajan" or st.bekleyen is None:
            return []
        return sorted(k for k in st.bekleyen if k in pk)
    d = _dizin(ws, info)
    bad = _gecersiz(d)
    return sorted(k for k in pk if not cikti_yolu(d, info, k).exists() or k in bad)


# -- bölme ---------------------------------------------------------------------------------------------

def grup_anahtari(info: dict, k: str) -> str:
    if info.get("grup") == "alt_bolum":
        parts = k.split(".")
        return ".".join(parts[:2]) if len(parts) >= 2 else k
    return k


def bol(agirliklar: dict[str, int], n: int, grup=None) -> list[list[str]]:
    """Ayrık ve eksiksiz bölme, ağırlığa göre dengeli (en ağır grup en hafif parçaya; LPT). `grup(k)`
    verilirse aynı gruptaki paketler aynı parçada kalır. Boş parça üretilmez; sonuç belirlenimci."""
    grup = grup or (lambda k: k)
    gruplar: dict[str, list[str]] = {}
    for k in sorted(agirliklar):
        gruplar.setdefault(grup(k), []).append(k)
    n = max(1, min(n, len(gruplar)))
    sira = sorted(gruplar, key=lambda g: (-sum(agirliklar[k] for k in gruplar[g]), g))
    yuk = [0] * n
    out: list[list[str]] = [[] for _ in range(n)]
    for g in sira:
        i = min(range(n), key=lambda j: (yuk[j], j))
        out[i].extend(gruplar[g])
        yuk[i] += sum(agirliklar[k] for k in gruplar[g])
    return [sorted(p) for p in out if p]


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def paket_izi(ws: Workspace, info: dict) -> str:
    h = hashlib.sha256()
    for k, p in paketler(ws, info).items():
        st = p.stat()
        h.update(f"{k}\0{st.st_size}\0{st.st_mtime_ns}\n".encode())
    return h.hexdigest()


def durum(ws_root: Path, sid: str, n_bekleyen: int) -> dict:
    """`bidr next` için: aşama bölünebilir mi, kaç parça önerilir, komut."""
    from .state import bidr_command
    info = bilgi(sid)
    if not info:
        return {}
    out = {"bolunebilir": bool(info.get("bolunebilir")), "gerekce": " ".join(str(info.get("gerekce", "")).split()),
           "bekleyen": n_bekleyen}
    if not out["bolunebilir"]:
        out["parca_sayisi"] = 1 if n_bekleyen else 0
        return out
    try:
        a = ayarlar(ws_root)
    except ParcaHatasi:
        a = dict(VARSAYILAN)
    n = parca_sayisi(n_bekleyen, **a)
    if info.get("grup") and n > 1:
        ws = Workspace(Path(ws_root))
        n = min(n, len({grup_anahtari(info, k) for k in paketler(ws, info)}) or 1)
    import shlex
    out.update(parca_sayisi=n, ayar=a, komut=f"{bidr_command()} parcala -w {shlex.quote(str(Path(ws_root)))} {sid}",
               denetim=f"{bidr_command()} parca-denetle -w {shlex.quote(str(Path(ws_root)))} {sid}")
    return out


def parcala(ws_root: Path, sid: str, *, azami: int | None = None, esik: int | None = None,
            adim: int | None = None, parca: int | None = None, taban: int | None = None) -> dict:
    """Cevapsız paketleri ayrık parça listelerine böler ve `work/<aşama>/_parca/`'ya yazar. `parca`:
    parça sayısını zorla (tavanla sınırlı). Döner: bildirim (parcalar[], dosya yolları)."""
    ws = Workspace(Path(ws_root).expanduser().resolve())
    info = bilgi(sid)
    if info is None:
        raise ParcaHatasi(f"'{sid}' bir model aşaması değil (pipeline.yaml'da paralel alanı yok)")
    if not info.get("bolunebilir"):
        raise ParcaHatasi(f"'{sid}' bölünmez: {' '.join(str(info.get('gerekce', '')).split())}")
    a = ayarlar(ws.root, azami=azami, esik=esik, adim=adim, taban=taban)
    keys = bekleyen(ws.root, sid)
    d = _dizin(ws, info)
    pk = paketler(ws, info)
    n = min(parca, a["azami"]) if parca else parca_sayisi(len(keys), **a)
    w = {k: agirlik(pk[k], info) for k in keys}
    parts = bol(w, n, (lambda k: grup_anahtari(info, k))) if keys else []
    pd = d / PARCA
    if pd.exists():
        shutil.rmtree(pd)
    (pd / "yedek").mkdir(parents=True)
    listed = set(keys)
    onceki = {}
    for k, p in cevaplar(ws, info).items():
        if k not in listed:
            onceki[k] = _sha(p)
            shutil.copy2(p, pd / "yedek" / f"{k}.out.json")
    rel = lambda p: str(p.relative_to(ws.root))
    out_parts = []
    for i, ks in enumerate(parts, 1):
        f = pd / f"{i}.txt"
        head = (f"# bidr parça {i}/{len(parts)} · aşama {sid} · {len(ks)} paket\n"
                f"# Yalnız bu listedeki paketlerin cevabını yaz: her paketin cevabı aynı klasörde <ad>.out.json.\n"
                f"# Başka paketin cevabına dokunma; apply'ı çalıştırma (hepsi bitince bir kez çalışır).\n")
        f.write_text(head + "".join(rel(pk[k]) + "\n" for k in ks), encoding="utf-8")
        out_parts.append({"no": i, "dosya": rel(f), "paketler": ks,
                          "cevaplar": [rel(cikti_yolu(d, info, k)) for k in ks],
                          "agirlik": sum(w[k] for k in ks)})
    man = {"surum": 1, "asama": sid, "dizin": info["dizin"], "duzen": info.get("duzen", "dosya"),
           "olusturma": datetime.now().isoformat(timespec="seconds"), "ayar": a, "bekleyen": len(keys),
           "paket_izi": paket_izi(ws, info), "parcalar": out_parts, "onceki": onceki}
    (pd / BILDIRIM).write_text(json.dumps(man, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return man


# -- ezme denetimi ---------------------------------------------------------------------------------------

def _bildirim(ws: Workspace, info: dict) -> dict | None:
    p = _dizin(ws, info) / PARCA / BILDIRIM
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def denetle(ws_root: Path, sid: str, *, duzelt: bool = True) -> dict:
    """Parça dışı yazımı yakalar. Döner: {durum: yok|eski|temiz|ihlal, ihlaller: [{anahtar, neden, dosya}]}.
    `duzelt`: ihlal eden dosya `_parca/reddedilen/`'e taşınır, varsa eski cevap `yedek/`'ten geri konur."""
    ws = Workspace(Path(ws_root).expanduser().resolve())
    info = bilgi(sid) or {}
    if not info.get("dizin"):
        return {"durum": "yok", "ihlaller": []}
    man = _bildirim(ws, info)
    if man is None or man.get("asama") != sid:
        return {"durum": "yok", "ihlaller": []}
    if man.get("paket_izi") != paket_izi(ws, info):
        return {"durum": "eski", "ihlaller": [],
                "neden": "paketler bölmeden sonra değişti (yeniden prepare): parça listeleri geçersiz, denetim yok"}
    d = _dizin(ws, info)
    pd = d / PARCA
    listed = {k for p in man["parcalar"] for k in p["paketler"]}
    onceki: dict = man.get("onceki") or {}
    now = cevaplar(ws, info)
    ihlal = []
    for k, p in now.items():
        if k in listed:
            continue
        if k in onceki and _sha(p) == onceki[k]:
            continue
        neden = "ezildi (bölmeden önce var olan, hiçbir listede olmayan cevap değişti)" if k in onceki \
            else "liste dışı yazıldı (hiçbir parça listesinde yok)"
        ihlal.append({"anahtar": k, "neden": neden, "dosya": str(p.relative_to(ws.root))})
    for k in onceki:
        if k not in now:
            ihlal.append({"anahtar": k, "neden": "silindi (bölmeden önce var olan liste dışı cevap)",
                          "dosya": str(cikti_yolu(d, info, k).relative_to(ws.root))})
    if duzelt and ihlal:
        (pd / "reddedilen").mkdir(parents=True, exist_ok=True)
        damga = datetime.now().strftime("%Y%m%d-%H%M%S")
        for x in ihlal:
            k = x["anahtar"]
            p = cikti_yolu(d, info, k)
            if p.exists():
                shutil.move(str(p), str(pd / "reddedilen" / f"{k}.{damga}.out.json"))
            y = pd / "yedek" / f"{k}.out.json"
            if k in onceki and y.exists():
                shutil.copy2(y, p)
                x["geri_kondu"] = True
    return {"durum": "ihlal" if ihlal else "temiz", "ihlaller": ihlal}


def apply_oncesi(ws_root: Path, dizin: str, log=None) -> int:
    """Her apply'dan önce: klasörün açık bildirimi varsa parça dışı yazımı reddeder (stderr'e yazar).
    Döner: ihlal sayısı. Bildirim yoksa ya da eskiyse hiçbir şey yapmaz."""
    import sys
    ws_root = Path(ws_root).expanduser().resolve()
    p = ws_root / dizin / PARCA / BILDIRIM
    if not p.exists():
        return 0
    try:
        sid = json.loads(p.read_text(encoding="utf-8")).get("asama")
        bilgi(sid)
    except (OSError, ValueError, KeyError):
        return 0
    r = denetle(ws_root, sid)
    for x in r["ihlaller"]:
        msg = (f"parça denetimi: {x['dosya']} reddedildi — {x['neden']}"
               + ("; eski cevap geri kondu" if x.get("geri_kondu") else "") + f" (bkz. {dizin}/{PARCA}/reddedilen/)")
        (log or (lambda m: print(m, file=sys.stderr)))(msg)
    return len(r["ihlaller"])


# -- CLI -------------------------------------------------------------------------------------------------

def _sid(args) -> str:
    if args.asama:
        return args.asama
    from .state import evaluate
    n = evaluate(Path(args.workspace)).sonraki
    if n is None:
        raise ParcaHatasi("bütün aşamalar bitti: bölünecek aşama yok")
    return n.id


def _cmd_parcala(args) -> int:
    import sys
    try:
        sid = _sid(args)
        man = parcala(Path(args.workspace), sid, azami=args.azami, esik=args.esik, adim=args.adim,
                      parca=args.parca, taban=args.taban)
    except (ParcaHatasi, KeyError) as e:
        print(f"HATA {e}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(man, ensure_ascii=False, indent=1))
        return 0
    ps = man["parcalar"]
    if not ps:
        print(f"{sid}: cevap bekleyen paket yok; bölünecek iş yok.")
        return 0
    print(f"{sid}: {man['bekleyen']} cevapsız paket {len(ps)} ayrık parçaya bölündü "
          f"(eşik {man['ayar']['esik']}, adım {man['ayar']['adim']}, tavan {man['ayar']['azami']}).")
    for p in ps:
        print(f"  parça {p['no']}: {len(p['paketler'])} paket → {p['dosya']}")
    print("Her ajana bir parça dosyası verin; ajan yalnız kendi listesindeki paketlere cevap yazar (talimat "
          "tek ajanınkiyle aynı: paketin `istem`i ve README), apply'ı çalıştırmaz. Hepsi bitince bir kez "
          f"`bidr parca-denetle -w {args.workspace} {sid}` ve aşamanın apply komutu (apply de liste dışı yazımı reddeder).")
    return 0


def _cmd_denetle(args) -> int:
    import sys
    try:
        sid = _sid(args)
        r = denetle(Path(args.workspace), sid, duzelt=not args.kuru)
    except (ParcaHatasi, KeyError) as e:
        print(f"HATA {e}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=1))
    elif r["durum"] == "yok":
        print(f"{sid}: açık parça bildirimi yok.")
    elif r["durum"] == "eski":
        print(f"{sid}: {r['neden']}")
    elif r["durum"] == "temiz":
        print(f"{sid}: parça dışı yazım yok.")
    else:
        for x in r["ihlaller"]:
            print(f"İHLAL {x['dosya']}: {x['neden']}" + (" (eski cevap geri kondu)" if x.get("geri_kondu") else ""))
        info = bilgi(sid) or {}
        print(f"{len(r['ihlaller'])} cevap reddedildi" + (" (--kuru: dokunulmadı)" if args.kuru else
                                                         f" (taşındı: {info.get('dizin')}/{PARCA}/reddedilen/)"))
    return 1 if r["durum"] == "ihlal" else 0


def register(sub):
    p = sub.add_parser("parcala", help="model aşamasının cevapsız paketlerini paralel ajanlar için ayrık parça "
                                       "listelerine böler (work/<aşama>/_parca/<k>.txt)")
    p.add_argument("asama", nargs="?", help="aşama kimliği (vars. sıradaki aşama), ör. karar_ince")
    p.add_argument("--workspace", "-w", required=True)
    p.add_argument("--azami", type=int, help=f"en çok parça (vars. ve kesin tavan {TAVAN}; {ENV_AZAMI} ve rapor.paralel_azami düşürür)")
    p.add_argument("--taban", type=int, help=f"eşiğe kadar parça sayısı (vars. {VARSAYILAN['taban']}; "
                                            "paket sayısını aşmaz)")
    p.add_argument("--esik", type=int, help=f"bu sayıya kadar paket `taban` parça (vars. {VARSAYILAN['esik']})")
    p.add_argument("--adim", type=int, help=f"eşikten sonra her kaç pakette bir parça eklenir (vars. {VARSAYILAN['adim']})")
    p.add_argument("--parca", type=int, help="parça sayısını zorla (tavanla sınırlı)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_cmd_parcala)
    p = sub.add_parser("parca-denetle", help="parça listeleri dışında yazılmış ya da ezilmiş cevapları yakalar ve reddeder")
    p.add_argument("asama", nargs="?")
    p.add_argument("--workspace", "-w", required=True)
    p.add_argument("--kuru", action="store_true", help="yalnız raporla, dosyalara dokunma")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_cmd_denetle)
