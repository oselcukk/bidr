"""`bidr write prepare|apply`: ölçüt açıklama metinleri (ajan modu) → `texts/<ölçüt>.json`.

prepare: kanıtı olan her ölçüt için `work/write/<ölçüt>.json` paketi. Girdiler:
  - `evidence-index.csv` (kanıt no, ad, alıntılar; alıntının belge metnindeki bağlamı),
  - `audit-olcutler.json` (önerilen OD, PUKÖ zinciri, eksik halkalar, notlar),
  - ölçüt tanımı/rubrik (paket verisi), kılavuzun yazım soruları,
  - ölçütün kanıtlarının faaliyet özeti (`faaliyetler.json`, `bidr faaliyet`: faaliyet adı,
    aşamalar ve hangi kanıtın hangi aşama olduğu, "yalnız duyuru" işareti); istem kuralı:
    "düzenlenmiştir/gerçekleştirilmiştir" yalnız gerçekleşmesi kanıtlı faaliyet için,
  - isteğe bağlı: geçen yılın aynı ölçüt metni (`--onceki` ya da config.yaml
    `rapor.onceki_rapor`: FR-0833 docx'i ya da `<ölçüt>.txt` klasörü) ve komisyon bilgisi
    (`rapor-notlari.yaml`).
apply: şema + kod denetimi (bidr/write/text.py: her cümlede atıf, atıf listede mi, OD aşımı,
yasak ifade, uydurma gelecek vaadi). Geçemeyen cevap yazılmaz (GECERSIZ.md); geçen metin
`texts/<ölçüt>.json` olur, `durum: taslak` (doğrulama `bidr verify`).

Yeniden yazım döngüsü (`prepare --reddedilenler`): `bidr verify`'ın reddettiği her metin için
yeni paket; istemin sonuna doğrulayıcının cümle bazlı gerekçesi ve reddedilen metin eklenir
(doğrulayıcının paketi yazara verilmez, yalnız kararı ve gerekçesi: cümle bazlı, soru bazlı
— beş soru denetiminin `uydurma_suphesi` — ve kod denetimi gerekçelerinin hepsi). Tur sayısı metinde
(`tur`) tutulur; `rapor.yeniden_yazim_siniri` (vars. 2) turdan sonra reddedilen ölçüt "insan
gerekli" olur (`bidr verify karar … cikar|tekrar`, bkz. bidr/verify/run.py).
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

from bidr.common import Workspace, read_jsonl
from bidr.criteria.loader import load_criteria
from bidr.criteria.model import id_key

from . import packages as K
from . import sources as S
from . import text as T

TASK = "write_criterion"
STAGE = "write"
TEXTS = "texts"
HALKA = {"planla": "planlama", "uygula": "uygulama", "kontrol_et": "kontrol (izleme/ölçme)",
         "onlem_al": "önlem alma (iyileştirme)", "ozgun": "özgün uygulama"}
GUIDE = Path(__file__).resolve().parents[1] / "data" / "criteria" / "guide.yaml"
RULE = ("İstemdeki kurallara uy: her cümle `[n_ODk]` atfı taşır, yalnız kanıtta olanı yaz, "
        "önerilen OD'nin üstünde olgunluk dili kullanma, gelecek vaadi uydurma.")


class Backend:
    """`bidr.llm` arayüzü; testler sahtesini verir."""
    NAMES = ("render_task", "validate_output", "verify_quote")

    def __init__(self, **fns):
        bad = set(fns) - set(self.NAMES)
        if bad:
            raise TypeError(f"bilinmeyen işlev: {bad}")
        self._fns = fns

    def __getattr__(self, name):
        if name in Backend.NAMES:
            f = self.__dict__["_fns"].get(name)
            if f is None:
                import bidr.llm as llm
                f = getattr(llm, name)
            return f
        raise AttributeError(name)


def task_version(name: str = TASK) -> str:
    from bidr.llm import load_task
    return str(load_task(name).version)


def texts_dir(ws: Workspace) -> Path:
    return ws.root / TEXTS


def work_dir(ws: Workspace, stage: str = STAGE) -> Path:
    return ws.root / "work" / stage


# -- bağlam ---------------------------------------------------------------------------------

class Sources:
    """Bir çalışma alanının yazım/doğrulama girdileri (salt okunur)."""

    def __init__(self, ws_root: Path, *, index: Path | None = None, audit: Path | None = None,
                 onceki: str | Path | None = None, notes: Path | None = None, verify=None):
        self.ws = Workspace(Path(ws_root))
        self.index_path = Path(index) if index else self.ws.root / S.INDEX
        self.audit_path = Path(audit) if audit else self.ws.root / S.AUDIT
        if not self.index_path.exists():
            raise FileNotFoundError(f"{S.INDEX} yok: {self.index_path} (önce `file` aşaması)")
        if not self.audit_path.exists():
            raise FileNotFoundError(f"{S.AUDIT} yok: {self.audit_path} (önce `bidr audit`)")
        self.index = S.load_index(self.index_path)
        self.audit = S.load_audit(self.audit_path)
        src = onceki if onceki is not None else S.configured_previous(self.ws.root)
        self.previous, self.previous_name = S.load_previous(src) if src else ({}, None)
        self.notes = S.load_notes(Path(notes) if notes else self.ws.root / S.NOTES)
        self.cs = load_criteria()
        self.verify = verify
        self.docs = ({r["doc_id"]: r for r in read_jsonl(self.ws.documents) if r.get("doc_id")}
                     if self.ws.documents.exists() else {})
        self._texts: dict[str, str | None] = {}
        self.faaliyetler = load_activities(self.ws.root)
        self.donem = period_of(self.ws.root)
        self.birim = S.unit_name(self.ws.root)[0]

    def doc_text(self, did: str) -> str | None:
        if did not in self._texts:
            p = self.ws.text_path(did) if did else None
            self._texts[did] = p.read_text(encoding="utf-8", errors="replace") if p and p.exists() else None
        return self._texts[did]

    def od(self, olcut: str) -> int:
        a = self.audit.get(olcut) or {}
        return int(a.get("od") or 1)

    def index_nos(self, olcut: str) -> set[str]:
        return {r["kanit_no"] for r in self.index.get(olcut, [])}

    def evidence(self, olcut: str, only: set[str] | None = None) -> list[dict]:
        """Kanıtlar, alıntı bağlamıyla (paket ve doğrulama için)."""
        out = []
        for r in self.index.get(olcut, []):
            if only is not None and r["kanit_no"] not in only:
                continue
            doc = self.docs.get(r.get("doc_id")) or {}
            txt = self.doc_text(r.get("doc_id"))
            # birleşik belgede pencere alıntının parçasıyla sınırlı (başka parçanın bilgisi kanıta mal edilmesin)
            part = None
            if self.verify:
                txt, part = S.part_scope(txt, doc.get("parcalar") or [], r["alintilar"], self.verify)
            cov = S.quote_spans(txt, r["alintilar"], self.verify) if self.verify else []
            # kurum geneli düzenlemenin dönem bilgisi künye tarihidir; yalnız birime ait belgeye eklenir
            ext = "kurum_geneli" not in (r.get("isaretler") or "")
            out.append({"no": r["kanit_no"], "ad": r.get("ad", ""), "dosya": r.get("dosya", ""),
                        "doc_id": r.get("doc_id", ""), "od": r.get("od"), "yuvalar": r["yuvalar"],
                        "belge_turu": doc.get("doc_type_etiket") or doc.get("doc_type") or "",
                        "tarih": (part or {}).get("tarih") or doc.get("tarih") or "",
                        "donem_ici": S.period_snippets(txt, self.donem, cov) if ext else [],
                        "bolum_verisi": S.unit_value_snippets(txt, self.birim),
                        "konu": S.topic_snippets(txt, self._description(olcut), cov) if ext else [],
                        "alintilar": S.evidence_context(txt, r["alintilar"], self.verify)})
        return out

    def _description(self, olcut: str) -> str:
        try:
            s = self.cs.get(olcut)
        except KeyError:
            return ""
        return " ".join([s.title, *s.description])

    def gaps(self, olcut: str) -> list[str]:
        """Eksik halkalar ve notlar (insan okur; metne değil `eksikler` alanına)."""
        a = self.audit.get(olcut) or {}
        out = []
        for e in a.get("eksik") or []:
            yv = "; ".join(y["yuva"] for y in e.get("yuvalar") or [])
            out.append(f"OD{a.get('sonraki_od')} için {HALKA.get(e['halka'], e['halka'])} kanıtı eksik: "
                       f"{e.get('gereken', '')}" + (f" (yuva: {yv})" if yv else ""))
        out += [str(n) for n in a.get("notlar") or []]
        return out

    def previous_text(self, olcut: str) -> str:
        p = self.previous.get(olcut) or {}
        if not p.get("aciklama"):
            return "yok"
        s = "Açıklamalar:\n" + p["aciklama"]
        if p.get("kanitlar"):
            s += "\n\nKanıtlar:\n" + p["kanitlar"]
        return s

    def activities(self, olcut: str) -> list[dict]:
        """Ölçütün kanıtlarının bağlı olduğu faaliyet kayıtları (`faaliyetler.json`); her birinde
        aşama → bu ölçütün kanıt numaraları (kanıtı bu ölçütte olmayan aşama belgesi `None`)."""
        if not self.faaliyetler:
            return []
        no_of: dict = {}  # bölünmüş birleşik belgenin parçaları ayrı numara alır: belge → numaraların hepsi
        for r in self.index.get(olcut, []):
            if r.get("doc_id") and r["kanit_no"] not in no_of.setdefault(r["doc_id"], []):
                no_of[r["doc_id"]].append(r["kanit_no"])
        out = []
        for f in self.faaliyetler:
            ids = {b.get("doc_id") for b in f.get("belgeler") or []}
            if not ids & set(no_of):
                continue
            asm = {a: [n for d in ds for n in (no_of.get(d) or [None])]
                   for a, ds in (f.get("asamalar") or {}).items()}
            out.append({"id": f.get("id"), "ad": f.get("ad") or "", "tarih": f.get("tarih"),
                        "durum": f.get("durum"), "yalniz_duyuru": bool(f.get("yalniz_duyuru")),
                        "asamalar": asm, "eksik": list(f.get("eksik") or [])})
        return out

    def notes_text(self, olcut: str) -> str:
        n = self.notes.get(olcut) or []
        return "\n".join(f"- {x}" for x in n) if n else "yok"


# -- istem girdileri ---------------------------------------------------------------------------

def render_criterion(cs, olcut: str, od: int | None = None) -> str:
    s = cs.get(olcut)
    lines = [f"{s.id} {s.title}"]
    if od is not None:
        lines.append(f"Önerilen OD: {od}")
    lines.append("Tanım:")
    lines += [f"- {d}" for d in s.description]
    lines.append("Rubrik:")
    lines += [f"{k}: {v}" for k, v in sorted(s.rubric.items())]
    return "\n".join(lines)


def render_od(a: dict, gaps: list[str]) -> str:
    z = a.get("zincir") or {}
    zz = ", ".join(f"{HALKA.get(k, k)}: {v.get('durum')} ({v.get('eslesme', 0)} eşleşme)" for k, v in z.items())
    lines = [f"Önerilen OD: {a.get('od', 1)} — metin bu düzeyin üstünde olgunluk iddia etmez.",
             f"PUKÖ zinciri: {a.get('zincir_kisa', '')}" + (f" ({zz})" if zz else "")]
    if gaps:
        lines.append("Eksikler ve notlar (metne yazılmaz; ayrı listelenir):")
        lines += [f"- {g}" for g in gaps]
    return "\n".join(lines)


def render_evidence(ev: list[dict], cs, donem: int | None = None) -> str:
    """Kanıt blokları. `donem` verilirse (yazım paketi) başa dönem içi kaydı olan kanıtların listesi
    konur: bu kayıtlar metinde önce anlatılır (kod denetimi `donem_ici_atlandi`)."""
    blocks = []
    if donem:
        nos = [e["no"] for e in ev if T.dated_in_period(e.get("donem_ici") or [], donem)]
        if nos:
            blocks.append(f"DÖNEM İÇİ KAYDI OLAN KANITLAR ({donem}): " + ", ".join(f"[{n}]" for n in nos)
                          + " — bu kanıtların \"dönem içi bilgi\" satırlarındaki kayıtlar metinde ÖNCE anlatılır; "
                            "bu kanıtla yalnız dönem dışı kayıt anlatan metni kod reddeder.")
    for e in ev:
        lines = [f"[{e['no']}] {e['ad']}"]
        info = ", ".join(x for x in (f"tür: {e['belge_turu']}" if e["belge_turu"] else "",
                                     f"tarih: {e['tarih']}" if e["tarih"] else "") if x)
        if info:
            lines.append(f"  {info}")
        # önce bölümün kendi gösterge verisi, belgedeki dönem içi kayıtlar ve ölçütün sorduğu bilgi
        for i, x in enumerate(e.get("bolum_verisi") or [], 1):
            lines.append(f"  bölümün kendi verisi {i}: «{x}»")
        for i, x in enumerate(e.get("donem_ici") or [], 1):
            lines.append(f"  dönem içi bilgi {i}: «{x}»")
        for i, x in enumerate(e.get("konu") or [], 1):
            lines.append(f"  ölçütle ilgili bilgi {i}: «{x}»")
        for y in e["yuvalar"]:
            try:
                lines.append(f"  yuva {y}: {cs.get_slot(y).text}")
            except KeyError:
                lines.append(f"  yuva {y}")
        for i, q in enumerate(e["alintilar"], 1):
            lines.append(f"  alıntı {i}: «{q['alinti']}»")
            if q.get("baglam"):
                lines.append(f"  bağlam {i}: «{q['baglam']}»")
            elif q.get("alinti_belgede") is False:
                lines.append(f"  (alıntı belge metninde bulunamadı)")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def period_of(ws_root: Path) -> int | None:
    """config.yaml `bidr.donem` (rapor yılı; yoksa None)."""
    from bidr.init.config import load_section
    try:
        v = (load_section(Path(ws_root)) or {}).get("donem")
        return int(v) if v else None
    except (TypeError, ValueError, OSError):
        return None


FAALIYETLER = "faaliyetler.json"
GERCEKLESME = ("gerceklesme", "katilim", "degerlendirme", "iyilestirme")


def load_activities(ws_root: Path) -> list[dict]:
    """`faaliyetler.json` kayıtları (yoksa ya da okunamazsa boş)."""
    p = Path(ws_root) / FAALIYETLER
    try:
        return list(json.loads(p.read_text(encoding="utf-8")).get("faaliyetler") or []) if p.exists() else []
    except (OSError, ValueError, AttributeError):
        return []


def render_activities(acts: list[dict]) -> str:
    """Yazım istemindeki FAALİYETLER bölümü."""
    if not acts:
        return "yok (bu ölçütün kanıtları bir faaliyet kaydına bağlı değil)"
    blocks = []
    for f in acts:
        kanitli = not f["yalniz_duyuru"] and f["durum"] != "gerceklesme_kanitsiz"
        head = f"{f['ad']}" + (f" ({f['tarih']})" if f.get("tarih") else "")
        lines = [head,
                 "  durum: " + ("gerçekleşmesi kanıtlı" if kanitli else
                                "YALNIZ DUYURU — gerçekleşmesi kanıtlı değil; 'düzenlenmiştir/gerçekleştirilmiştir' "
                                "denemez, yalnız 'duyurulmuştur/planlanmıştır'")]
        parts = []
        for a, nos in f["asamalar"].items():
            have = [f"[{n}]" for n in nos if n]
            other = sum(1 for n in nos if not n)
            parts.append(f"{a}: " + ", ".join(have + ([f"{other} belge bu ölçütün kanıtı değil"] if other else [])))
        lines.append("  aşamalar: " + "; ".join(parts))
        if kanitli and not any(n for a in GERCEKLESME for n in f["asamalar"].get(a) or []):
            lines.append("  not: gerçekleşme belgesi bu ölçütün KANITLAR listesinde yok; gerçekleşme iddiası "
                         "atıf yapılabilecek bir kanıta dayanmaz")
        if f.get("eksik"):
            lines.append("  eksik: " + ", ".join(f["eksik"]))
        blocks.append("\n".join(lines))
    return "\n".join(blocks)


def writing_questions() -> str:
    g = yaml.safe_load(GUIDE.read_text(encoding="utf-8"))
    for sec in g.get("sections") or []:
        if sec.get("section") == "Açıklama Metni Yazımı":
            return "\n".join(f"- {t}" for t in sec["text"][1:])
    return "-"


def hitap_for(profile: str | None, override: str | None = None) -> str:
    if override:
        return override
    return "Bölümümüzde" if (profile or "akademik_bolum") == "akademik_bolum" else "Birimimizde"


def write_inputs(src: Sources, olcut: str, hitap: str) -> tuple[dict, dict]:
    a = src.audit.get(olcut) or {"od": 1}
    gaps = src.gaps(olcut)
    ev = src.evidence(olcut)
    acts = src.activities(olcut)
    inputs = {"hitap": hitap, "olcut": render_criterion(src.cs, olcut),
              "od_bilgisi": render_od(a, gaps), "kanitlar": render_evidence(ev, src.cs, src.donem),
              "onceki_metin": src.previous_text(olcut), "komisyon_bilgisi": src.notes_text(olcut),
              "yazim_sorulari": writing_questions(), "faaliyetler": render_activities(acts)}
    meta = {"olcut": olcut, "od_onerisi": src.od(olcut), "eksikler": gaps,
            "kanitlar": [{"no": e["no"], "ad": e["ad"], "dosya": e["dosya"], "doc_id": e["doc_id"]} for e in ev],
            "komisyon": bool(src.notes.get(olcut)), "onceki": src.previous_name if olcut in src.previous else None,
            "faaliyetler": [{"id": f["id"], "ad": f["ad"], "yalniz_duyuru": f["yalniz_duyuru"]} for f in acts],
            "donem": src.donem, "donem_ici": in_period_nos(ev, src.donem)}
    return inputs, meta


def in_period_nos(ev: list[dict], donem: int | None) -> list[str]:
    """Belgesinde dönem içi tarihli kayıt bulunan kanıt numaraları (kod denetimi `donem_ici_atlandi`)."""
    return [e["no"] for e in ev if donem and T.dated_in_period(e.get("donem_ici") or [], donem)]


# -- kaynak yolları ----------------------------------------------------------------------------

SOURCES_FILE = "kaynaklar.json"      # work/write/: prepare'in kullandığı girdi yolları


def _rel(ws_root: Path, p) -> str | None:
    """Kayda yazılacak yol: çalışma alanının içindeyse ona göre göreli (klasör kopyalanır ya da
    taşınırsa kopyanın kendi dosyasını gösterir), değilse mutlak."""
    if not p:
        return None
    p, root = Path(p).expanduser().resolve(), Path(ws_root).resolve()
    return p.relative_to(root).as_posix() if root == p or root in p.parents else str(p)


def save_source_paths(src: "Sources", onceki, notes) -> None:
    d = work_dir(src.ws)
    d.mkdir(parents=True, exist_ok=True)
    root = src.ws.root
    rec = {"index": _rel(root, src.index_path), "audit": _rel(root, src.audit_path),
           "onceki": _rel(root, onceki), "notlar": _rel(root, notes)}
    (d / SOURCES_FILE).write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")


def _saved_path(ws_root: Path, v) -> str | None:
    """Kayıttaki yol → kullanılacak yol. Göreli yol çalışma alanına göredir. Eski kayıttaki mutlak
    yol başka bir çalışma alanının (config.yaml'ı olan klasörün) kendi dosyasını gösteriyorsa bu
    çalışma alanı o klasörün kopyasıdır: kopyanın aynı adlı dosyası kullanılır. Gerçek veri
    2026-11-21: kopyada yeniden dosyalanan dizin yerine asıl çalışma alanının dizini okunuyor,
    write_tamam kanıt numarası değişen metinleri eski saymıyordu."""
    if not v:
        return None
    root = Path(ws_root).resolve()
    p = Path(v).expanduser()
    if not p.is_absolute():
        return str(root / p)
    if (p.name in (S.INDEX, S.AUDIT) and p.parent != root and (p.parent / "config.yaml").exists()
            and (root / "config.yaml").exists() and (root / p.name).exists()):
        return str(root / p.name)
    return str(p)


def source_paths(ws_root: Path, *, index=None, audit=None, onceki=None, notes=None) -> dict:
    """Komut satırında verilmeyen yollar son `write prepare`'in kaydından (yoksa varsayılan)."""
    f = work_dir(Workspace(Path(ws_root))) / SOURCES_FILE
    saved = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    return {"index": index or _saved_path(ws_root, saved.get("index")),
            "audit": audit or _saved_path(ws_root, saved.get("audit")),
            "onceki": onceki if onceki is not None else _saved_path(ws_root, saved.get("onceki")),
            "notes": notes or _saved_path(ws_root, saved.get("notlar"))}


# -- prepare / apply ------------------------------------------------------------------------------

def _criteria(src: Sources, only: list[str] | None) -> tuple[list[str], list[str]]:
    """(kanıtı olan ölçütler, kanıtsız ölçütler) — `only` verilirse onunla sınırlı."""
    have = set(src.index)
    pool = set(only) if only else have | set(src.audit)
    yes = sorted((c for c in pool if c in have), key=id_key)
    no = sorted((c for c in pool if c not in have), key=id_key)
    return yes, no


def load_text(ws: Workspace, olcut: str) -> dict | None:
    p = texts_dir(ws) / f"{olcut}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def girdi_sha(rows: list[dict], od: int) -> str:
    """Metnin dayandığı girdilerin özeti: ölçütün kanıt listesi (no, doc_id) ve önerilen OD.
    Değişirse metin eskir (write_tamam)."""
    k = sorted((r["kanit_no"], r.get("doc_id", "")) for r in rows)
    return K.sha(json.dumps({"k": k, "od": int(od)}, ensure_ascii=False))


def inputs_sha(src: Sources, olcut: str) -> str:
    return girdi_sha(src.index.get(olcut, []), src.od(olcut))


DEFAULT_LIMIT = 2


def rewrite_limit(ws_root: Path) -> int:
    """config.yaml `rapor.yeniden_yazim_siniri` (vars. 2)."""
    try:
        return max(0, int(S.rapor_section(Path(ws_root)).get("yeniden_yazim_siniri", DEFAULT_LIMIT)))
    except (TypeError, ValueError):
        return DEFAULT_LIMIT


def rejection_section(t: dict, rec: dict | None, tur: int, limit: int) -> str:
    """Yeniden yazım paketinin istemine eklenen bölüm: doğrulayıcının bütün gerekçeleri — cümle
    bazlı, soru bazlı (beş soru denetiminin `uydurma_suphesi`) ve kod denetimi; kayıttaki ya da
    metnin `dogrulama.gerekce` listesinde olup bunlarla gösterilmeyen satırlar da eklenir."""
    rec = rec or {}
    L = [f"DOĞRULAMADA REDDEDİLDİ — YENİDEN YAZIM (tur {tur}/{limit})",
         "Bu ölçüt için daha önce yazılan metin bağımsız doğrulamada reddedildi. Metni yukarıdaki "
         "kurallarla ve yalnız KANITLAR listesine dayanarak yeniden yaz:",
         "- reddedilen cümleyi kanıtın gerçekten gösterdiği kadarına indir ya da çıkar; kanıtı olmayan "
         "iddiayı başka sözcüklerle yeniden kurma;",
         "- uydurma şüphesi taşıyan soruyu (izleme, iyileştirme vb.) kanıtsız genel ifadeyle doldurma: "
         "kanıt o soruyu somut olarak cevaplamıyorsa o soruya ilişkin cümleyi çıkar (cevapsız kalması doğrudur);",
         "- desteklendiği söylenen cümleleri koruyabilirsin; yeni iddia ekleme;",
         "- doğrulayıcıyı ikna etmeye çalışan açıklama yazma; cevap biçimi aynı.", ""]
    shown: set[str] = set()
    rows = [r for r in rec.get("cumleler") or [] if r.get("karar") != "destekleniyor"]
    if rows:
        L.append("Doğrulayıcının desteklemediği cümleler (yer, karar, gerekçe):")
        for r in rows:
            L.append(f"- {r['yer']} ({r['karar']}): «{r.get('metin', '')}» — {r.get('gerekce', '')}")
            shown.add(f"{r['yer']} ({r['karar']}): {r.get('gerekce', '')} — «{r.get('metin', '')}»")
    qs = [q for q in ((rec.get("soru_kapsami") or t.get("soru_kapsami") or {}).get("sorular") or [])
          if q.get("durum") == "uydurma_suphesi"]
    if qs:
        L.append("Beş soru denetimi — kanıtsız genel ifadeyle doldurulan sorular (soru, yerler, gerekçe):")
        for q in qs:
            yer = ", ".join(q.get("yerler") or [])
            L.append(f"- soru {q['soru']} «{q.get('baslik', '')}» (uydurma_suphesi; {yer}): {q.get('gerekce', '')}")
            shown.add(f"soru {q['soru']} (uydurma_suphesi; {yer}): {q.get('gerekce', '')}")
    kod = rec.get("kod_denetimi") or []
    if kod:
        L.append("Kod denetiminin bulduğu sorunlar:")
        for i in kod:
            L.append(f"- {i.get('yer', '-')} {i.get('kod', '')}: {i.get('ayrinti', '')}")
            shown.add(f"{i.get('yer', '-')} {i.get('kod', '')}: {i.get('ayrinti', '')}")
    rest: list[str] = []
    for g in [*(rec.get("gerekce") or []), *((t.get("dogrulama") or {}).get("gerekce") or [])]:
        g = str(g)
        if g not in shown and g not in rest:
            rest.append(g)
    if rest:
        L.append("Doğrulama gerekçeleri" + (" (yukarıdakilere ek)" if shown else "") + ":")
        L += [f"- {g}" for g in rest]
    if not shown and not rest:
        L.append("- (gerekçe kaydı yok)")
    if rec.get("genel"):
        L.append(f"Doğrulayıcının genel notu: {rec['genel']}")
    L += ["", "REDDEDİLEN METİN (yalnız düzeltme için; kanıt değildir)", "<<<"]
    L += [p["metin"] for p in t.get("paragraflar") or []]
    if (t.get("onceki_yila_gore") or "").strip():
        L.append("onceki_yila_gore: " + t["onceki_yila_gore"].strip())
    L.append(">>>")
    return "\n".join(L)


def prepare_rejected(ws_root: Path, *, only: list[str] | None = None, index: Path | None = None,
                     audit: Path | None = None, onceki=None, notes: Path | None = None,
                     hitap: str | None = None, backend: Backend | None = None) -> dict:
    """Doğrulamada reddedilen metinler için yeniden yazım paketleri (bkz. modül belgesi)."""
    from bidr.verify import run as V
    backend = backend or Backend()
    sp = source_paths(ws_root, index=index, audit=audit, onceki=onceki, notes=notes)
    src = Sources(ws_root, index=sp["index"], audit=sp["audit"], onceki=sp["onceki"], notes=sp["notes"],
                  verify=backend.verify_quote)
    _, profile = S.unit_name(src.ws.root)
    h = hitap_for(profile, hitap)
    log = V.load_log(src.ws)
    human = V.load_human(src.ws)
    d = work_dir(src.ws)
    d.mkdir(parents=True, exist_ok=True)
    st = {"paket": 0, "yeni": 0, "insan_gerekli": [], "cikarildi": [], "kanitsiz": [], "tur": {}}
    for c, t in V.rejected(src.ws, log, only=only).items():
        if V.excluded(t, human):
            st["cikarildi"].append(c)
            continue
        if c not in src.index:
            st["kanitsiz"].append(c)
            continue
        tur, lim = int(t.get("tur") or 0), V.limit_for(src.ws, c, human)
        if tur >= lim:
            st["insan_gerekli"].append(c)
            continue
        inputs, meta = write_inputs(src, c, h)
        r = backend.render_task(TASK, inputs)
        base = K.sha(r["prompt"])
        r = {**r, "prompt": r["prompt"] + "\n\n" + rejection_section(t, log.get(c), tur + 1, lim)}
        meta.update({"tur": tur + 1, "temel_istem_sha": base, "girdi_sha": inputs_sha(src, c),
                     "ret": (log.get(c) or {}).get("gerekce") or []})
        st["paket"] += 1
        st["yeni"] += K.write_pkg(d, c, r, meta)
        st["tur"][c] = tur + 1
    st["bekleyen"] = K.write_readme(d, task=TASK, version=task_version(), cmd="write", rule=RULE)
    st["klasor"] = str(d)
    return st


def prepare(ws_root: Path, *, only: list[str] | None = None, redo: bool = False,
            index: Path | None = None, audit: Path | None = None, onceki=None, notes: Path | None = None,
            hitap: str | None = None, backend: Backend | None = None, old_rules: bool = False) -> dict:
    """`old_rules` (`--eski-kurallar`): yalnız yazım görevinin eski sürümüyle yazılmış, girdisi değişmemiş
    ve reddedilmemiş metinleri yeni kuralla yeniden paketler (isteğe bağlı yenileme; bkz. `old_rule_texts`)."""
    backend = backend or Backend()
    src = Sources(ws_root, index=index, audit=audit, onceki=onceki, notes=notes, verify=backend.verify_quote)
    unknown = [c for c in only or [] if c not in src.cs._index]
    if unknown:
        raise KeyError(f"bilinmeyen ölçüt: {', '.join(unknown)}")
    if old_rules:
        if redo:
            raise KeyError("--eski-kurallar ile --redo birlikte kullanılmaz")
        olds = old_rule_texts(src.ws, src.index, src.audit, task_version())
        only = [c for c in olds if not only or c in only]
        if not only:
            return {"paket": 0, "yeni": 0, "zaten_tamam": 0, "kanitsiz": [], "onceki": src.previous_name,
                    "onceki_olcut": 0, "eski_surum": [], "yenilenen": [], "klasor": str(work_dir(src.ws)),
                    "bekleyen": K.write_readme(work_dir(src.ws), task=TASK, version=task_version(), cmd="write",
                                               rule=RULE) if work_dir(src.ws).exists() else 0}
    save_source_paths(src, onceki if onceki is not None else S.configured_previous(src.ws.root), notes)
    _, profile = S.unit_name(src.ws.root)
    h = hitap_for(profile, hitap)
    d = work_dir(src.ws)
    d.mkdir(parents=True, exist_ok=True)
    yes, no = _criteria(src, only)
    st = {"paket": 0, "yeni": 0, "zaten_tamam": 0, "kanitsiz": no, "onceki": src.previous_name,
          "onceki_olcut": sum(c in src.previous for c in yes), "eski_surum": [],
          "yenilenen": list(only) if old_rules else []}
    for c in yes:
        inputs, meta = write_inputs(src, c, h)
        r = backend.render_task(TASK, inputs)
        t = load_text(src.ws, c)
        kay = (t or {}).get("kaynak") or {}
        if (t and not redo and not only and (kay.get("temel_istem_sha") or kay.get("istem_sha")) == K.sha(r["prompt"])
                and str(kay.get("gorev_surumu")) == str(r["version"])):
            st["zaten_tamam"] += 1
            continue
        if t and not redo and not only and old_version_valid(t, str(r["version"]), inputs_sha(src, c)):
            st["eski_surum"].append(c)          # görevin eski sürümüyle yazılmış, girdileri güncel: geçerli
            continue
        gsha = inputs_sha(src, c)
        # doğrulama tur sayacı metnin girdisine bağlıdır: kanıt listesi/OD değişince ya da metin yeni
        # kuralla yenilenince yeni metin baştan sayılır (eski metnin turları yeni metne yük olmaz)
        same = bool(t) and t.get("girdi_sha") == gsha and not old_rules
        meta.update({"tur": int(t.get("tur") or 0) if same else 0, "temel_istem_sha": K.sha(r["prompt"]),
                     "girdi_sha": gsha})
        st["paket"] += 1
        st["yeni"] += K.write_pkg(d, c, r, meta, force=bool(redo and t))
    st["bekleyen"] = K.write_readme(d, task=TASK, version=task_version(), cmd="write", rule=RULE)
    st["klasor"] = str(d)
    return st


def old_rule_texts(ws: Workspace, index: dict, audit: dict, version: str | None = None) -> list[str]:
    """Yazım görevinin eski sürümüyle (eski yazım kuralıyla) yazılmış, girdisi (kanıt listesi, OD)
    değişmemiş ve doğrulamada reddedilmemiş metinler: geçerlidir; yeni kuralla yeniden yazmak isteğe
    bağlıdır (`bidr write prepare --eski-kurallar`)."""
    version = version or task_version()
    out = []
    for c in sorted(index, key=id_key):
        t = load_text(ws, c)
        if not t or t.get("durum") == "reddedildi":
            continue
        od = int((audit.get(c) or {}).get("od") or 1)
        if old_version_valid(t, version, girdi_sha(index[c], od)):
            out.append(c)
    return out


def old_version_valid(t: dict, version: str, cur_inputs_sha: str) -> bool:
    """Görevin eski sürümüyle yazılmış metin geçerli kalır (yeniden paketlenmez) — kanıt listesi ve
    OD değişmediyse (`girdi_sha`; alanı olmayan eski metin de write_tamam'daki gibi güncel sayılır).
    Yeni sürümün kuralıyla yeniden yazmak isteğe bağlı: `write prepare --redo` ya da `--only`."""
    kay = t.get("kaynak") or {}
    if not kay.get("gorev_surumu") or str(kay["gorev_surumu"]) == version:
        return False
    return not t.get("girdi_sha") or t["girdi_sha"] == cur_inputs_sha


def _cited(paragraphs: list[str], onceki: str) -> list[str]:
    seen: list[str] = []
    for r in T.sentence_rows(paragraphs, onceki):
        for c in T.citations(r["metin"]):
            if c not in seen:
                seen.append(c)
    return sorted(seen, key=lambda x: int(x.split("_")[0]))


NUMARA_HARITASI = "numara_haritasi"     # {şimdiki atıf: metnin yazıldığı (doğrulandığı) atıf}


def as_written(s: str, harita: dict | None) -> str:
    """Metindeki atıfları yazıldıkları numaraya geri çevirir (`numara_haritasi`; bkz.
    bidr.file.renumber). Harita birebirdir: ayrı atıflar ayrı kalır."""
    if not harita:
        return s
    hedef = set(harita.values())

    def geri(m) -> str:
        c = f"{m.group(1)}_OD{m.group(2)}"
        if c in harita:
            return f"[{harita[c]}]"
        # haritada olmayan atıf, başka bir atfın yazıldığı numaraya denk geliyorsa ayrı tutulur
        # (birebirlik: atfı başka kanıta çevirmek özeti değiştirir)
        return f"[{c}*]" if c in hedef else f"[{c}]"
    return T.ATIF.sub(geri, s)


def text_sha(t: dict) -> str:
    """Metnin içerik özeti (durum ve doğrulama alanları hariç). Dosyalama yalnız numaraları
    değiştirdiyse (aynı belgeler, aynı kod OD'si; `bidr.file.renumber`) atıflar yazıldıkları
    numarayla özetlenir: kodla yeniden numaralama metnin doğrulamasını ve ona dayanan kayıtları
    (verify, yönler) eskitmez; metinde başka her değişiklik (atfın başka kanıta çevrilmesi dahil)
    özeti değiştirir."""
    h = t.get(NUMARA_HARITASI) or {}
    body = json.dumps({"p": [as_written(p["metin"], h) for p in t.get("paragraflar") or []],
                       "o": as_written(t.get("onceki_yila_gore") or "", h), "od": t.get("od_onerisi")},
                      ensure_ascii=False, sort_keys=True)
    return K.sha(body)


def apply(ws_root: Path, *, model: str = "ajan:belirtilmemis", index: Path | None = None,
          audit: Path | None = None, backend: Backend | None = None) -> dict:
    backend = backend or Backend()
    sp = source_paths(ws_root, index=index, audit=audit)
    src = Sources(ws_root, index=sp["index"], audit=sp["audit"], onceki="", verify=backend.verify_quote)
    d = work_dir(src.ws)
    td = texts_dir(src.ws)
    st = {"islenen": 0, "degismedi": 0, "bekleyen": [], "gecersiz": {}, "eski": []}
    version = task_version()
    for p in K.pkg_paths(d):
        pkg = json.loads(p.read_text(encoding="utf-8"))
        c = pkg["olcut"]
        outp = d / pkg["cikti_dosyasi"]
        if not outp.exists():
            st["bekleyen"].append(c)
            continue
        meta = pkg["meta"]
        old = load_text(src.ws, c)
        okay = old and (old.get("kaynak") or {})
        if okay and okay.get("istem_sha") == pkg["istem_sha"] \
                and okay.get("cevap_sha") == K.sha(outp.read_text(encoding="utf-8")):
            # bu paketin bu cevabı zaten metin oldu (önceki çalıştırmadan kalan paket): write_tamam gibi
            # işlenmiş sayılır, görev sürümü eski olsa da; metnin girdisi sonradan değiştiyse paket değil
            # metin eskidir (prepare)
            if old.get("girdi_sha") and old["girdi_sha"] != inputs_sha(src, c):
                st["eski"].append(c)
            else:
                st["degismedi"] += 1
            continue
        if str(pkg["surum"]) != version:
            st["eski"].append(c)
            continue
        cur = {(r["kanit_no"], r.get("doc_id", "")) for r in src.index.get(c, [])}
        if cur != {(k["no"], k["doc_id"]) for k in meta["kanitlar"]} or src.od(c) != meta["od_onerisi"]:
            st["eski"].append(c)              # kanıt listesi ya da OD paketten sonra değişti
            continue
        raw = outp.read_text(encoding="utf-8")
        out, errs = backend.validate_output(TASK, raw)
        if out is None:
            st["gecersiz"][c] = errs[:5]
            continue
        paras = [x["metin"].strip() for x in out["paragraflar"]]
        onceki = (out.get("onceki_yila_gore") or "").strip()
        issues = T.check_text(paras, onceki, index_nos=src.index_nos(c), od=meta["od_onerisi"],
                              komisyon=meta.get("komisyon", False))
        issues += T.content_issues(paras, onceki, donem=meta.get("donem"), donem_ici=set(meta.get("donem_ici") or []))
        if issues:
            st["gecersiz"][c] = [f"{i['yer']} {i['kod']}: {i['ayrinti']}" for i in issues]
            continue
        cited = _cited(paras, onceki)
        byno = {k["no"]: k for k in meta["kanitlar"]}
        rec = {"olcut": c, "od_onerisi": meta["od_onerisi"], "durum": "taslak",
               "tur": int(meta.get("tur") or 0), "girdi_sha": meta.get("girdi_sha") or inputs_sha(src, c),
               "paragraflar": [{"metin": m, "atiflar": _cited([m], "")} for m in paras],
               "kanitlar": [{"no": n, "ad": byno[n]["ad"], "dosya": byno[n]["dosya"]} for n in cited],
               "eksikler": meta["eksikler"], "onceki_yila_gore": onceki,
               **({"onceki_ret": meta["ret"]} if meta.get("ret") else {}),
               "kaynak": {"model": model, "gorev_surumu": str(pkg["surum"]), "istem_sha": pkg["istem_sha"],
                          "temel_istem_sha": meta.get("temel_istem_sha") or pkg["istem_sha"],
                          "cevap_sha": K.sha(raw), "onceki": meta.get("onceki"), "zaman": K.now()}}
        if old and text_sha(old) == text_sha(rec) and (old.get("kaynak") or {}).get("istem_sha") == pkg["istem_sha"]:
            st["degismedi"] += 1
            continue
        td.mkdir(parents=True, exist_ok=True)
        (td / f"{c}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
        st["islenen"] += 1
    K.write_invalid(d, TASK, st["gecersiz"])
    return st
