"""`bidr denetim prepare|apply|karar|ozet`: raporun kör denetimi (isteğe bağlı, rapor render'dan sonra).

Kullanıcının onayladığı tasarım (2026-11-24 elle yapılan kör denetimin hatta taşınması):

prepare  `work/kor_denetim/<anahtar>.json` paketleri. Anahtar ölçüt kodu (`B.1.1`; birimin doldurduğu
         her ölçüt, metni olmayan kanıtsız ölçüt dahil) ya da alan yön paketi (`yon_A` … `yon_D`).
         Ölçüt paketi: raporun ölçüt bölümü (işaretlenen OD, açıklama metni, kanıt listesi), atıf
         yapılan kanıtların METNİ ve ölçütte aday olup kanıt listesine girmemiş belgelerin kısa metni
         (kapsam kaybı; bidr/write/ilgili.py). Yön paketi: alanın güçlü/gelişmeye açık maddeleri ve
         alanın ölçüt bölümleri. Paketler yazarın bağlamını İÇERMEZ (yazım istemi, düzeltme notları,
         doğrulama gerekçeleri, inceleme notları, ince kararın alıntıları yok). Denetçi metni yazmamış,
         taze bir ajandır (model Opus; panel işleyicisi aynı).
apply    şema + kod denetimi. Her alıntı normalize edilerek (bidr.llm.verify_quote) aranır: rapor
         alıntısı raporun o bölümünde (ya da yön maddesinde), kanıt alıntısı belirtilen belgenin metninde.
         Tutmayan bulgu "doğrulanamadı" işaretlenir: gösterilir, işlenmez. Bulgular sınıflanır:
           metin  sayı/özet/çelişki/abartı/genelleme… (ve doğrulanmış K/U cümleleri): `bidr duzelt`
                  kendiliğinden düzeltir (yeniden yazım + bağımsız doğrulama);
           od     denetçinin OD görüşü raporun OD'sinden farklı: bölüm karar verir;
           kanit  kullanılmayan ilgili belge: bölüm karar verir; kabul edilirse ikinci arama paketine
                  girer ve inceleme adayı olur (bidr/candidates/arama.py `denetim` kaynağı).
         Bütün paketler geçerliyse `kor-denetim.json` (makine) ve `kor-denetim.md` (insan) yazılır.
         Puan İÇ ÖLÇÜMDÜR: denetçi yazandan bağımsızdır ama aynı model ailesindendir; kalite belgesi değildir.
karar    `bidr denetim karar <bulgu_id> kabul|ret [--not]` → `kor-denetim-kararlar.jsonl` (yalnız od/kanit;
         kararı ajan vermez). Kabul edilen OD audit okunurken ölçütün OD'si olur (bidr/kor/od.py).
ozet     dosya + kararlar + düzeltme durumu (bulgu başına `durum`).

Tek tur: denetim → düzelt → doğrulama. Otomatik ikinci denetim yok; `prepare --ikinci` (ilk turun
düzeltmesi bittikten sonra) yeni bir ölçüm turudur: bulguları düzeltilmez, önce/sonra puan
karşılaştırması verir. Önceki tur `kor-denetim-<tur>.json` olarak saklanır.
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from bidr.common import Workspace
from bidr.criteria.model import id_key
from bidr.write import ilgili as IL
from bidr.write import packages as K
from bidr.write import run as W

from . import od as OD

STAGE = WORK = "kor_denetim"
TASK, YTASK = "kor_denetim", "kor_denetim_yon"
OUT_JSON, OUT_MD = "kor-denetim.json", "kor-denetim.md"
KARARLAR = OD.KARARLAR
TUR_FILE = "_tur.json"
KEY = r"(?:[A-E]\.\d+\.\d+|yon_[A-D])"
YON = "yon_"
SURUM = 1
OLCEK = {"1": "yanıltıcı", "2": "zayıf", "3": "kullanılabilir taslak", "4": "küçük düzeltmeyle kullanılabilir",
         "5": "doğrudan kullanılabilir"}
ACIKLAMA = ("Puan iç ölçümdür: denetçi metni yazandan bağımsızdır ama aynı model ailesindendir; kalite belgesi "
            "değildir. Metin bulguları kendiliğinden düzeltilir ve yeniden doğrulanır; OD ve kanıt önerileri "
            "bölümün kararına gelir.")
KARAR = ("kabul", "ret")
DKU = {"D": "kaynakla doğru", "K": "kısmen doğru ya da abartılı", "U": "kaynakla uyuşmuyor"}
EV_MAX = 20000        # pakette kanıt başına en çok karakter (alıntı denetimi bütün metinde yapılır)
REL_MAX = 3000        # ilgili belge başına
ATIF = re.compile(r"\s*\[(?:\d+_OD[1-5]\*?|komisyon)\](?:\s*,\s*\[(?:\d+_OD[1-5]\*?|komisyon)\])*")
RULE = ("Metni sen yazmadın; yalnız paketteki belgelere göre denetle. Her alıntı (rapordan ve belgeden) BİREBİR "
        "olmalı: kod arar, tutmayan bulgu işlenmez. Puan 1-5; D/K/U etiketleri; bulgular; kullanılmayan ilgili belgeler.")
TUR_ADLARI = {"sayi": "sayı hatası", "yanlis_ozet": "yanlış özet", "gundem_gerceklesmis": "gündem/davet gerçekleşmiş gibi",
              "sablon_arac": "boş şablon kullanılan araç gibi", "od_kanit_onunde": "olgunluk dili kanıtın önünde",
              "genelleme": "genelleme", "kanit_yok_denmis": "'kanıt yok' denmiş ama var", "celiski": "çelişki",
              "kurum_geneli": "kurum geneli bölüm kanıtı gibi", "abarti": "abartı", "diger": "diğer",
              "olcut_metniyle_celiski": "ölçüt metniyle çelişki", "dayanaksiz": "dayanaksız madde",
              "cumle_K": "kısmen doğru cümle", "cumle_U": "kaynakla uyuşmayan cümle",
              "od_dusur": "OD düşürme önerisi", "od_yukselt": "OD yükseltme önerisi", "kullanilmayan": "kullanılmamış belge"}


class DenetimHatasi(ValueError):
    pass


def work_dir(ws: Workspace) -> Path:
    return ws.root / "work" / WORK


def _read_json(p: Path) -> dict | None:
    try:
        v = json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
    except (OSError, ValueError):
        return None
    return v if isinstance(v, dict) else None


def load(ws: Workspace) -> dict | None:
    """`kor-denetim.json` (yoksa ya da okunamazsa None)."""
    return _read_json(ws.root / OUT_JSON)


def tur_info(ws: Workspace) -> dict | None:
    return _read_json(work_dir(ws) / TUR_FILE)


def strip_cit(s: str) -> str:
    out = ATIF.sub("", s or "")
    return re.sub(r"\s+([.,;:])", r"\1", " ".join(out.split())).strip()


def task_version(task: str) -> str:
    return W.task_version(task)


def is_yon(key: str) -> bool:
    return key.startswith(YON)


# -- raporun denetlenen görünümü --------------------------------------------------------------------

class View:
    """Raporun okunur hali (salt okunur): ölçüt metinleri, kanıt dizini, audit (kabul edilen OD dahil),
    alan maddeleri. Render'ın kurallarıyla aynı: kullanıcının `cikar` dediği metin ve kanıtı kalmamış
    ölçütün metni rapora girmez."""

    def __init__(self, ws_root: Path):
        from bidr.criteria.loader import load_criteria
        from bidr.render.kapsam import fills, workspace_scope
        from bidr.verify import run as V
        from bidr.write import sources as S
        self.ws = Workspace(Path(ws_root))
        sp = W.source_paths(self.ws.root)
        ip = Path(sp["index"]) if sp["index"] else self.ws.root / S.INDEX
        ap = Path(sp["audit"]) if sp["audit"] else self.ws.root / S.AUDIT
        self.index = S.load_index(ip) if ip.exists() else {}
        self.audit = S.load_audit(ap) if ap.exists() else {}
        self.cs = load_criteria()
        kapsam, _ = workspace_scope(self.ws.root, self.cs)
        self.criteria = [s.id for s in self.cs.sub_criteria if fills(kapsam, s.id)]
        human = V.load_human(self.ws)
        self.texts: dict[str, dict] = {}
        for c in self.criteria:
            t = W.load_text(self.ws, c)
            if t and c in self.index and not V.excluded(t, human) and t.get("insan_karari") != "cikar":
                self.texts[c] = t
        self.related_src = IL.Related(self.ws.root)
        self._doc: dict[str, str | None] = {}

    def title(self, c: str) -> str:
        try:
            return self.cs.get(c).title
        except KeyError:
            return ""

    def doc_text(self, did: str) -> str | None:
        if did not in self._doc:
            p = self.ws.text_path(did) if did and re.fullmatch(r"[0-9a-f]{8,64}", did) else None
            self._doc[did] = p.read_text(encoding="utf-8", errors="replace") if p and p.exists() else None
        return self._doc[did]

    def rapor_od(self, c: str) -> int | None:
        """Raporda işaretlenen OD (render'ın seçimiyle aynı: komisyon onayı > kod önerisi > metin)."""
        from bidr.render.run import Result, choose_od
        t = self.texts.get(c)
        od, _ = choose_od(c, self.audit.get(c), (t or {}).get("od_onerisi"), Result(self.ws.root / "_"))
        return od

    def metin(self, c: str) -> str:
        t = self.texts.get(c)
        if not t:
            return ""
        parts = [p.get("metin") or "" for p in t.get("paragraflar") or []]
        if (t.get("onceki_yila_gore") or "").strip():
            parts.append(t["onceki_yila_gore"].strip())
        return "\n\n".join(parts)

    def metin_sha(self, c: str) -> str:
        t = self.texts.get(c)
        return W.text_sha(t) if t else "yok"

    def evidence(self, c: str) -> list[dict]:
        out, seen = [], set()
        for r in self.index.get(c, []):
            out.append({"no": r["kanit_no"], "ad": r.get("ad", ""), "doc_id": r.get("doc_id", ""),
                        "tekrar": r.get("doc_id") in seen})
            seen.add(r.get("doc_id"))
        return out

    def related(self, c: str) -> list[dict]:
        used = {r.get("doc_id") for r in self.index.get(c, []) if r.get("doc_id")}
        return self.related_src.for_criterion(c, used)

    def yon(self, alan: str) -> dict | None:
        from bidr.write import yonler as Y
        t = Y.load(self.ws, alan)
        return t if t and Y.items(t) else None

    def yon_sha(self, alan: str) -> str:
        from bidr.write import yonler as Y
        t = self.yon(alan)
        return Y.text_sha(t) if t else "yok"


def _cut(s: str, n: int) -> str:
    s = s or ""
    if len(s) <= n:
        return s
    h = n * 2 // 3
    return (s[:h] + f"\n[… belge kısaltıldı: ortadaki {len(s) - n} karakter gösterilmiyor …]\n"
            + s[-(n - h):])


def cut_note(txt: str | None, n: int) -> str:
    """Paket başlığına: belge kısaltıldıysa "metin kısaltıldı (N/M karakter)"."""
    m = len(txt or "")
    return f"metin kısaltıldı ({n}/{m} karakter)" if m > n else ""


def criterion_inputs(v: View, c: str) -> tuple[dict, dict]:
    from bidr.write.run import render_criterion
    t = v.texts.get(c)
    od = v.rapor_od(c)
    ev = v.evidence(c)
    L = [f"İşaretlenen OD: {od if od else 'yok'}"]
    if t:
        L.append("Açıklama metni:")
        L += [p.get("metin") or "" for p in t.get("paragraflar") or []]
        if (t.get("onceki_yila_gore") or "").strip():
            L.append("Önceki yıla göre: " + t["onceki_yila_gore"].strip())
        L.append("Kanıt listesi:")
        L += [f"- [{e['no']}] {e['ad']}" for e in ev]
    else:
        L.append("Açıklama metni: yazılmamış (raporda bu ölçüt için kanıt gösterilmemiş).")
    kan = []
    if t:
        for e in ev:
            if e["tekrar"]:
                continue
            doc = v.related_src.docs.get(e["doc_id"]) or {}
            txt = v.doc_text(e["doc_id"])
            info = ", ".join(x for x in (f"doc_id: {e['doc_id']}",
                                         f"tür: {doc.get('doc_type_etiket') or doc.get('doc_type')}"
                                         if doc.get("doc_type") else "",
                                         f"tarih: {doc.get('tarih')}" if doc.get("tarih") else "",
                                         cut_note(txt, EV_MAX)) if x)
            nos = ", ".join(f"[{x['no']}]" for x in ev if x["doc_id"] == e["doc_id"])
            kan.append(f"{nos} {e['ad']} ({info})\n<<<\n{_cut(txt or '(metin yok)', EV_MAX)}\n>>>")
    rel = v.related(c)
    rl = []
    for r in rel:
        rtxt = v.doc_text(r["doc_id"])
        info = ", ".join(x for x in (f"doc_id: {r['doc_id']}", f"tür: {r['tur']}" if r["tur"] else "",
                                     f"tarih: {r['tarih']}" if r["tarih"] else "", cut_note(rtxt, REL_MAX)) if x)
        rl.append(f"{r['ad']} ({info})\n<<<\n{_cut(rtxt or '(metin yok)', REL_MAX)}\n>>>")
    from bidr.write.run import period_of
    inputs = {"olcut": render_criterion(v.cs, c), "donem": str(period_of(v.ws.root) or "belirtilmemiş"),
              "rapor": "\n".join(L), "kanitlar": "\n\n".join(kan) or "yok", "ilgili": "\n\n".join(rl) or "yok"}
    meta = {"anahtar": c, "olcut": c, "metin_sha": v.metin_sha(c), "rapor_od": od, "metin_var": bool(t),
            "kanit_docs": sorted({e["doc_id"] for e in ev if e["doc_id"]}) if t else [],
            "kanit_sayisi": len(ev) if t else 0, "ilgili": [r["doc_id"] for r in rel],
            "kisaltilan": sorted({e["doc_id"] for e in ev if e["doc_id"] and len(v.doc_text(e["doc_id"]) or "") > EV_MAX})
            if t else []}
    return inputs, meta


def yon_inputs(v: View, alan: str) -> tuple[dict, dict]:
    from bidr.write import yonler as Y
    t = v.yon(alan)
    rows = Y.items(t)
    blocks = []
    for c in v.criteria:
        if not c.startswith(alan + "."):
            continue
        txt = strip_cit(v.metin(c))
        od = v.rapor_od(c)
        blocks.append(f"{c} {v.title(c)} — işaretlenen OD: {od if od else 'yok'}\n  "
                      + (f"metin: «{txt}»" if txt else "metin yok (kanıt gösterilmemiş)"))
    try:
        title = f"{alan} {v.cs.get(alan).title}"
    except KeyError:
        title = alan
    inputs = {"alan": title,
              "maddeler": "\n".join(f"{r['yer']} ({'güçlü' if r['liste'] == 'guclu' else 'gelişmeye açık'}): "
                                    f"{r['metin']}" for r in rows),
              "olcutler": "\n\n".join(blocks) or "yok"}
    meta = {"anahtar": f"{YON}{alan}", "alan": alan, "yon_sha": v.yon_sha(alan),
            "maddeler": {r["yer"]: r["metin"] for r in rows},
            "hucreler": sorted({r["liste"] for r in rows})}
    return inputs, meta


# -- prepare -------------------------------------------------------------------------------------------

def prepare(ws_root: Path, *, ikinci: bool = False, backend: W.Backend | None = None) -> dict:
    from bidr.render.run import load_manifest
    backend = backend or W.Backend()
    ws = Workspace(Path(ws_root))
    if not load_manifest(ws.root):
        raise DenetimHatasi("rapor üretilmemiş (bidr render): denetim rapor bittikten sonra istenir")
    d = work_dir(ws)
    info, cur = tur_info(ws), load(ws)
    done = bool(cur and info and cur.get("id") == info.get("id"))
    if ikinci:
        if not done:
            raise DenetimHatasi("bitmiş bir denetim turu yok: önce `bidr denetim prepare` ve `apply`")
        acik = duzelt_acik(ws)
        if acik:
            raise DenetimHatasi("ilk turun düzeltmesi bitmedi (" + "; ".join(acik) + "): ikinci denetim "
                                "düzeltmeler ve kararlar bittikten sonra")
        _archive(ws, int(info["tur"]))
        info = {"tur": int(info["tur"]) + 1, "id": K.sha(K.now() + ":" + str(int(info["tur"]) + 1)),
                "zaman": K.now(), "onceki": f"kor-denetim-{info['tur']}.json"}
    elif done:
        raise DenetimHatasi(f"denetim zaten yapıldı (tur {info['tur']}; {OUT_JSON}). İsteğe bağlı ikinci denetim "
                            "(önce/sonra karşılaştırması): `bidr denetim prepare --ikinci`")
    elif not info:
        info = {"tur": 1, "id": K.sha(K.now() + ":1"), "zaman": K.now()}
    d.mkdir(parents=True, exist_ok=True)
    (d / TUR_FILE).write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")
    v = View(ws.root)
    st = {"tur": info["tur"], "paket": 0, "yeni": 0, "olcut": 0, "yon": 0, "klasor": str(d)}
    keys = []
    for c in v.criteria:
        inputs, meta = criterion_inputs(v, c)
        meta.update(tur=info["tur"], id=info["id"])
        st["yeni"] += K.write_pkg(d, c, backend.render_task(TASK, inputs), meta)
        st["paket"] += 1
        st["olcut"] += 1
        keys.append(c)
    from bidr.write.yonler import ALANLAR
    for a in ALANLAR:
        if not v.yon(a):
            continue
        inputs, meta = yon_inputs(v, a)
        meta.update(tur=info["tur"], id=info["id"])
        st["yeni"] += K.write_pkg(d, f"{YON}{a}", backend.render_task(YTASK, inputs), meta)
        st["paket"] += 1
        st["yon"] += 1
        keys.append(f"{YON}{a}")
    for p in K.pkg_paths(d, KEY):                  # kapsamdan düşen paket: arşive
        if p.stem not in keys:
            _move(d, p.stem, d / "_eski")
    st["bekleyen"] = K.write_readme(d, task=f"{TASK} + {YTASK}", version=task_version(TASK), cmd="denetim",
                                    rule=RULE, pattern=KEY, key="anahtar")
    return st


def _move(d: Path, key: str, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for f in d.glob(f"{key}.*"):
        if f.is_file():
            f.replace(dest / f.name)


def _archive(ws: Workspace, tur: int) -> None:
    """Biten turu saklar: kor-denetim.json/.md → kor-denetim-<tur>.*, paketler → work/kor_denetim/_tur<tur>/."""
    for name in (OUT_JSON, OUT_MD):
        p = ws.root / name
        if p.exists():
            shutil.copy2(p, ws.root / name.replace("kor-denetim", f"kor-denetim-{tur}"))
    d = work_dir(ws)
    dest = d / f"_tur{tur}"
    dest.mkdir(parents=True, exist_ok=True)
    for f in list(d.iterdir()):
        if f.is_file():
            f.replace(dest / f.name)


# -- apply ---------------------------------------------------------------------------------------------

def _q(quote: str, text: str | None) -> bool:
    from bidr.llm import verify_quote
    if not quote or not text:
        return False
    return bool(verify_quote(strip_cit(quote), strip_cit(text)).ok)


def _finding(base: dict, **kw) -> dict:
    rec = {"id": "", "sinif": "metin", "tur": "diger", "olcut": None, "alan": None, "yer": None, "alinti": "",
           "doc_id": "", "belge_adi": "", "kanit_alintisi": "", "aciklama": "", "oneri": "", "rapor_od": None,
           "denetci_od": None, "dogrulama": "dogrulandi", "dogrulama_nedeni": ""}
    rec.update(base)
    rec.update(kw)
    return rec


def _check_quotes(v: View, report_text: str, x: dict, *, need_report: bool = True) -> list[str]:
    why = []
    if need_report and not _q(x.get("alinti", ""), report_text):
        why.append("rapor alıntısı raporun bu bölümünde bulunamadı")
    did, ka = (x.get("doc_id") or "").strip(), (x.get("kanit_alintisi") or "").strip()
    if ka and not did:
        why.append("kanıt alıntısının belgesi (doc_id) yok")
    elif did and v.doc_text(did) is None:
        why.append(f"belge bulunamadı: {did}")
    elif did and ka and not _q(ka, v.doc_text(did)):
        why.append("kanıt alıntısı belgede bulunamadı")
    return why


def _norm(s: str) -> str:
    from bidr.candidates.arama import norm_quote
    return norm_quote(strip_cit(s))


# Yokluk iddiası ("kaynakta yok / bulunamadı"): pakette kısaltılmış belgede denetçi görmediği kısım için
# yanlış "yok" diyebilir (prova 2026-11-24: 23 bulgu). Kod iddiayı kısaltılmış belgelerin TAM metninde arar.
YOKLUK = re.compile(r"bulunama|bulunmuyor|bulunmamakta|yer al(?:miyor|mamakta|madigi)|gecmiyor|gecmemekte|"
                    r"gorunmuyor|gorulmuyor|(?:belge|kanit|kaynak|metin)\w{0,4} (?:hic )?yok\b|dogrulanama|"
                    r"rastlanma|izine rastlan")
TIRNAK = re.compile(r"[«“\"]([^»”\"]{4,160})[»”\"]")
DURAK = {"olarak", "ile", "icin", "gibi", "olan", "olup", "veya", "daha", "kadar", "sonra", "once", "uzere",
         "tarafindan", "ayrica", "bunun", "bu", "her", "tum", "bolum", "bolumu", "bolumde", "bolumumuz",
         "bolumumuzde", "yapilmaktadir", "edilmektedir", "bulunmaktadir", "verilmektedir", "olmaktadir"}


def absence_claim(x: dict, *, text: str = "") -> bool:
    """Bulgu/cümle bir yokluk iddiası mı: şemanın `iddia: "yok"` alanı; alan yoksa (eski cevap) açıklama /
    gerekçe metninden. "Kanıt yok denmiş" türü tersidir (denetçi VARLIK söyler)."""
    if x.get("tur") == "kanit_yok_denmis":
        return False
    if x.get("iddia"):
        return x["iddia"] == "yok"
    from bidr.candidates.text import fold
    return bool(YOKLUK.search(fold(text or x.get("aciklama") or x.get("gerekce") or "")))


def hidden_part(full: str, n: int = EV_MAX, pay: int = 300) -> str:
    """Kısaltılmış belgenin pakette gösterilmeyen ortası (`_cut` ile aynı bölme; kenarlarda küçük pay)."""
    if len(full) <= n:
        return ""
    h = n * 2 // 3
    return full[max(0, h - pay):len(full) - (n - h) + pay]


def _claim_in(phrases: list[str], alinti: str, full: str) -> str | None:
    """Yokluğu iddia edilen ifade tam metinde var mı. Açıklama ifadeyi tırnakla veriyorsa yalnız o ifade
    (normalize, birebir) tam metinde aranır. Tırnak yoksa rapor alıntısının içerik sözcüklerinin en az %80'i
    ve bütün sayıları aynı yakın pencerede aranır — yalnız denetçinin GÖRMEDİĞİ ortada (gördüğü kısımdaki
    yokluk hükmü bir değerlendirmedir, korunur)."""
    from bidr.candidates.arama import norm_quote
    if phrases:
        padded = f" {norm_quote(full)} "
        for ph in phrases:
            n = norm_quote(ph)
            if len(n) >= 6 and f" {n} " in padded:
                return ph
        return None
    T = norm_quote(hidden_part(full))
    if not T:
        return None
    words = norm_quote(strip_cit(alinti)).split()
    nums = {w for w in words if w.isdigit()}
    cw = {w[:5] for w in words if len(w) >= 4 and not w.isdigit() and w not in DURAK}
    if len(cw) < 3:
        return None
    need = -(-len(cw) * 4 // 5)
    toks = T.split()
    win = max(15, 3 * len(words))
    for i in range(0, max(1, len(toks) - win // 2), max(1, win // 2)):
        seg = toks[i:i + win]
        if nums - set(seg):
            continue
        if len(cw & {w[:5] for w in seg}) >= need:
            return strip_cit(alinti)
    return None


def full_text_hit(v: View, meta: dict, x: dict, why_text: str) -> dict | None:
    """Yokluk iddiası kısaltılmış bir belgenin tam metninde çürüyorsa {doc_id, ifade}; değilse None.
    Bakılan belgeler: bulgunun belgesi ve ölçütün kanıtları, yalnız pakette kısaltılmış olanlar
    (kısaltılmamış belgeyi denetçi bütünüyle gördü; onun hükmü korunur)."""
    if not absence_claim(x, text=why_text):
        return None
    docs = [d for d in dict.fromkeys([(x.get("doc_id") or "").strip(), *(meta.get("kanit_docs") or [])]) if d]
    phrases = TIRNAK.findall(why_text or "")
    for did in docs:
        full = v.doc_text(did)
        if not full or len(full) <= EV_MAX:
            continue
        hit = _claim_in(phrases, x.get("alinti") or "", full)
        if hit:
            return {"doc_id": did, "ifade": hit}
    return None


def _tam_metinde(hit: dict) -> str:
    return (f"doğrulanamadı — tam metinde var: yokluk iddiası («{hit['ifade'][:120]}») pakette kısaltılan belgenin "
            f"tam metninde bulundu ({hit['doc_id']})")


def judge_criterion(v: View, c: str, meta: dict, out: dict) -> tuple[dict, list[dict], list[str]]:
    """(ölçüt satırı, bulgular, geçersizlik hataları)."""
    text = v.metin(c)
    counts = {"D": 0, "K": 0, "U": 0}
    finds: list[dict] = []
    n = 0
    seen_q: set[str] = set()
    for x in out["bulgular"]:
        n += 1
        why = _check_quotes(v, text, x)
        hit = None if why else full_text_hit(v, meta, x, x.get("aciklama") or "")
        if hit:
            why = [_tam_metinde(hit)]
        finds.append(_finding({"id": f"{c}-{n}", "olcut": c, "tur": x["tur"], "alinti": x["alinti"],
                               "doc_id": x["doc_id"], "kanit_alintisi": x["kanit_alintisi"],
                               "aciklama": x["aciklama"], "oneri": x["oneri"], "iddia": x.get("iddia") or "",
                               "belge_adi": v.related_src.name(x["doc_id"]) if x["doc_id"] else ""},
                              dogrulama="dogrulanamadi" if why else "dogrulandi", dogrulama_nedeni="; ".join(why),
                              **({"tam_metinde": hit} if hit else {})))
        if not why:
            seen_q.add(_norm(x["alinti"]))
    cum = []
    for x in out["cumleler"]:
        why = _check_quotes(v, text, x)
        if not why and x["etiket"] in ("K", "U"):
            hit = full_text_hit(v, meta, x, x.get("gerekce") or "")
            if hit:
                why = [_tam_metinde(hit)]
        ok = not why
        cum.append({**x, "dogrulama": "dogrulandi" if ok else "dogrulanamadi", "dogrulama_nedeni": "; ".join(why)})
        if not ok:
            continue
        counts[x["etiket"]] += 1
        if x["etiket"] in ("K", "U") and _norm(x["alinti"]) not in seen_q:
            n += 1
            seen_q.add(_norm(x["alinti"]))
            finds.append(_finding({"id": f"{c}-{n}", "olcut": c, "tur": f"cumle_{x['etiket']}", "alinti": x["alinti"],
                                   "doc_id": x["doc_id"], "kanit_alintisi": x["kanit_alintisi"],
                                   "aciklama": x["gerekce"] or ("kaynakla uyuşmuyor" if x["etiket"] == "U"
                                                                else "kısmen doğru / abartılı"),
                                   "belge_adi": v.related_src.name(x["doc_id"]) if x["doc_id"] else ""}))
    rapor_od = meta.get("rapor_od")
    d_od = int(out["denetci_od"])
    if rapor_od and d_od != int(rapor_od):
        onayli = (v.audit.get(c) or {}).get("od_onayli") in (1, 2, 3, 4, 5)
        finds.append(_finding({"id": f"{c}-od", "sinif": "od", "olcut": c,
                               "tur": "od_dusur" if d_od < int(rapor_od) else "od_yukselt",
                               "aciklama": out["od_gerekce"], "oneri": f"OD{d_od}", "rapor_od": int(rapor_od),
                               "denetci_od": d_od, "od_kod": (v.audit.get(c) or {}).get("od"),
                               "od_onayli": onayli}))
    j = 0
    kanit_docs = set(meta.get("kanit_docs") or [])
    for x in out["kullanilmayan"]:
        j += 1
        did = x["doc_id"].strip()
        why = []
        if v.doc_text(did) is None:
            why.append(f"belge bulunamadı: {did}")
        elif did in kanit_docs:
            why.append("belge zaten bu ölçütün kanıt listesinde")
        elif not _q(x["kanit_alintisi"], v.doc_text(did)):
            why.append("kanıt alıntısı belgede bulunamadı")
        finds.append(_finding({"id": f"{c}-k{j}", "sinif": "kanit", "olcut": c, "tur": "kullanilmayan",
                               "doc_id": did, "belge_adi": v.related_src.name(did), "kanit_alintisi": x["kanit_alintisi"],
                               "aciklama": x["neden"]},
                              dogrulama="dogrulanamadi" if why else "dogrulandi", dogrulama_nedeni="; ".join(why)))
    row = {"olcut": c, "baslik": v.title(c), "rapor_od": rapor_od, "denetci_od": d_od, "puan": int(out["puan"]),
           "gerekce": out["puan_gerekce"], "od_gerekce": out["od_gerekce"], **counts,
           "metin_var": bool(meta.get("metin_var")), "kanit_sayisi": int(meta.get("kanit_sayisi") or 0),
           "genel": out.get("genel", ""), "cumleler": cum}
    return row, finds, []


def judge_yon(v: View, key: str, meta: dict, out: dict) -> tuple[list[dict], list[dict], list[str]]:
    alan = meta["alan"]
    hs = [h["hucre"] for h in out["hucreler"]]
    errs = []
    if len(hs) != len(set(hs)):
        errs.append("aynı hücre iki kez puanlanmış")
    extra = set(hs) - set(meta.get("hucreler") or [])
    if extra:
        errs.append(f"maddesi olmayan hücre puanlanmış: {', '.join(sorted(extra))}")
    if errs:
        return [], [], errs
    items = meta.get("maddeler") or {}
    rows = [{"alan": alan, "hucre": h["hucre"], "puan": int(h["puan"]), "sorun": h["sorun"]} for h in out["hucreler"]]
    finds = []
    for n, x in enumerate(out["bulgular"], 1):
        why = []
        if x["yer"] not in items:
            why.append(f"böyle bir madde yok: {x['yer']}")
        elif not _q(x["alinti"], items[x["yer"]]):
            why.append("alıntı maddede bulunamadı")
        finds.append(_finding({"id": f"{key}-{n}", "alan": alan, "yer": x["yer"], "olcut": x["olcut"] or None,
                               "tur": x["tur"], "alinti": x["alinti"], "aciklama": x["aciklama"], "oneri": x["oneri"]},
                              dogrulama="dogrulanamadi" if why else "dogrulandi", dogrulama_nedeni="; ".join(why)))
    return rows, finds, []


def _izi(d: Path) -> str:
    parts = []
    for p in K.pkg_paths(d, KEY):
        o = p.with_name(f"{p.stem}.out.json")
        parts.append([p.stem, K.sha(p.read_text(encoding="utf-8")),
                      K.sha(o.read_text(encoding="utf-8")) if o.exists() else None])
    return K.sha(json.dumps(parts))


def pending(ws: Workspace) -> dict:
    """Aşama denetimi ve apply için: {paket, cevapsiz, gecersiz, eski} (anahtar kümeleri)."""
    d = work_dir(ws)
    info = tur_info(ws) or {}
    out = {"paket": set(), "cevapsiz": set(), "gecersiz": set(), "eski": set()}
    if not d.exists():
        return out
    from bidr.pipeline.checks import _invalid_keys
    bad = _invalid_keys(d / "GECERSIZ.md", r"^- `([^`]+)\.json`")
    v = None
    for p in K.pkg_paths(d, KEY):
        pkg = _read_json(p)
        if not pkg:
            continue
        k, meta = p.stem, pkg.get("meta") or {}
        out["paket"].add(k)
        task = YTASK if is_yon(k) else TASK
        if meta.get("id") != info.get("id") or str(pkg.get("surum")) != task_version(task):
            out["eski"].add(k)
            continue
        v = v or View(ws.root)
        cur = v.yon_sha(meta["alan"]) if is_yon(k) else v.metin_sha(k)
        if cur != (meta.get("yon_sha") if is_yon(k) else meta.get("metin_sha")):
            out["eski"].add(k)
            continue
        if not p.with_name(f"{k}.out.json").exists():
            out["cevapsiz"].add(k)
        elif k in bad:
            out["gecersiz"].add(k)
    return out


def apply(ws_root: Path, *, model: str = "ajan:belirtilmemis", backend: W.Backend | None = None) -> dict:
    backend = backend or W.Backend()
    ws = Workspace(Path(ws_root))
    d = work_dir(ws)
    info = tur_info(ws)
    if not info:
        raise DenetimHatasi("denetim istenmemiş: önce `bidr denetim prepare`")
    v = View(ws.root)
    st = {"tur": info["tur"], "bekleyen": [], "gecersiz": {}, "eski": [], "islenen": 0, "yazildi": False}
    olc, yon, finds, msha, ysha = [], [], [], {}, {}
    for p in K.pkg_paths(d, KEY):
        pkg = json.loads(p.read_text(encoding="utf-8"))
        k, meta = p.stem, pkg["meta"]
        task = YTASK if is_yon(k) else TASK
        if meta.get("id") != info["id"] or str(pkg["surum"]) != task_version(task):
            st["eski"].append(k)
            continue
        cur = v.yon_sha(meta["alan"]) if is_yon(k) else v.metin_sha(k)
        if cur != (meta.get("yon_sha") if is_yon(k) else meta.get("metin_sha")):
            st["eski"].append(k)                  # rapor paketten sonra değişti: prepare yeniler
            continue
        outp = d / pkg["cikti_dosyasi"]
        if not outp.exists():
            st["bekleyen"].append(k)
            continue
        out, errs = backend.validate_output(task, outp.read_text(encoding="utf-8"))
        if out is None:
            st["gecersiz"][k] = errs[:5]
            continue
        if is_yon(k):
            rows, fs, errs = judge_yon(v, k, meta, out)
            if errs:
                st["gecersiz"][k] = errs
                continue
            yon += rows
            ysha[meta["alan"]] = cur
        else:
            row, fs, errs = judge_criterion(v, k, meta, out)
            if errs:
                st["gecersiz"][k] = errs
                continue
            olc.append(row)
            msha[k] = cur
        finds += fs
        st["islenen"] += 1
    K.write_invalid(d, f"{TASK} + {YTASK}", st["gecersiz"])
    if st["bekleyen"] or st["gecersiz"] or st["eski"] or not st["islenen"]:
        return st
    olc.sort(key=lambda r: id_key(r["olcut"]))
    yon.sort(key=lambda r: (r["alan"], r["hucre"]))
    js = {"surum": SURUM, "ic_olcum": True, "id": info["id"], "tur": int(info["tur"]), "zaman": K.now(),
          "model": model, "aciklama": ACIKLAMA, "olcek": OLCEK, "olcutler": olc, "yonler": yon, "bulgular": finds,
          "metin_sha": msha, "yon_sha": ysha, "paket_izi": _izi(d)}
    js["ozet"] = summary(js)
    js["karsilastirma"] = compare(ws, js, info.get("onceki"))
    (ws.root / OUT_JSON).write_text(json.dumps(js, ensure_ascii=False, indent=1), encoding="utf-8")
    write_md(ws, view_dict(ws, js))
    st["yazildi"] = True
    st["ozet"] = js["ozet"]
    return st


def _avg(xs: list) -> float | None:
    xs = [x for x in xs if isinstance(x, (int, float))]
    return round(sum(xs) / len(xs), 2) if xs else None


def summary(js: dict) -> dict:
    fs = js.get("bulgular") or []
    ok = [f for f in fs if f.get("dogrulama") == "dogrulandi"]
    return {"ortalama": _avg([r["puan"] for r in js.get("olcutler") or []]),
            "yon_ortalama": _avg([r["puan"] for r in js.get("yonler") or []]),
            "D": sum(r.get("D", 0) for r in js.get("olcutler") or []),
            "K": sum(r.get("K", 0) for r in js.get("olcutler") or []),
            "U": sum(r.get("U", 0) for r in js.get("olcutler") or []),
            "bulgu": {"metin": sum(f["sinif"] == "metin" for f in ok), "od": sum(f["sinif"] == "od" for f in ok),
                      "kanit": sum(f["sinif"] == "kanit" for f in ok), "dogrulanamadi": len(fs) - len(ok)}}


def compare(ws: Workspace, js: dict, onceki: str | None) -> dict | None:
    prev = _read_json(ws.root / onceki) if onceki else None
    if not prev:
        return None
    po = {r["olcut"]: r["puan"] for r in prev.get("olcutler") or []}
    py = {(r["alan"], r["hucre"]): r["puan"] for r in prev.get("yonler") or []}
    return {"onceki_tur": prev.get("tur"),
            "ortalama": {"once": (prev.get("ozet") or {}).get("ortalama"), "sonra": js["ozet"]["ortalama"]},
            "yon_ortalama": {"once": (prev.get("ozet") or {}).get("yon_ortalama"), "sonra": js["ozet"]["yon_ortalama"]},
            "olcutler": [{"olcut": r["olcut"], "once": po.get(r["olcut"]), "sonra": r["puan"]}
                         for r in js["olcutler"]],
            "yonler": [{"alan": r["alan"], "hucre": r["hucre"], "once": py.get((r["alan"], r["hucre"])),
                        "sonra": r["puan"]} for r in js["yonler"]]}


# -- kararlar ve düzeltme durumu ------------------------------------------------------------------------

def load_kararlar(ws: Workspace, js: dict | None = None) -> dict[str, dict]:
    """{bulgu_id: son karar} — yalnız bu denetimin (id) kararları."""
    js = js if js is not None else load(ws)
    out: dict[str, dict] = {}
    for r in OD.load_decisions(ws.root):
        if js and r.get("denetim") == js.get("id"):
            out[r["bulgu_id"]] = r
    return out


def target(f: dict) -> str | None:
    """Metin bulgusunun düzeltileceği yer: ölçüt metni (`B.1.1`) ya da alan maddeleri (`yon_A`)."""
    if f.get("alan"):
        return f"{YON}{f['alan']}"
    return f.get("olcut")


def _record(ws: Workspace, key: str) -> dict | None:
    if is_yon(key):
        from bidr.write import yonler as Y
        return Y.load(ws, key[len(YON):])
    return W.load_text(ws, key)


def _record_text(key: str, t: dict | None) -> str:
    if not t:
        return ""
    if is_yon(key):
        from bidr.write import yonler as Y
        return "\n".join(r["metin"] for r in Y.items(t))
    parts = [p.get("metin") or "" for p in t.get("paragraflar") or []]
    return "\n\n".join(parts + [t.get("onceki_yila_gore") or ""])


def consumed(js: dict, t: dict | None) -> set[str]:
    dz = (t or {}).get("duzeltme") or {}
    return set(dz.get("bulgular") or []) if dz.get("denetim") == js.get("id") else set()


def statuses(ws: Workspace, js: dict, key: str | None = None) -> dict[str, tuple[str, str]]:
    """{bulgu_id: (durum, not)} — duzeltilecek | duzeltildi | karar_bekliyor | kabul | ret | dogrulanamadi | bilgi.
    `key` verilirse yalnız o hedefin (ölçüt ya da `yon_X`) bulguları."""
    kar = load_kararlar(ws, js)
    olcum = int(js.get("tur") or 1) >= 2
    recs: dict[str, dict | None] = {}
    out = {}
    audit = None
    for f in js.get("bulgular") or []:
        fid = f["id"]
        if key is not None and target(f) != key:
            continue
        if f.get("dogrulama") != "dogrulandi":
            out[fid] = ("dogrulanamadi", f.get("dogrulama_nedeni") or "")
            continue
        if olcum:
            out[fid] = ("bilgi", "ikinci denetim ölçümdür: bulgular kendiliğinden düzeltilmez")
            continue
        if f["sinif"] == "metin":
            hedef = target(f)   # `key` (süzgeç) ezilmesin: yoksa ilk hedeften sonrakiler atlanır
            if hedef not in recs:
                recs[hedef] = _record(ws, hedef)
            t = recs[hedef]
            if fid in consumed(js, t):
                out[fid] = ("duzeltildi", "")
            elif not t:
                out[fid] = ("bilgi", "düzeltilecek metin yok")
            elif not _q(f["alinti"], _record_text(hedef, t)):
                out[fid] = ("bilgi", "metin denetimden sonra değişti; alıntı artık metinde yok")
            else:
                out[fid] = ("duzeltilecek", "")
            continue
        k = kar.get(fid)
        if k:
            note = ""
            if f["sinif"] == "od" and k["karar"] == "kabul":
                if audit is None:
                    audit = _audit(ws)
                row = audit.get(f["olcut"]) or {}
                if (row.get("od_denetim") or {}).get("bulgu_id") != fid:
                    note = "karar uygulanmıyor (komisyon OD onayı ya da kod önerisi sonradan değişti)"
            out[fid] = (k["karar"], note)
        elif f["sinif"] == "od" and f.get("od_onayli"):
            out[fid] = ("bilgi", "bu ölçütün OD'si komisyonca onaylanmış (inceleme tablosu); değişiklik orada yapılır")
        else:
            out[fid] = ("karar_bekliyor", "")
    return out


def _audit(ws: Workspace) -> dict[str, dict]:
    from bidr.write import sources as S
    sp = W.source_paths(ws.root)
    ap = Path(sp["audit"]) if sp["audit"] else ws.root / S.AUDIT
    return S.load_audit(ap) if ap.exists() else {}


def view_dict(ws: Workspace, js: dict) -> dict:
    """`bidr denetim ozet --json`: dosya + bulgu başına güncel durum ve karar."""
    st = statuses(ws, js)
    kar = load_kararlar(ws, js)
    out = {k: v for k, v in js.items() if k not in ("metin_sha", "yon_sha", "paket_izi")}
    out["olcutler"] = [{k: v for k, v in r.items() if k != "cumleler"} for r in js.get("olcutler") or []]
    fs = []
    for f in js.get("bulgular") or []:
        d, note = st.get(f["id"], ("bilgi", ""))
        k = kar.get(f["id"])
        fs.append({**f, "durum": d, "durum_notu": note,
                   "karar": {"karar": k["karar"], "not": k.get("not") or "", "zaman": k.get("zaman")} if k else None})
    out["bulgular"] = fs
    # hattı tutmayan, bölüm kararını bekleyen OD/kanıt önerileri (rapor tamamlandı sayılır; karar ne zaman verilirse)
    out["karar_bekleyen_sayisi"] = sum(1 for f in fs if f["durum"] == "karar_bekliyor")
    out["dku"] = DKU
    out["tur_adlari"] = TUR_ADLARI
    return out


def karar_bekleyen(ws: Workspace, js: dict | None = None) -> list[dict]:
    js = js if js is not None else load(ws)
    if not js:
        return []
    st = statuses(ws, js)
    out = []
    for f in js.get("bulgular") or []:
        if st.get(f["id"], ("",))[0] != "karar_bekliyor":
            continue
        if f["sinif"] == "od":
            oz = f"{f['olcut']}: raporun OD'si {f['rapor_od']}, denetçinin görüşü {f['denetci_od']} — {f['aciklama']}"
        else:
            oz = f"{f['olcut']}: kullanılmamış belge «{f['belge_adi']}» — {f['aciklama']}"
        out.append({"bulgu_id": f["id"], "sinif": f["sinif"], "olcut": f["olcut"], "ozet": oz[:400],
                    "rapor_od": f.get("rapor_od"), "denetci_od": f.get("denetci_od"),
                    "doc_id": f.get("doc_id") or None, "belge_adi": f.get("belge_adi") or None})
    return out


def decide(ws_root: Path, bulgu_id: str, karar: str, note: str = "") -> dict:
    """Bölümün kararı (`bidr denetim karar`) → kor-denetim-kararlar.jsonl. Ajan kendi kararını yazmaz."""
    ws = Workspace(Path(ws_root))
    if karar not in KARAR:
        raise DenetimHatasi(f"karar '{karar}' geçersiz ({' | '.join(KARAR)})")
    js = load(ws)
    if not js:
        raise DenetimHatasi(f"{OUT_JSON} yok: denetim yapılmadı")
    f = next((x for x in js.get("bulgular") or [] if x["id"] == bulgu_id), None)
    if f is None:
        raise DenetimHatasi(f"bulgu yok: {bulgu_id}")
    if f["sinif"] not in ("od", "kanit"):
        raise DenetimHatasi(f"{bulgu_id} bir metin bulgusu: kendiliğinden düzeltilir, karar gerekmez")
    if f.get("dogrulama") != "dogrulandi":
        raise DenetimHatasi(f"{bulgu_id} doğrulanamadı ({f.get('dogrulama_nedeni')}): karar verilemez")
    if int(js.get("tur") or 1) >= 2:
        raise DenetimHatasi("ikinci denetim ölçümdür: bulgularına karar verilmez")
    if f["sinif"] == "od" and f.get("od_onayli") and karar == "kabul":
        raise DenetimHatasi(f"{f['olcut']} OD'si komisyonca onaylanmış (inceleme tablosu 'Ölçüt özeti'); "
                            "değişiklik orada yapılır")
    rec = {"bulgu_id": bulgu_id, "denetim": js["id"], "tur": js["tur"], "sinif": f["sinif"], "olcut": f["olcut"],
           "karar": karar, "not": note, "zaman": K.now(), "kayit": "insan"}
    if f["sinif"] == "od":
        od_kod = (_audit_raw(ws).get(f["olcut"]) or {}).get("od")
        rec.update(od=f["denetci_od"], od_onceki=f["rapor_od"], od_kod=od_kod)
    else:
        rec.update(doc_id=f["doc_id"])
    with open(ws.root / KARARLAR, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    write_md(ws, view_dict(ws, js))
    return rec


def _audit_raw(ws: Workspace) -> dict[str, dict]:
    """Audit satırları, denetim OD kararı UYGULANMADAN (kararın dayandığı kod önerisi)."""
    from bidr.write import sources as S
    sp = W.source_paths(ws.root)
    ap = Path(sp["audit"]) if sp["audit"] else ws.root / S.AUDIT
    if not ap.exists():
        return {}
    d = json.loads(ap.read_text(encoding="utf-8"))
    rows = d.get("olcutler", d) if isinstance(d, dict) else d
    return {r["olcut"]: r for r in rows}


def kanit_ciftleri(ws_root: Path, *, recs: dict[str, dict] | None = None, bekleyen: bool = True) -> list[dict]:
    """Bölümün kabul ettiği kullanılmamış belge önerileri: [{doc_id, olcut, bulgu_id}]. `bekleyen`:
    ikinci aramayla `denetim` kaynağıyla henüz bakılmamış olanlar (bidr/candidates/arama.py)."""
    ws = Workspace(Path(ws_root))
    js = load(ws)
    if not js:
        return []
    out = []
    for fid, k in load_kararlar(ws, js).items():
        if k.get("sinif") != "kanit" or k.get("karar") != "kabul" or not k.get("doc_id"):
            continue
        out.append({"doc_id": k["doc_id"], "olcut": k["olcut"], "bulgu_id": fid})
    if not bekleyen or not out:
        return out
    if recs is None:
        from bidr.decide.run import load_decisions
        recs = load_decisions(ws)
    from bidr.candidates.arama import done_criteria
    keep = []
    for x in out:
        rec = recs.get(x["doc_id"]) or {}
        oc = ((rec.get("ikinci_arama") or {}).get("olcutler") or {}).get(x["olcut"]) or {}
        if x["olcut"] in done_criteria(rec) and "denetim" in (oc.get("kaynak") or []):
            continue
        keep.append(x)
    return keep


# -- düzeltme notları (bidr write / bidr yonler paketlerine girer) --------------------------------------

def excluded(ws: Workspace, key: str, t: dict | None) -> bool:
    """Bölümün rapordan çıkardığı metin (`verify karar … cikar` ya da `write karar … cikar`): denetim
    düzeltmesine girmez (insan kararı korunur)."""
    if is_yon(key) or not t:
        return False
    from bidr.verify import run as V
    return t.get("insan_karari") == "cikar" or V.excluded(t, V.load_human(ws))


def notes(ws: Workspace, key: str, js: dict | None = None, t: dict | None = None) -> list[dict]:
    """Hedefin (ölçüt metni ya da alan maddeleri) bekleyen düzeltme notları: düzeltilecek metin bulguları
    ve kabul edilip audit'e yansımış ama metne henüz işlenmemiş OD kararı."""
    js = js if js is not None else load(ws)
    if not js or int(js.get("tur") or 1) >= 2:
        return []
    t = t if t is not None else _record(ws, key)
    if excluded(ws, key, t):
        return []
    st = statuses(ws, js, key)
    done = consumed(js, t)
    out = []
    for f in js.get("bulgular") or []:
        if f["id"] in done:
            continue
        if f["sinif"] == "metin" and target(f) == key and st.get(f["id"], ("",))[0] == "duzeltilecek":
            out.append(f)
        elif (f["sinif"] == "od" and not is_yon(key) and f["olcut"] == key and st.get(f["id"]) == ("kabul", "")):
            out.append(f)
    return out


def section(ws: Workspace, key: str, fs: list[dict], t: dict | None) -> str:
    """Yazım/yön paketinin istemine eklenen DENETİM DÜZELTME NOTU bölümü."""
    v_idx = {}
    if not is_yon(key):
        from bidr.write import sources as S
        sp = W.source_paths(ws.root)
        ip = Path(sp["index"]) if sp["index"] else ws.root / S.INDEX
        for r in (S.load_index(ip).get(key, []) if ip.exists() else []):
            v_idx.setdefault(r.get("doc_id"), r["kanit_no"])
    rel = IL.Related(ws.root)
    yer = "maddeleri" if is_yon(key) else "metni"
    L = ["DENETİM DÜZELTME NOTU (bağımsız bir denetçinin bulguları; alıntıları kod raporda ve belgede doğruladı)",
         f"Bu {'alanın güçlü/gelişmeye açık yön' if is_yon(key) else 'ölçütün açıklama'} {yer} bağımsız denetimde "
         "aşağıdaki sorunlarla işaretlendi. Yukarıdaki kurallarla ve yalnız yukarıdaki dayanağa göre yeniden yaz:",
         "- her sorunu dayanağın gösterdiği kadarıyla düzelt: sayıyı kaynaktaki gibi yaz, özeti düzelt, abartıyı ve "
         "genellemeyi kaldır, gündem/davet belgesine dayanan cümlede gerçekleşme ('görüşülmüştür', 'yapılmıştır') "
         "deme, boş şablonu kullanılan araç gibi sunma, kurum geneli belgeyi bölümün kanıtı gibi sunma, aynı "
         "bölümün güçlü yönüyle ya da ölçüt metniyle çelişen yokluk hükmü kurma;",
         "- denetçinin önerisi bağlayıcı değildir: dayanak önerinin söylediğini göstermiyorsa öneriyi uygulama, "
         "cümleyi dayanağın gösterdiği kadarına indir ya da çıkar;",
         "- sorunsuz cümleleri koru; yeni iddia ekleme; atıf, biçim ve yasak ifade kuralları aynı; denetçiyi ikna "
         "etmeye çalışan açıklama yazma.", "", "Bulgular:"]
    for f in fs:
        if f["sinif"] == "od":
            L.append(f"- [{f['id']}] Bölüm bu ölçütün olgunluk düzeyini OD{f['denetci_od']} olarak kabul etti "
                     f"(raporda OD{f['rapor_od']}). Metin bu düzeyin üstünde olgunluk dili kullanmaz"
                     + ("; düzey yükseldiyse yalnız kanıtın gösterdiğini anlat." if f["denetci_od"] > f["rapor_od"]
                        else "."))
            continue
        ref = ""
        if f.get("doc_id"):
            no = v_idx.get(f["doc_id"])
            ref = f"[{no}]" if no else f"«{rel.name(f['doc_id'])}»"
        s = f"- [{f['id']}] ({TUR_ADLARI.get(f['tur'], f['tur'])}"
        s += f"; {f['yer']}" if f.get("yer") else ""
        s += f") raporda: «{f['alinti']}» — sorun: {f['aciklama']}"
        if f.get("kanit_alintisi"):
            s += f" — kaynak {ref}: «{f['kanit_alintisi']}»"
        if f.get("oneri"):
            s += f" — denetçinin önerisi: {f['oneri']}"
        L.append(s)
    L += ["", f"MEVCUT {'MADDELER' if is_yon(key) else 'METİN'} (yalnız düzeltme için; kanıt değildir)", "<<<",
          _record_text(key, t).strip(), ">>>"]
    return "\n".join(L)


def kanit_alintilari(ws: Workspace, key: str, ids, js: dict | None = None) -> list[dict]:
    """Uygulanan metin bulgularının (`ids`: düzeltme izi) denetçi kanıt alıntıları — apply'da belgede
    doğrulanmış olanlar: [{id, doc_id, alinti}]. Yazım ve doğrulama paketleri bunları kanıt alıntısı olarak
    görür; böylece denetçinin tam belgede bulduğu doğru bilgi "kanıtta yok" diye silinmez."""
    js = js if js is not None else load(ws)
    if not js or int(js.get("tur") or 1) >= 2 or is_yon(key):
        return []
    ids = set(ids or [])
    out = []
    for f in js.get("bulgular") or []:
        if (f["id"] in ids and f["sinif"] == "metin" and f.get("dogrulama") == "dogrulandi"
                and target(f) == key and (f.get("doc_id") or "").strip() and (f.get("kanit_alintisi") or "").strip()):
            out.append({"id": f["id"], "doc_id": f["doc_id"].strip(), "alinti": f["kanit_alintisi"].strip()})
    return out


def trace_ids(ws: Workspace, t: dict | None, js: dict | None = None) -> list[str]:
    """Metnin bu denetime ait düzeltme izindeki bulgu kimlikleri (yoksa boş)."""
    js = js if js is not None else load(ws)
    dz = (t or {}).get("duzeltme") or {}
    return list(dz.get("bulgular") or []) if js and dz.get("denetim") == js.get("id") else []


def alinti_bolumu(src, key: str, ids) -> str | None:
    """Yazım paketine eklenen DENETİM KANIT ALINTILARI bölümü (temel istemin dışında: istem özeti değişmez).
    Yalnız ölçütün kanıt listesindeki belgeler (atıf yapılabilir); alıntı belgede (parçada) bulunmalı."""
    rows = augment_evidence(src, key, [{"no": r["kanit_no"], "doc_id": r.get("doc_id", ""),
                                         "alintilar": [{"alinti": q} for q in r["alintilar"]]}
                                        for r in src.index.get(key, [])], ids)
    L = []
    for e in rows:
        for q in e["alintilar"]:
            if not q.get("denetim"):
                continue                 # kanıtın kendi alıntısı zaten KANITLAR'da
            L.append(f"- [{e['no']}] «{q['alinti']}»" + (f"\n  bağlam: «{q['baglam']}»" if q.get("baglam") else ""))
    if not L:
        return None
    return "\n".join(["DENETİM KANIT ALINTILARI (bağımsız denetçinin kanıt alıntıları; kod belgede doğruladı. Bu "
                      "bilgiler ilgili kanıtın alıntısı sayılır, atıf yapılabilir; yalnız alıntının gösterdiği kadarını "
                      "yaz)", *L])


def augment_evidence(src, key: str, ev: list[dict], ids) -> list[dict]:
    """Kanıt bloklarına (Sources.evidence biçimi) denetçinin doğrulanmış alıntılarını ekler: belge kanıt
    listesinde ve alıntı (birleşik belgede o parçanın) metninde bulunmalı. Eklenen alıntı `denetim: True`."""
    from bidr.write import sources as S
    qs = kanit_alintilari(src.ws, key, ids)
    if not qs or not getattr(src, "verify", None):
        return ev
    out = []
    for e in ev:
        mine = [q for q in qs if q["doc_id"] == e.get("doc_id")]
        if not mine:
            out.append(e)
            continue
        txt = src.doc_text(e["doc_id"])
        row = next((r for r in src.index.get(key, []) if r["kanit_no"] == e["no"]), None)
        doc = (getattr(src, "docs", {}) or {}).get(e["doc_id"]) or {}
        if row is not None:
            txt, _ = S.part_scope(txt, doc.get("parcalar") or [], row["alintilar"], src.verify)
        have = {_norm(q["alinti"]) for q in e.get("alintilar") or []}
        add = []
        for q in mine:
            if _norm(q["alinti"]) in have:
                continue
            ctx = S.evidence_context(txt, [q["alinti"]], src.verify)
            if ctx and ctx[0].get("alinti_belgede"):
                have.add(_norm(q["alinti"]))
                add.append({**ctx[0], "denetim": q["id"]})
        out.append({**e, "alintilar": [*(e.get("alintilar") or []), *add[:4]]} if add else e)
    return out


def duzeltme(ws: Workspace, key: str, t: dict | None) -> tuple[str | None, dict | None]:
    """Yazım/yön paketi için: (istem bölümü ya da None, metin kaydına geçecek `duzeltme` izi ya da None).
    Bekleyen not yoksa önceki iz (bu denetimin) taşınır: girdisi değişip yeniden yazılan metin düzeltilmiş
    sayılmaya devam eder."""
    js = load(ws)
    if not js:
        return None, None
    prev = (t or {}).get("duzeltme") or {}
    carry = prev if prev.get("denetim") == js.get("id") else None
    fs = notes(ws, key, js, t)
    if not fs:
        return None, carry
    ids = sorted(set((carry or {}).get("bulgular") or []) | {f["id"] for f in fs})
    return section(ws, key, fs, t), {"denetim": js["id"], "tur": js["tur"], "bulgular": ids}


def duzelt_acik(ws: Workspace) -> list[str]:
    """İlk turun düzeltmesinde açık kalan işler (ikinci denetimden önce bitmeli)."""
    js = load(ws)
    if not js or int(js.get("tur") or 1) >= 2:
        return []
    st = statuses(ws, js)
    out = []
    n = sum(1 for d, _ in st.values() if d == "duzeltilecek")
    if n:
        out.append(f"{n} metin bulgusu düzeltilmedi")
    n = sum(1 for d, _ in st.values() if d == "karar_bekliyor")
    if n:
        out.append(f"{n} bulgu bölüm kararı bekliyor")
    od_wait = [f["olcut"] for f in js.get("bulgular") or []
               if f["sinif"] == "od" and notes(ws, f["olcut"], js) and st.get(f["id"]) == ("kabul", "")]
    if od_wait:
        out.append(f"{len(od_wait)} kabul edilen OD metne işlenmedi")
    k = kanit_ciftleri(ws.root)
    if k:
        out.append(f"{len(k)} kabul edilen belge önerisi ikinci aramada bekliyor")
    return out


# -- insan raporu ---------------------------------------------------------------------------------------

DURUM_AD = {"duzeltilecek": "düzeltilecek", "duzeltildi": "düzeltildi", "karar_bekliyor": "bölüm kararı bekliyor",
            "kabul": "kabul edildi", "ret": "reddedildi", "dogrulanamadi": "doğrulanamadı", "bilgi": "bilgi"}


def write_md(ws: Workspace, v: dict) -> Path:
    oz = v.get("ozet") or {}
    L = [f"# Raporun kör denetimi (tur {v.get('tur')})", "",
         f"> İç ölçüm. {v.get('aciklama', ACIKLAMA)}", "",
         f"Zaman: {v.get('zaman')} · denetçi: {v.get('model')}", "",
         "Ölçek: " + " · ".join(f"{k} {x}" for k, x in (v.get("olcek") or OLCEK).items()), "",
         "## Özet", "",
         f"- Ölçüt puanı ortalaması: {oz.get('ortalama')}",
         f"- Yön hücreleri ortalaması: {oz.get('yon_ortalama')}",
         f"- Cümle etiketleri: D {oz.get('D')} · K {oz.get('K')} · U {oz.get('U')}",
         "- Bulgular: " + ", ".join(f"{k} {n}" for k, n in (oz.get("bulgu") or {}).items()), ""]
    if v.get("karar_bekleyen_sayisi"):
        L[-1:-1] = [f"- Bölüm kararını bekleyen öneri: {v['karar_bekleyen_sayisi']} (OD/kanıt; hattı tutmaz, rapor "
                    "tamamlandı sayılır; kabul edilen OD küçük bir düzeltme turu açar)"]
    kar = v.get("karsilastirma")
    if kar:
        L += ["## Önce / sonra", "",
              f"Ortalama: {kar['ortalama']['once']} → {kar['ortalama']['sonra']} (tur {kar['onceki_tur']} → "
              f"{v.get('tur')})", "", "| Ölçüt | Önce | Sonra |", "|---|---|---|"]
        L += [f"| {r['olcut']} | {r['once'] if r['once'] is not None else '—'} | {r['sonra']} |" for r in kar["olcutler"]]
        L.append("")
    L += ["## Ölçütler", "", "| Ölçüt | Raporun OD'si | Denetçinin OD görüşü | Kanıt | D/K/U | Puan | Gerekçe |",
          "|---|---|---|---|---|---|---|"]
    for r in v.get("olcutler") or []:
        g = " ".join(str(r.get("gerekce") or "").split()).replace("|", "/")
        L.append(f"| {r['olcut']} | {r['rapor_od'] or '—'} | {r['denetci_od']} | {r['kanit_sayisi']} | "
                 f"{r['D']}/{r['K']}/{r['U']} | {r['puan']} | {g} |")
    L += ["", "## Güçlü / gelişmeye açık yön hücreleri", "", "| Alan | Hücre | Puan | Sorun |", "|---|---|---|---|"]
    for r in v.get("yonler") or []:
        s = " ".join(str(r.get("sorun") or "").split()).replace("|", "/")
        L.append(f"| {r['alan']} | {'güçlü' if r['hucre'] == 'guclu' else 'gelişmeye açık'} | {r['puan']} | {s} |")
    groups = (("metin", "Metin düzeltmeleri (kendiliğinden yapılır ve yeniden doğrulanır)"),
              ("od", "OD önerileri (bölüm kararı)"), ("kanit", "Kullanılmamış belge önerileri (bölüm kararı)"))
    for sinif, head in groups:
        fs = [f for f in v.get("bulgular") or [] if f["sinif"] == sinif and f.get("durum") != "dogrulanamadi"]
        L += ["", f"## {head}", ""]
        if not fs:
            L.append("Yok.")
        for f in fs:
            where = f["olcut"] or f"{f['alan']} yönleri"
            s = f"- **{f['id']}** ({where}; {TUR_ADLARI.get(f['tur'], f['tur'])}; {DURUM_AD.get(f.get('durum'), f.get('durum'))})"
            if f.get("alinti"):
                s += f" — «{f['alinti']}»"
            if f.get("belge_adi"):
                s += f" — belge: {f['belge_adi']}"
            s += f" — {f['aciklama']}"
            if f.get("oneri"):
                s += f" — öneri: {f['oneri']}"
            if f.get("karar"):
                s += f" — karar: {f['karar']['karar']}" + (f" ({f['karar']['not']})" if f["karar"].get("not") else "")
            L.append(s)
    bad = [f for f in v.get("bulgular") or [] if f.get("durum") == "dogrulanamadi"]
    if bad:
        L += ["", "## Doğrulanamayan bulgular (işlenmedi)", ""]
        L += [f"- {f['id']} — {f.get('dogrulama_nedeni')}: «{f.get('alinti') or f.get('kanit_alintisi')}»" for f in bad]
    p = ws.root / OUT_MD
    p.write_text("\n".join(L) + "\n", encoding="utf-8")
    return p
