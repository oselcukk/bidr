"""render çekirdeği: şablon kopyası + `texts/<olcut>.json` (+ `audit-olcutler.json`) → report.docx.

Şablon dosyasına yazılmaz; çıktı her zaman ayrı bir yoldur. Değişen yerler yalnız:
alt ölçüt bloklarının "Açıklamalar" ve "Kanıtlar" hücreleri, öz değerlendirme işareti
(rubrik hücresi), kapaktaki birim adı / yıl ve (gerekirse) üstbilgideki TASLAK satırı.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from bidr.criteria.extract_docx import W, _ptext

from . import docx_ops as ops
from .template import ACIKLAMA, COVER_STOP, KANIT, find_blocks

# Metni olmayan ölçüt için varsayılan ifade. Gerekçe: kılavuzun "Kapsam" bölümüne göre rapor
# önceki takvim yılıyla sınırlıdır; ifade yalnız bu dönemde *kanıt* bulunamadığını söyler,
# faaliyetin yapılmadığını iddia etmez (bu bir değerlendirme olur), puan da önermez.
# 2025 Matematik raporundaki "Bu kısım için veri bulunmamaktadır." kullanımıyla aynı tonda.
BOS_IFADE = "Bu ölçüt için bu dönemde kanıt bulunamamıştır."
BOS_KANIT = "Bu ölçüt için kanıt bulunmamaktadır."
TASLAK_METNI = "TASLAK — doğrulanmamış metin içerir"
DOGRULANMADI = "[doğrulanmadı]"
GOLGE = "FFE699"
PUAN_ISARETLERI = ("kalin", "golge", "yok")
KANIT_BICIMLERI = ("mat", "kilavuz")
RE_NO = re.compile(r"^(\d+)_OD([1-5])$")
RE_ATIF = re.compile(r"\[(\d+_OD[1-5])\]")
RE_YIL = re.compile(r"^(19|20)\d\d$")
# `[komisyon]`: yazım/doğrulamada cümlenin komisyon bilgisine dayandığını gösteren iç işaret;
# rapora girmez (atıf yerine geçer, okur için anlamı yok).
RE_KOMISYON = re.compile(r"\s*\[komisyon\]")
MANIFEST = ".bidr-render.json"


def clean_text(m: str) -> str:
    """Rapora girecek paragraf: iç işaretler temizlenir, noktalama önü boşluk düzeltilir."""
    m = RE_KOMISYON.sub("", m)
    m = re.sub(r"\s+([.,;:])", r"\1", m)
    return " ".join(m.split())


@dataclass
class Options:
    puan_isareti: str = "kalin"    # kalin (Kimya 2025 usulü) | golge | yok (Matematik/Fizik/MBG usulü)
    kanit_bicimi: str = "mat"      # mat: "1_OD3: ad" | kilavuz: "[1-OD3]. ad"
    bos_ifade: str = BOS_IFADE
    bos_kanit: str = BOS_KANIT
    eksik_notu: bool = True


@dataclass
class Result:
    out: Path
    dolu: list[str] = field(default_factory=list)
    bos: list[str] = field(default_factory=list)
    dogrulanmamis: list[str] = field(default_factory=list)
    reddedildi: list[str] = field(default_factory=list)
    od: dict[str, int] = field(default_factory=dict)
    taslak: bool = False
    kapak: dict[str, str] = field(default_factory=dict)
    uyarilar: list[str] = field(default_factory=list)
    degisen_parcalar: list[str] = field(default_factory=list)
    baglantili: int = 0
    baglantisiz: list[str] = field(default_factory=list)

    def ozet(self) -> dict:
        return {"cikti": str(self.out), "dolu": len(self.dolu), "bos": len(self.bos),
                "dogrulanmamis": self.dogrulanmamis, "reddedildi": self.reddedildi,
                "od_isaretli": len(self.od), "taslak": self.taslak, "kapak": self.kapak,
                "uyari": len(self.uyarilar), "baglantili_kanit": self.baglantili,
                "baglantisiz_kanit": len(self.baglantisiz),
                "degisen_parcalar": self.degisen_parcalar}


def load_texts(d: Path) -> tuple[dict[str, dict], list[str]]:
    out, uy = {}, []
    if not d.is_dir():
        return out, [f"metin klasörü yok: {d} (bütün ölçütler boş ifadeyle doldurulur)"]
    for p in sorted(d.glob("*.json")):
        try:
            t = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            uy.append(f"{p.name}: okunamadı ({e})")
            continue
        cid = t.get("olcut")
        if not cid:
            uy.append(f"{p.name}: 'olcut' alanı yok")
            continue
        if cid in out:
            uy.append(f"{cid}: birden çok metin dosyası; {p.name} atlandı")
            continue
        out[cid] = t
    return out, uy


def load_audit(p: Path | None) -> tuple[dict[str, dict], list[str]]:
    if p is None or not p.exists():
        return {}, [f"audit-olcutler.json yok ({p}); OD önerisi yalnız metinlerden, eksik notu yok"]
    js = json.loads(p.read_text(encoding="utf-8"))
    return {c["olcut"]: c for c in js.get("olcutler") or []}, []


def kanit_parts(k: dict, bicim: str) -> tuple[str, str]:
    """(önek, ad): "1_OD3: " + ad (mat) ya da "[1-OD3]. " + ad (kılavuz)."""
    no, ad = str(k.get("no", "")).strip(), str(k.get("ad", "")).strip()
    if bicim == "kilavuz":
        m = RE_NO.match(no)
        if m:
            return f"[{m.group(1)}-OD{m.group(2)}]. ", ad
    return f"{no}: ", ad


def kanit_line(k: dict, bicim: str) -> str:
    return "".join(kanit_parts(k, bicim))


def load_links(index: Path | None) -> dict[tuple[str, str], str]:
    """evidence-index.csv → {(ölçüt, kanıt no): bağlantı}. Dosya ya da sütun yoksa boş."""
    import csv
    if index is None or not Path(index).exists():
        return {}
    out = {}
    with open(index, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            u = (r.get("baglanti") or "").strip()
            if u and r.get("olcut") and r.get("kanit_no"):
                out[(r["olcut"].strip(), r["kanit_no"].strip())] = u
    return out


def eksik_text(a: dict | None) -> str | None:
    if not a:
        return None
    items = [e.get("gereken") for e in a.get("eksik") or [] if e.get("gereken")]
    if not items:
        return None
    return "Eksik kanıt notu: " + "; ".join(items) + "."


def _usable(t: dict | None) -> bool:
    return bool(t) and t.get("durum") != "reddedildi" and any(
        (p.get("metin") or "").strip() for p in t.get("paragraflar") or [])


def _mark_od(block, od: int, mode: str) -> bool:
    if mode == "yok" or not (1 <= od <= 5) or not block.rubric:
        return False
    for tc in block.rubric_cells(od):
        if mode == "kalin":
            ops.mark_bold(tc)
        else:
            ops.mark_shade(tc, GOLGE)
    if mode == "golge" and len(block.numbers) == 5:
        ops.mark_shade(block.numbers[od - 1], GOLGE)
    return True


def fill_cover(doc, birim: str | None, yil: int | str | None) -> dict[str, str]:
    """Kapak: "[Birim Adı]" yer tutucusu ve yalnız bir yıl olan ilk paragraf."""
    done: dict[str, str] = {}
    for el in doc.element.body.iterchildren(W + "p"):
        txt = _ptext(el).strip()
        if txt == COVER_STOP:
            break
        if birim and "birim" not in done and "[Birim Adı]" in txt:
            ops.set_paragraph_text(el, birim)
            done["birim"] = birim
        elif yil and "yil" not in done and RE_YIL.match(txt):
            ops.set_paragraph_text(el, str(yil))
            done["yil"] = str(yil)
    return done


def render(template: Path, out: Path, *, texts_dir: Path, audit_path: Path | None,
           birim: str | None = None, yil: int | str | None = None,
           opts: Options | None = None, index_path: Path | None = None) -> Result:
    import docx

    opts = opts or Options()
    if opts.puan_isareti not in PUAN_ISARETLERI:
        raise ValueError(f"puan işareti: {opts.puan_isareti} (seçenekler: {', '.join(PUAN_ISARETLERI)})")
    if opts.kanit_bicimi not in KANIT_BICIMLERI:
        raise ValueError(f"kanıt biçimi: {opts.kanit_bicimi} (seçenekler: {', '.join(KANIT_BICIMLERI)})")
    template, out = Path(template).expanduser().resolve(), Path(out).expanduser().resolve()
    if not template.exists():
        raise FileNotFoundError(f"şablon yok: {template}")
    if out == template:
        raise ValueError("çıktı şablonun üstüne yazılamaz; --out ile başka bir yol verin")

    res = Result(out)
    texts, uy = load_texts(Path(texts_dir))
    res.uyarilar += uy
    audit, uy = load_audit(audit_path)
    res.uyarilar += uy

    links = load_links(index_path)
    if index_path is not None and not Path(index_path).exists():
        res.uyarilar.append(f"evidence-index.csv yok ({index_path}); kanıt adları bağlantısız")
    doc = docx.Document(str(template))
    blocks, uy = find_blocks(doc)
    res.uyarilar += uy
    if not blocks:
        raise ValueError("şablonda alt ölçüt bloğu bulunamadı (FR-0833 biçimi değil mi?)")
    for cid in sorted(set(texts) - set(blocks)):
        res.uyarilar.append(f"{cid}: metni var ama şablonda bloğu yok; yazılmadı")

    for cid, b in blocks.items():
        t, a = texts.get(cid), audit.get(cid)
        aciklama: list = []
        kanit: list = []
        od = None
        if _usable(t):
            res.dolu.append(cid)
            if t.get("durum") != "dogrulandi":
                res.dogrulanmamis.append(cid)
                aciklama.append(ops.make_paragraph([(
                    f"{DOGRULANMADI} Bu açıklama metni doğrulama aşamasından geçmemiştir "
                    f"(durum: {t.get('durum') or 'belirtilmemiş'}).",
                    {"italic": True, "color": ops.TASLAK_RENK})]))
            known = {str(k.get("no")) for k in t.get("kanitlar") or []}
            for p in t.get("paragraflar") or []:
                m = clean_text(p.get("metin") or "")
                if not m:
                    continue
                aciklama.append(ops.make_paragraph(m))
                for no in RE_ATIF.findall(m):
                    if no not in known:
                        res.uyarilar.append(f"{cid}: metindeki [{no}] kanıt listesinde yok")
            if clean_text(t.get("onceki_yila_gore") or ""):
                aciklama.append(ops.make_paragraph(clean_text(t["onceki_yila_gore"])))
            kanit = []
            for k in t.get("kanitlar") or []:
                pre, ad = kanit_parts(k, opts.kanit_bicimi)
                url = links.get((cid, str(k.get("no", "")).strip()))
                if url:
                    seg = [(pre, {}), (ad, {"rid": ops.link_rid(doc.part, url)})]
                    res.baglantili += 1
                else:
                    seg = [(pre + ad, {})]
                    res.baglantisiz.append(f"{cid} [{k.get('no')}] {ad}")
                kanit.append(ops.make_paragraph(seg, jc="left"))
            if not kanit:
                res.uyarilar.append(f"{cid}: metin var, kanıt listesi boş")
                kanit = [ops.make_paragraph(opts.bos_kanit, jc="left")]
            od = t.get("od_onerisi")
        else:
            res.bos.append(cid)
            if t and t.get("durum") == "reddedildi":
                res.reddedildi.append(cid)
                aciklama.append(ops.make_paragraph([(
                    f"{DOGRULANMADI} Bu ölçüt için yazılan metin doğrulamada reddedildiği için "
                    "rapora alınmamıştır.", {"italic": True, "color": ops.TASLAK_RENK})]))
            aciklama.append(ops.make_paragraph(opts.bos_ifade))
            note = eksik_text(a) if opts.eksik_notu else None
            if note:
                aciklama.append(ops.make_paragraph([(note, {"italic": True})]))
            kanit = [ops.make_paragraph(opts.bos_kanit, jc="left")]
        od_a = a.get("od") if a else None
        if od is None:
            od = od_a
        elif od_a is not None and od > od_a:
            res.uyarilar.append(f"{cid}: metnin OD önerisi ({od}) audit önerisini ({od_a}) aşıyor; "
                                f"OD{od_a} işaretlendi")
            od = od_a
        if b.aciklama_tc is not None:
            ops.fill_cell(b.aciklama_tc, ACIKLAMA, aciklama)
        if b.kanit_tc is not None:
            ops.fill_cell(b.kanit_tc, KANIT, kanit)
        if od is not None and _mark_od(b, int(od), opts.puan_isareti):
            res.od[cid] = int(od)

    # Doğrulanmamış metin varsa TASLAK. İnsanın raporun dışında bıraktığı reddedilmiş metin
    # (`bidr verify karar … cikar`) rapora girmez ve belgeyi taslak yapmaz.
    res.taslak = any(t.get("durum") != "dogrulandi" and not (t.get("durum") == "reddedildi"
                                                             and t.get("insan_karari") == "cikar")
                     for t in texts.values())
    if res.taslak:
        ops.add_draft_mark(doc, TASLAK_METNI)
    res.kapak = fill_cover(doc, birim, yil)
    if birim and "birim" not in res.kapak:
        res.uyarilar.append("kapakta '[Birim Adı]' yer tutucusu bulunamadı")
    if yil and "yil" not in res.kapak:
        res.uyarilar.append("kapakta yıl paragrafı bulunamadı")
    out.parent.mkdir(parents=True, exist_ok=True)
    res.degisen_parcalar = ops.save_preserving(doc, template, out)
    return res


# -- çalışma alanı kaydı (render_tamam) ---------------------------------------------------------

def inputs_sha(template: Path, texts_dir: Path, audit_path: Path | None, index_path: Path | None) -> str:
    """Raporun girdilerinin özeti: şablon, metinler, audit, kanıt dizini."""
    import hashlib
    h = hashlib.sha256()
    for p in [Path(template), *(sorted(Path(texts_dir).glob("*.json")) if Path(texts_dir).is_dir() else []),
              *(x for x in (audit_path, index_path) if x)]:
        p = Path(p)
        h.update(p.name.encode())
        h.update(p.read_bytes() if p.exists() else b"-")
    return h.hexdigest()[:16]


def write_manifest(ws: Path, res: Result, sha: str, template: Path, *, texts_dir: Path,
                   audit_path: Path | None, index_path: Path | None) -> Path:
    import hashlib
    p = Path(ws) / MANIFEST
    rec = {"surum": 1, "cikti": str(res.out), "girdi_sha": sha, "sablon": str(template),
           "girdiler": {"texts": str(texts_dir), "audit": str(audit_path) if audit_path else None,
                        "index": str(index_path) if index_path else None},
           "cikti_sha": hashlib.sha256(Path(res.out).read_bytes()).hexdigest()[:16],
           **{k: v for k, v in res.ozet().items() if k != "cikti"}}
    p.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    return p


def load_manifest(ws: Path) -> dict | None:
    p = Path(ws) / MANIFEST
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
    except (OSError, ValueError):
        return None


def update_link_gaps(ws: Path, index_path: Path | None) -> None:
    """gaps.md "bağlantı yok" bölümünü kanıt dizininden yeniler (bkz. bidr/file/links.py)."""
    import csv

    from bidr.file.links import gaps_block, update_gaps
    if index_path is None or not Path(index_path).exists():
        return
    with open(index_path, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    update_gaps(Path(ws) / "gaps.md", gaps_block(rows))
