"""Denetim çekirdeği: decisions.jsonl (+ inceleme kararları) → satırlar ve ölçüt özetleri.

Salt okunur girdi: `decisions.jsonl`, `documents.jsonl` (çalışma alanı), ölçütler ve yuva
etiketleri (paket verisi). Çıktılar `out` klasörüne (varsayılan çalışma alanı):
`review.xlsx`, `gaps.md`, `audit-olcutler.json`; `apply` ayrıca
`review-decisions.jsonl` ve `slot-tags-oneri.yaml`.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from bidr.common import Workspace, read_jsonl, write_jsonl
from bidr.criteria.loader import load_criteria
from bidr.criteria.model import CriteriaSet, id_key
from bidr.criteria.profiles import load_profile
from bidr.criteria.slots import STAGE_OD, SlotTag, load_tags
from bidr.decide.run import (BIRIM_BELIRSIZ, BIRIM_DISI, BIRIM_KARARLARI, GENEL_ILISKI, INSAN_ILISKILERI,
                             load_unit_pins, needs_redecide, pin_applied, record_unit_relation,
                             unit_view)
from bidr.identify.parca import part_view

from . import donem as D
from .rules import (GEREKEN, KARAR_TURLERI, KISA, KURUM_GENELI_TURLER, LINKS, criterion_od,
                    effective_stage)

SURUM = 1
FILES = {"xlsx": "review.xlsx", "gaps": "gaps.md", "json": "audit-olcutler.json",
         "decisions": "review-decisions.jsonl", "tag_oneri": "slot-tags-oneri.yaml",
         "birim": BIRIM_KARARLARI, "od": "olcut-od-kararlari.jsonl", "gorulen": "review-gorulen.jsonl"}
ALINTI_KISA = 160                              # birim sayfasında alıntı kısaltması
KARARLAR = ("kabul", "ret", "duzelt")
ETIKET_KARARLARI = ("onayla", "duzelt")
DEFAULT_PROFILE = "akademik_bolum"
BETIMLEME_ISARETI = "[GÖRSEL BETİMLEME"       # bidr describe metin başlığı


def file_sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16] if p.exists() else ""


def load_od_decisions(out: Path) -> dict[str, dict]:
    """{ölçüt: insanın onayladığı nihai OD kaydı} (`olcut-od-kararlari.jsonl`; yoksa boş)."""
    p = Path(out) / FILES["od"]
    return {r["olcut"]: r for r in read_jsonl(p) if r.get("olcut") and r.get("od") in (1, 2, 3, 4, 5)} \
        if p.exists() else {}


def load_review_decisions(out: Path) -> dict[str, dict]:
    p = Path(out) / FILES["decisions"]
    return {r["satir"]: r for r in read_jsonl(p)} if p.exists() else {}


# -- "yeniden bakılmalı": kararlı satırın kararından sonra değişen durumu ----------------------
# İnsan kararı verildiğinde satırın gördüğü durum (inceleme işaretleri, sayılan aşama, OD)
# `review-gorulen.jsonl`'e yazılır. Audit yeniden çalışınca (araç güncellemesi, yeni belge) satıra
# yeni işaret eklenmiş ya da sayılan aşaması/OD'si değişmişse karar KORUNUR ama satır "yeniden
# bak" sütununda gerekçesiyle vurgulanır. İnsan satıra bakınca "bakıldı" sütununa `evet` yazar (ya da
# kararı/notu değiştirir): `audit apply` görülen durumu günceller.
# Kararın kendisinden doğan işaretler (insan ret/düzelt, birim onayı) karşılaştırmaya girmez.
KARAR_ISARETLERI = frozenset({"insan_reddetti", "insan_duzeltti", "birim_aitligi_onaylandi",
                              "birim_onay_bekliyor", "birim_aitligi_dogrulanmali"})


def load_seen(out: Path) -> dict[str, dict]:
    p = Path(out) / FILES["gorulen"]
    return {r["satir"]: r for r in read_jsonl(p) if r.get("satir")} if p.exists() else {}


def _save_seen(out: Path, seen: dict[str, dict]) -> None:
    p = Path(out) / FILES["gorulen"]
    if seen:
        write_jsonl(p, [seen[k] for k in sorted(seen)])
    elif p.exists():
        p.unlink()


def _od_int(v) -> int | None:
    try:
        return int(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def seen_state(r: dict) -> dict:
    """Satırın (audit satırı ya da tablodan okunan satır) karara esas durumu."""
    fl = r.get("flags")
    if fl is None:
        fl = [x.strip() for x in str(r.get("isaretler") or "").split(",") if x.strip()]
    return {"satir": r.get("satir"), "isaretler": sorted(set(fl) - KARAR_ISARETLERI),
            "asama": str(r.get("etkin_asama") or ""), "od": _od_int(r.get("od"))}


def relook_reason(base: dict, cur: dict, karar: str) -> str:
    """Görülen durumdan bu yana değişen (boş: değişiklik yok). Sayılan aşama/OD yalnız `kabul`de
    anlamlıdır (ret sayılmaz; duzelt aşamayı insan verir)."""
    parts = []
    yeni = [x for x in cur["isaretler"] if x not in set(base.get("isaretler") or [])]
    if yeni:
        parts.append("yeni işaret: " + ", ".join(yeni))
    if karar == "kabul":
        if (base.get("asama") or "") != cur["asama"]:
            parts.append(f"sayılan aşama {base.get('asama') or '—'} → {cur['asama'] or '—'}")
        if base.get("od") != cur["od"]:
            parts.append(f"OD {base.get('od') or '—'} → {cur['od'] or '—'}")
    return "; ".join(parts)


def _acknowledged(xr: dict | None) -> bool:
    """Tablo satırında "bakıldı" = evet (insan yeniden baktı, karar aynı kalsın)."""
    return bool(xr) and _norm(xr.get("bakildi")) in ("evet", "e", "bakildi", "tamam")


def relook_pending(xr: dict) -> bool:
    """Tablo satırı yeniden bakılmayı bekliyor mu (karar var, gerekçe dolu, bakıldı değil)."""
    return bool(str(xr.get("karar") or "").strip() and str(xr.get("yeniden_bak") or "").strip()
                and not _acknowledged(xr))


@dataclass
class Audit:
    ws: Workspace
    out: Path
    profile: str | None
    cs: CriteriaSet
    tags: dict[str, SlotTag]
    rows: list[dict]
    criteria: list[dict]
    decisions_sha: str
    uyarilar: list[str] = field(default_factory=list)
    donem: int | None = None                # rapor yılı (documents.jsonl `donem`)
    # birim aitliği: {"baska_birim": [...], "belirsiz": [...]} (belge başına bir kayıt)
    birim: dict = field(default_factory=lambda: {"baska_birim": [], "belirsiz": []})
    # "Başka birime ait sayılanlar" sayfası: modelin başka birim dediği ya da insanın birim
    # ilişkisine karar verdiği belgeler (belge başına bir satır)
    birim_sayfa: list = field(default_factory=list)
    birim_sha: str = ""                         # birim-kararlari.jsonl özeti (tablo güncelliği)
    faaliyet_sha: str = ""                      # faaliyetler.json özeti (tablo güncelliği)
    # gerçekleşmesi kanıtlanmamış faaliyetler (faaliyetler.json; yalnız duyurulu/kanıtsız)
    faaliyetler: list = field(default_factory=list)
    od_sha: str = ""                            # olcut-od-kararlari.jsonl özeti

    @property
    def by_key(self) -> dict[str, dict]:
        return {r["satir"]: r for r in self.rows}


def _tag_text(t: SlotTag | None) -> str:
    if t is None:
        return ""
    if t.uncertain:
        return "belirsiz (aşama içeriğe bağlı)"
    return ", ".join(t.stages) + " → OD" + "/".join(str(x) for x in t.od)


def lifted_od(m: dict, tags: dict) -> int | None:
    """decide'ın kurum geneli tavanından (`uygulama_kaniti_eksik`, OD2) önceki OD: modelin OD'si ile
    aşamanın (yuva etiketine göre) kod OD'sinin küçüğü. Tavan yoksa None. Kod kurum geneli
    olmadığını gösterdiğinde (birime özgü belge/sayfa) kullanılır."""
    from bidr.decide.run import _od_code
    if "uygulama_kaniti_eksik" not in ((m.get("denetim") or {}).get("isaret") or []) or not m.get("kabul"):
        return None
    od_model = m.get("od_onerisi")
    cands = [x for x in (od_model if isinstance(od_model, int) else None,
                         _od_code(m.get("asama"), tags.get(m.get("yuva")))) if x]
    return min(cands) if cands else None


def _lift(m: dict, tags: dict) -> dict:
    """Eşleşmenin kurum geneli tavanını kaldırır (kopya; işaret `kurum_tavani_kaldirildi`)."""
    od = lifted_od(m, tags)
    if od is None:
        return m
    den = dict(m.get("denetim") or {})
    den["isaret"] = [x for x in den.get("isaret") or [] if x != "uygulama_kaniti_eksik"] + ["kurum_tavani_kaldirildi"]
    return {**m, "od_kabul": od, "denetim": den}


def _row(cs, tags, docs, rec, m, dec, rule: D.Rule | None = None, name: tuple | None = None,
         link: tuple | None = None, betimleme: bool = False, dosya: str | None = None,
         surum: dict | None = None, sv=None) -> dict:
    did = rec["doc_id"]
    doc = docs.get(did) or {}
    key = f"{did}|{m['yuva']}"
    rel = record_unit_relation(rec)
    # birim aitliği işareti kaydın ilişkisinden yeniden kurulur (insan birim kararı kaldırır)
    flags = [f for f in (m.get("denetim") or {}).get("isaret") or [] if f != "birim_aitligi_dogrulanmali"]
    olcut, yuva, asama = m["olcut"], m["yuva"], m.get("asama")
    etkin = effective_stage(asama, m.get("od_kabul"))
    if etkin != asama:
        flags.append("asama_dusuruldu")
    dtype = doc.get("doc_type") or (rec.get("belge_bilgisi") or {}).get("tur") or ""
    donem_ici = doc.get("donem_ici")
    sayilir, karar = True, None
    sv_out = None
    if (rec.get("ince") or {}).get("birim_iliskisi_kod"):
        flags.append("birim_iliskisi_kod")
    if dec:
        karar = dec["karar"]
    if karar == "ret":
        sayilir = False
        flags.append("insan_reddetti")
    elif karar == "duzelt":
        dz = dec.get("duzelt") or {}
        olcut = dz.get("olcut") or olcut
        yuva = dz.get("yuva") or yuva
        etkin = dz.get("asama") or etkin
        flags.append("insan_duzeltti")
    else:
        # Kurum/fakülte geneli: tür listesi ya da ince kararın birim ilişkisi. Üst birimin bu
        # birim hakkındaki kararı (ör. senato kararı) tür yüzünden sınırlanmaz.
        # Bölümün kendi usul belgesi (yönerge türünde olsa bile; başlığında birimin adı) tür
        # tavanına girmez: kurum geneli değildir (birim adı config.yaml'da biliniyorsa).
        tur_kg = dtype in KURUM_GENELI_TURLER and not (
            rel == "ust_birim_bu_birim_hakkinda" and dtype in KARAR_TURLERI) and not (
            rel == "kendi" and dtype not in KARAR_TURLERI and sv is not None and sv.own_regulation(did))
        # Birleşik PDF: tür (yönerge) bütün belgeye verilmiş ama alıntı birimin kendi belgesinin
        # sayfasından (ör. bölümün ders değerlendirme sonucu): tür tavanı o satıra uygulanmaz.
        sayfa = (sv.unit_page(did, m.get("alinti") or "") if tur_kg and rel in ("kendi", "ust_birim_bu_birim_hakkinda")
                 and sv is not None else "")
        if sayfa:
            tur_kg = False
            od2 = lifted_od(m, tags)
            if od2 is not None:
                etkin = effective_stage(asama, od2)
                flags = [x for x in flags if x not in ("uygulama_kaniti_eksik", "asama_dusuruldu")]
                if etkin != asama:
                    flags.append("asama_dusuruldu")
            flags.append("birim_sayfasi")
        if tur_kg or rel in GENEL_ILISKI:
            flags.append("kurum_geneli")
            if rel == "fakulte_geneli":
                flags.append("fakulte_geneli")
            if etkin and etkin != "planla":
                etkin = "planla"
                flags.append("uygulama_kaniti_eksik")
        if sv is not None:
            # kod tarafı savunmalar (tür/ifade/faaliyet); insan `kabul`ü metin sezgilerini aşar
            sv_out = sv.row(rec, m, dtype, etkin, human=karar == "kabul")
            etkin = sv_out["etkin"]
            flags.extend(sv_out["flags"])
    # Dönem kuralı (yapı/olay/karma). İnsan kararında (ret/duzelt) yalnız gösterilir.
    dz_ = (D.apply_row(rule, doc, dtype, etkin, dosya, (surum or {}).get(did),
                       part_view(doc, m.get("alinti"), sv.text(did) if sv and doc.get("parcalar") else None))
           if rule is not None and etkin else None)
    if dz_ and karar not in ("ret", "duzelt"):
        sayilir = dz_["sayilir"]
        flags.extend(dz_["flags"])
    if sv_out and sv_out["sayilir"] is False:
        sayilir = False
    od = STAGE_OD.get(etkin) if etkin else None
    if od is None:
        sayilir = False
    tag = tags.get(yuva)
    if (tag and etkin and not tag.uncertain and etkin not in tag.stages
            and "uygulama_kaniti_eksik" not in flags):
        flags.append("asama_yuva_etiketine_uymuyor")
    # Düşük güvenli eşleşme önerilen OD'ye katılmaz; inceleme kararı (kabul/duzelt) bunu kaldırır:
    # insan kararı kuralı aşar (file ile aynı kural).
    dusuk = m.get("guven") == "dusuk"
    zayif = dusuk and karar not in ("kabul", "duzelt")
    vurgu = []
    if od and od >= 4 and sayilir:
        vurgu.append(f"OD{od}'e yükselten" + (" (ÖNERİ etiket)" if tag and tag.state != "onayli" else ""))
    if zayif:
        vurgu.append("düşük güven")
    elif dusuk:
        vurgu.append("düşük güven (incelemede onaylandı)")
    birim_bekler = False
    if rel == BIRIM_BELIRSIZ:
        # İnsan birim ilişkisini onaylamadıkça (satır kararı kabul/duzelt ya da birim sayfası)
        # belge kanıt sayılmaz ve yayımlanan listeye girmez ("devam et" de bunu aşmaz).
        if karar in ("kabul", "duzelt"):
            flags.append("birim_aitligi_onaylandi")
            vurgu.append("birim aitliği incelemede onaylandı")
        elif karar != "ret":
            birim_bekler = True
            sayilir = False
            flags += ["birim_aitligi_dogrulanmali", "birim_onay_bekliyor"]
            vurgu.insert(0, "BİRİM AİTLİĞİ DOĞRULANMALI: onaylanana dek sayılmaz")
    ince_ = rec.get("ince") or {}
    if ince_.get("birim_iliskisi_kod") in ("kendi", "ust_birim_bu_birim_hakkinda") \
            and karar not in ("kabul", "duzelt", "ret"):
        # kod metindeki birim sinyaliyle ilişkiyi düzeltti (bidr/audit/savunma.py unit_relation)
        if ince_.get("birim_iliskisi_model") in GENEL_ILISKI:
            vurgu.insert(0, "birim kodca düzeltildi (model kurum/fakülte geneli dedi; metin birime özgü): doğrulanmalı")
        else:
            vurgu.insert(0, "birim kodca önerildi (metinde birim sinyali; model belirsiz dedi): doğrulanmalı")
    if "birim_sayfasi" in flags:
        vurgu.append("alıntı birleşik belgede birimin kendi sayfasından: tür (kurum geneli) tavanı uygulanmadı")
    if sv_out:
        vurgu.extend(sv_out["vurgu"])
    if betimleme:
        flags.append("betimleme_alintisi")
        vurgu.append("alıntı görsel betimlemeden")
    try:
        ymetin = cs.get_slot(yuva).text
    except KeyError:
        ymetin = ""
    row = {
        "satir": key, "doc_id": did, "belge": doc.get("calisma_adi") or did, "belge_turu": dtype,
        "birim_iliskisi": rel,
        "kanit_adi": (name or ("", ""))[0], "kanit_adi_oneri": (name or ("", ""))[0],
        "kanit_adi_kaynagi": (name or ("", ""))[1],
        "baglanti": (link or ("", ""))[0], "baglanti_oneri": (link or ("", ""))[0],
        "baglanti_kaynagi": (link or ("", ""))[1],
        "alinti_kaynagi": "betimleme" if betimleme else "belge",
        "donem_ici": {True: "evet", False: "hayır"}.get(donem_ici, "?"),
        "donem_sinif": dz_["sinif"] if dz_ else "", "donem_zaman": dz_["zaman"] if dz_ else "",
        "donem_yil": dz_["yil"] if dz_ else None,
        "tarih": doc.get("tarih") or "", "tarih_kaynagi": dz_["kaynak"] if dz_ else "",
        "tarih_notu": dz_["not"] if dz_ else "", "birim_onay_bekliyor": birim_bekler,
        "olcut": olcut, "yuva": yuva, "yuva_metni": ymetin,
        "olcut_model": m["olcut"], "yuva_model": m["yuva"],
        "asama": asama, "od_model": m.get("od_onerisi"), "od_kabul": m.get("od_kabul"),
        "etkin_asama": etkin, "od": od, "sayilir": sayilir, "zayif": zayif,
        "etiket": _tag_text(tag), "etiket_durumu": tag.state if tag else "",
        "vurgu": "; ".join(vurgu), "guven": m.get("guven") or "",
        "isaretler": ", ".join(dict.fromkeys(flags)), "flags": list(dict.fromkeys(flags)),
        "alinti": m.get("alinti") or "", "gerekce": m.get("gerekce") or "",
        "yeniden_bak": "", "bakildi": "",
        **_decision_cells(dec),
    }
    row["donem_kurali"] = D.describe(row)
    row["tarih_bilgisi"] = " · ".join(x for x in (row["tarih"], row["tarih_kaynagi"], row["tarih_notu"]) if x)
    return row


def _decision_cells(dec: dict | None) -> dict:
    dec = dec or {}
    dz, et = dec.get("duzelt") or {}, dec.get("etiket") or {}
    return {"karar": dec.get("karar") or "", "duzelt_olcut": dz.get("olcut") or "",
            "duzelt_yuva": dz.get("yuva") or "", "duzelt_asama": dz.get("asama") or "",
            "etiket_karari": et.get("karar") or "", "etiket_yeni": ", ".join(et.get("asama") or []),
            "not": dec.get("not") or ""}


def _slot_links(cs, tags, cid) -> tuple[list, set[str]]:
    slots = [s for s in cs.get(cid).slots if not s.footnote]
    has: set[str] = set()
    for s in slots:
        t = tags.get(s.id)
        if t is None or t.uncertain:
            has.update(LINKS)
        else:
            has.update(x for x in t.stages if x in LINKS)
    return slots, has


def _human(r: dict) -> bool:
    return r["karar"] in ("ret", "duzelt")


def _cycle(rule: D.Rule | None, rows: list[dict], period: int | None) -> dict | None:
    """Ölçütte tanımlı gözden geçirme döngüsü (komisyon kararı 3. madde) ve önceki yıl
    halkalarının açılması. Döngü yalnız sayılan, düşük güvenli olmayan bir eşleşmenin
    alıntısından tanınır; birden çoksa en kısa (temkinli) pencere."""
    if rule is None or period is None:
        return None
    found = []
    for r in rows:
        if r["sayilir"] and not r["zayif"]:
            n = rule.cycle_years(r["alinti"])
            if n:
                found.append((n, r))
    if not found:
        return None
    n, src = min(found, key=lambda x: (x[0], x[1]["satir"]))
    acilan = []
    for r in rows:
        if ("gecmis_kanit" in r["flags"] and not _human(r) and "birim_onay_bekliyor" not in r["flags"]
                and r["donem_yil"] and r["donem_yil"] > period - n):
            r["sayilir"] = True
            r["flags"] = ["dongu_halkasi" if f == "gecmis_kanit" else f for f in r["flags"]]
            r["isaretler"] = ", ".join(r["flags"])
            r["donem_kurali"] = D.describe(r)
            if r["od"] and r["od"] >= 4 and "yükselten" not in r["vurgu"]:
                r["vurgu"] = "; ".join(x for x in (f"OD{r['od']}'e yükselten", r["vurgu"]) if x)
            acilan.append(r["satir"])
    return {"yil": n, "satir": src["satir"], "belge": src["belge"], "alinti": src["alinti"],
            "acilan": acilan}


def _criterion(cs, tags, cid, rows, allowed, rule: D.Rule | None = None,
               cycle: dict | None = None, ek: dict | None = None, od_karar: dict | None = None) -> dict:
    slots, has = _slot_links(cs, tags, cid)
    counted = [r for r in rows if r["sayilir"]]
    strong = {r["etkin_asama"] for r in counted if not r["zayif"]}
    every = {r["etkin_asama"] for r in counted}
    rs, ra = criterion_od(strong, has), criterion_od(every, has)
    tarihsiz = [r for r in rows if "tarih_dogrulanmali" in r["flags"] and not _human(r)]
    rt = criterion_od(strong | {r["etkin_asama"] for r in tarihsiz if not r["zayif"]}, has)
    gecmis = [r for r in rows if "gecmis_kanit" in r["flags"] and not _human(r)]
    sonra = [r for r in rows if set(D.DONEM_DISI) & set(r["flags"]) and not _human(r)]
    birim_bek = [r for r in rows if r.get("birim_onay_bekliyor")]
    filled = {r["yuva"] for r in counted}
    empty = [s for s in slots if s.id not in filled]
    halka = {}
    for x in LINKS:
        n_s = sum(1 for r in counted if r["etkin_asama"] == x and not r["zayif"])
        n_w = sum(1 for r in counted if r["etkin_asama"] == x and r["zayif"])
        halka[x] = ("var" if n_s else "dusuk" if n_w else "yuvasiz" if x not in has else "yok", n_s + n_w)
    kg = [r for r in counted if "kurum_geneli" in r["flags"]]
    kg_only = bool(kg) and "uygula" not in every
    eksik = []
    for x in rs.eksik:
        ys = [(s.id, s.text) for s in slots
              if (t := tags.get(s.id)) is None or t.uncertain or x in t.stages]
        eksik.append({"halka": x, "gereken": GEREKEN[x], "yuvasiz": x not in has,
                      "yuvalar": [{"yuva": i, "metin": t} for i, t in ys]})
    if counted and rs.od <= 2:
        grup = 1
    elif not counted:
        grup = 2
    elif rs.od == 3:
        grup = 3
    elif rs.od == 4:
        grup = 4
    else:
        grup = 9
    notlar = []
    if rs.ortuk_plan:
        notlar.append("plan belgesi önerilir: plan belgesi yok, uygulama/izleme kanıtı tanımlı sürecin örtük kanıtı sayıldı")
    if kg_only:
        notlar.append("yalnız kurum geneli düzenlemeyle eşleşti: bölümün uygulama kanıtı eksik")
    if ra.od > rs.od:
        notlar.append(f"düşük güvenli eşleşmeler doğrulanırsa OD{ra.od}")
    if gecmis:
        yillar = sorted({r["donem_yil"] for r in gecmis if r["donem_yil"]})
        notlar.append(f"{len(gecmis)} geçmiş kanıt (süreklilik"
                      + (f"; {', '.join(map(str, yillar))}" if yillar else "")
                      + "): önceki yıl olayı, bu yılın halkası sayılmadı")
    if cycle:
        notlar.append(f"gözden geçirme döngüsü tanımlı (son {cycle['yil']} yıl; `{cycle['belge']}`)"
                      + (f": {len(cycle['acilan'])} önceki yıl halkası sayıldı" if cycle["acilan"] else ""))
    if tarihsiz:
        notlar.append(f"{len(tarihsiz)} eşleşme tarihi bilinmeyen olay belgesinden: sayılmadı (tarih doğrulanmalı)"
                      + (f"; doğrulanırsa OD{rt.od}" if rt.od > rs.od else ""))
    gd = {r["doc_id"] for r in counted if "guncellik_dogrulanmali" in r["flags"]}
    if gd:
        notlar.append(f"{len(gd)} belgenin rapor yılında yürürlükte olduğu doğrulanmalı (güncellik; tarih dönem dışı ya da yok)")
    if sonra:
        notlar.append(f"{len({r['doc_id'] for r in sonra})} belge dönem sonrasına ait ya da yürürlükteki sürüm değil: "
                      "bu dönemin kanıtı sayılmadı")
    rv = {r["doc_id"] for r in counted if "revizyon_donem_sonrasi" in r["flags"]}
    if rv:
        notlar.append(f"{len(rv)} düzenlemenin revizyon tarihi dönem sonrası: dönemdeki sürüm aranmalı")
    if birim_bek:
        notlar.append(f"{len({r['doc_id'] for r in birim_bek})} belgenin birim aitliği doğrulanmadı: "
                      "onaylanana dek sayılmadı")
    ek = ek or {}
    notlar.extend(ek.get("notlar") or [])
    od_onayli = (od_karar or {}).get("od")
    if rs.od == 5 and od_onayli is None:
        notlar.append("OD5 kod önerisidir: insan onayı bekliyor (review.xlsx \"Ölçüt özeti\" ONAYLANAN OD)")
    if od_onayli is not None and od_onayli != rs.od:
        notlar.append(f"komisyonun onayladığı düzey OD{od_onayli} (kod önerisi OD{rs.od})")
    eksik_notu = _missing_note(rows, counted, rs)
    if eksik_notu and eksik_notu["durum"] == "neredeyse_kanitsiz":
        notlar.append("neredeyse kanıtsız: " + ", ".join(EKSIK_NEDEN[x] for x in eksik_notu["nedenler"]))
    dongu_onerisi = (rule.cycle_criteria.get(cid) if rule is not None and not cycle else None)
    if dongu_onerisi:
        notlar.append("döngü önerisi: " + dongu_onerisi)
    if cid not in allowed:
        notlar.append("profil dışı ölçüt")
    sub = cs.get(cid)
    return {
        "olcut": cid, "baslik": sub.title, "od": rs.od, "od_dusuk_dahil": ra.od,
        # kod önerisi ile insanın onayladığı nihai düzey ayrı alanlarda (`od` = kod önerisi)
        "od_kod_onerisi": rs.od, "od_onayli": od_onayli,
        "od_onay": ({k: od_karar.get(k) for k in ("od", "not", "kod_onerisi", "zaman")} if od_karar else None),
        "uygulama_yayilimi": ek.get("uygulama_yayilimi"),
        "faaliyetler": ek.get("faaliyetler") or [],
        "puko_zinciri": ek.get("puko_zinciri") or [],
        "zincir": {x: {"durum": d, "eslesme": n} for x, (d, n) in halka.items()},
        "zincir_kisa": " ".join(f"{KISA[x]}{'+' if d == 'var' else '~' if d == 'dusuk' else '·' if d == 'yuvasiz' else '-'}"
                                for x, (d, _) in halka.items()),
        "duzeyler": {str(k): v for k, v in rs.duzeyler.items()},
        "sonraki_od": rs.sonraki, "eksik": eksik,
        "eslesme": len(counted), "belge": len({r["doc_id"] for r in counted}),
        "yuva_toplam": len(slots), "yuva_dolu": len(slots) - len(empty),
        "bos_yuvalar": [{"yuva": s.id, "metin": s.text,
                         "etiket": _tag_text(tags.get(s.id))} for s in empty],
        "kurum_geneli_yalniz": kg_only, "notlar": notlar, "oncelik_grubu": grup,
        "od_tarih_dogrulanirsa": rt.od, "dongu": cycle, "dongu_onerisi": dongu_onerisi,
        "gecmis_kanit": [{"satir": r["satir"], "belge": r["belge"], "yuva": r["yuva"],
                          "asama": r["etkin_asama"], "yil": r["donem_yil"]} for r in gecmis],
        "donem_sonrasi": [{"satir": r["satir"], "belge": r["belge"], "yuva": r["yuva"],
                           "asama": r["etkin_asama"], "yil": r["donem_yil"],
                           "isaret": next(f for f in r["flags"] if f in D.DONEM_DISI)} for r in sonra],
        "eksik_kanit_notu": eksik_notu,
        "rubrik": {str(k): v for k, v in sub.rubric.items()},
    }


EKSIK_NEDEN = {
    "yalniz_kurum_geneli": "yalnız kurum/fakülte geneli düzenleme",
    "yalniz_dusuk_guven": "yalnız düşük güvenli eşleşme",
    "yalniz_donem_disi": "yalnız dönem dışı belge (geçmiş, dönem sonrası ya da yürürlükte olmayan sürüm)",
    "tarihi_dogrulanmamis": "tarihi doğrulanmamış olay belgesi",
    "birim_dogrulanmamis": "birim aitliği doğrulanmamış belge",
}


def _missing_note(rows: list[dict], counted: list[dict], rs) -> dict | None:
    """Eksik kanıt notu (render okur: `eksik_kanit_notu.metin`). `kanitsiz`: ölçütte hiç eşleşme
    yok (ya da hepsi insanca reddedildi); `neredeyse_kanitsiz`: eşleşme var ama bölümün bu döneme
    ait, düşük güvenli olmayan ve kurum geneli olmayan sayılan kanıtı yok. Aksi None."""
    own = [r for r in counted if not r["zayif"] and "kurum_geneli" not in r["flags"]]
    if own:
        return None
    live = [r for r in rows if "insan_reddetti" not in r["flags"]]
    nedenler: list[str] = []
    if any("kurum_geneli" in r["flags"] for r in counted):
        nedenler.append("yalniz_kurum_geneli")
    if any(r["zayif"] for r in counted):
        nedenler.append("yalniz_dusuk_guven")
    off = [set(r["flags"]) for r in live if not r["sayilir"]]
    if any(f & {"gecmis_kanit", *D.DONEM_DISI} for f in off):
        nedenler.append("yalniz_donem_disi")
    if any("tarih_dogrulanmali" in f for f in off):
        nedenler.append("tarihi_dogrulanmamis")
    if any("birim_onay_bekliyor" in f for f in off):
        nedenler.append("birim_dogrulanmamis")
    gereken = [GEREKEN[x] for x in rs.eksik if x in GEREKEN]
    if not live or not nedenler:
        durum = "kanitsiz"
        metin = "Eksik kanıt notu: " + ("; ".join(gereken) if gereken else "bu ölçüt için kanıt bulunamadı") + "."
    else:
        durum = "neredeyse_kanitsiz"
        metin = ("Eksik kanıt notu: bölümün bu döneme ait doğrudan kanıtı yok ("
                 + "; ".join(EKSIK_NEDEN[x] for x in nedenler) + ")"
                 + (". Gereken: " + "; ".join(gereken) if gereken else "") + ".")
    return {"durum": durum, "nedenler": nedenler, "metin": metin}


def _names(ws_root: Path, out: Path, docs: dict, recs: list[dict]):
    """doc_id → (kanıt adı, kaynak: insan|model|kural); bidr/name/resolve.py ile file'la aynı."""
    from bidr.file.run import _type_labels
    from bidr.name.resolve import Resolver
    res = Resolver.load(ws_root, out, docs=docs, decisions={r["doc_id"]: r for r in recs},
                        labels=_type_labels())
    cache: dict[str, tuple[str, str]] = {}

    def get(did: str) -> tuple[str, str]:
        if did not in cache:
            ad, src, _ = res.resolve(did)
            cache[did] = (ad, src)
        return cache[did]
    return get


def _links(ws: Workspace, out: Path):
    """doc_id → (bağlantı önerisi, kaynak: insan|belge_metni|""); bidr/file/links.py."""
    from bidr.file.links import LinkResolver
    res = LinkResolver.load(ws.root, out)
    cache: dict[str, tuple[str, str]] = {}

    def get(did: str) -> tuple[str, str]:
        if did not in cache:
            cache[did] = res.suggest(did)
        return cache[did]
    return get


def _described(ws: Workspace):
    """(doc_id, alıntı) → alıntı görsel betimlemeden mi geliyor. Belge metni `bidr describe`
    başlığıyla başlıyorsa ve alıntı betimleme öncesi metinde (`text_pre_describe/`) yoksa evet."""
    from bidr.describe.run import BASE_DIR
    head: dict[str, bool] = {}
    base: dict[str, str | None] = {}

    def get(did: str, q: str) -> bool:
        if did not in head:
            p = ws.text_path(did)
            try:
                with open(p, encoding="utf-8", errors="replace") as f:
                    head[did] = f.read(40).lstrip().startswith(BETIMLEME_ISARETI)
            except OSError:
                head[did] = False
        if not head[did]:
            return False
        if did not in base:
            bp = ws.root / BASE_DIR / f"{did}.txt"
            base[did] = bp.read_text(encoding="utf-8", errors="replace") if bp.exists() else None
        if not base[did] or not q:
            return True
        from bidr.llm import verify_quote
        return not verify_quote(q, base[did])[0]
    return get


def priority_key(c: dict) -> tuple:
    return (c["oncelik_grubu"], -(c["yuva_toplam"] - c["yuva_dolu"]), id_key(c["olcut"]))


def _short(q: str, n: int = ALINTI_KISA) -> str:
    q = " ".join(str(q or "").split())
    return q if len(q) <= n else q[:n].rsplit(" ", 1)[0] + " …"


def _unit_row(rec: dict, eff: dict, pin: dict | None, docs: dict, name: str) -> dict:
    """Birim sayfası satırı: modelin gerekçesi ve birim yüzünden reddedilen eşleşmeleri."""
    did = rec["doc_id"]
    ince = rec.get("ince") or {}
    belirsiz = record_unit_relation(rec) == BIRIM_BELIRSIZ
    red = [m for m in rec.get("eslesmeler") or []
           if (m.get("kabul") if belirsiz else BIRIM_DISI in ((m.get("denetim") or {}).get("red") or []))]
    esl = "\n".join(f"{m.get('olcut')} {m.get('yuva')} · {m.get('asama') or '?'} · OD{m.get('od_onerisi') or '?'}"
                    f": \"{_short(m.get('alinti'))}\"" for m in red)
    rel = (pin or {}).get("birim_iliskisi") or ""
    if not rel:
        durum = ("model: birim aitliği belirsiz (onaylanana dek kanıt sayılmaz)" if belirsiz
                 else "model: başka birim (kanıt sayılmadı)")
    elif rel == BIRIM_DISI:
        durum = "insan onayladı: başka birim"
    elif pin_applied(rec, pin):
        durum = "yeniden karar verildi (insan ilişkisiyle): eşleşmeler inceleme tablosunda"
    elif record_unit_relation(eff) == rel and any(m.get("kabul") for m in eff.get("eslesmeler") or []) \
            and record_unit_relation(rec) == BIRIM_DISI:
        durum = "geri alındı: eşleşmeler inceleme tablosunda"
    elif needs_redecide(rec, rel):
        durum = "yeniden karar gerekli (eşleşme kaydı yok): bidr decide prepare --stage fine --only " + did
    else:
        durum = f"insan kararı: {rel}"
    return {"doc_id": did, "belge": (docs.get(did) or {}).get("calisma_adi") or did, "kanit_adi": name,
            "gerekce": ince.get("gerekce") or "", "eslesmeler": esl, "eslesme_sayisi": len(red),
            "model_iliskisi": ince.get("birim_iliskisi_model") or record_unit_relation(rec),
            "durum": durum, "insan_birim_iliskisi": rel, "not": (pin or {}).get("not") or ""}


def build(ws_root: Path, *, out: Path | None = None, profile: str | None = None,
          criteria: CriteriaSet | None = None, review: dict[str, dict] | None = None,
          pins: dict[str, dict] | None = None) -> Audit:
    ws = Workspace(ws_root)
    out = Path(out).expanduser().resolve() if out else ws.root
    dpath = ws.root / "decisions.jsonl"
    if not dpath.exists():
        raise FileNotFoundError(f"decisions.jsonl yok: {dpath}")
    cs = criteria or load_criteria()
    tags = load_tags(cs)
    if profile is None:
        from bidr.init.config import load_section
        profile = (load_section(ws.root) or {}).get("profil") or DEFAULT_PROFILE
    allowed = set(load_profile(profile).allowed(cs)) if profile else {s.id for s in cs.sub_criteria}
    docs = {r["doc_id"]: r for r in read_jsonl(ws.documents)} if ws.documents.exists() else {}
    review = load_review_decisions(out) if review is None else review
    pins = load_unit_pins(out) if pins is None else pins
    rows, uy = [], []
    rule, period = None, None
    od_kar = load_od_decisions(out)
    inv: dict[str, str] = {}
    if ws.inventory.exists():
        from bidr.file.run import _inventory
        inv = {k: v.get("rel_path") or "" for k, v in _inventory(ws).items()}
    surum: dict[str, str] = {}
    if any("donem_ici" in d for d in docs.values()):
        rule = D.load_rule()
        surum = D.version_status(docs, rule, inv)
        from collections import Counter
        ps = Counter(d["donem"] for d in docs.values() if d.get("donem") is not None)
        period = ps.most_common(1)[0][0] if ps else None
    else:
        uy.append("documents.jsonl'de dönem bilgisi yok (`bidr identify --period`): dönem kuralı uygulanmadı")
    from .savunma import Savunma
    sv = Savunma.load(ws.root, docs, period)
    n_ince = 0
    recs = [r for r in read_jsonl(dpath) if r.get("doc_id")]
    names = _names(ws.root, out, docs, recs)
    links = _links(ws, out)
    desc = _described(ws)
    birim: dict = {"baska_birim": [], "belirsiz": []}
    sayfa: list[dict] = []
    own: dict[str, dict] = {}                   # birime ait ince kayıtlar (PUKÖ zinciri)
    for orig in recs:
        if orig.get("durum") != "ok" or orig.get("asama") != "ince":
            continue
        n_ince += 1
        pin = pins.get(orig["doc_id"])
        # insan birim kararı (öncelik insan > model): kaydın görünümü değişir, dosya değişmez
        rec = unit_view(orig, pins, tags)
        if not pin:
            # kod: metinde birimin adı yokken başka birim adı ya da bütün birimleri kapsayan ifade
            ov = sv.unit_relation(rec, record_unit_relation(rec))
            if ov:
                ince = dict(rec.get("ince") or {})
                old_rel = record_unit_relation(rec)
                ince["birim_iliskisi_model"] = ince.get("birim_iliskisi_model") or old_rel
                ince["birim_iliskisi"] = ince["birim_iliskisi_kod"] = ov[0]
                ince["gerekce"] = "; ".join(x for x in (ov[1], ince.get("gerekce")) if x)
                rec = orig = {**rec, "ince": ince}
                kg = ince.get("kurum_geneli")
                tur = isinstance(kg, dict) and bool(kg.get("tur"))
                if old_rel in GENEL_ILISKI and ov[0] not in GENEL_ILISKI and not tur:
                    # model kurum/fakülte geneli dedi, kod birime özgü buldu: decide'ın tavanı kalkar
                    rec = orig = {**rec, "eslesmeler": [_lift(m, tags) for m in rec.get("eslesmeler") or []]}
        if pin or record_unit_relation(orig) in (BIRIM_DISI, BIRIM_BELIRSIZ):
            sayfa.append(_unit_row(orig, rec, pin, docs, names(orig["doc_id"])[0]))
        rel = record_unit_relation(rec)
        if rel not in (BIRIM_DISI, BIRIM_BELIRSIZ):
            own[rec["doc_id"]] = rec
        if rel in (BIRIM_DISI, BIRIM_BELIRSIZ):
            ince = rec.get("ince") or {}
            birim["baska_birim" if rel == BIRIM_DISI else "belirsiz"].append({
                "doc_id": rec["doc_id"], "belge": (docs.get(rec["doc_id"]) or {}).get("calisma_adi") or rec["doc_id"],
                "gerekce": ince.get("gerekce") or "",
                **({"insan": True} if pin else {}),
                "eslesme": sum(bool(m.get("kabul")) for m in rec.get("eslesmeler") or [])})
        for m in rec.get("eslesmeler") or []:
            if m.get("kabul"):
                rows.append(_row(cs, tags, docs, rec, m, review.get(f"{rec['doc_id']}|{m['yuva']}"), rule,
                                 names(rec["doc_id"]), links(rec["doc_id"]),
                                 desc(rec["doc_id"], m.get("alinti") or ""), inv.get(rec["doc_id"]), surum, sv))
    if not n_ince:
        uy.append("decisions.jsonl'de ince karar yok: tablo boş")
    for x in birim["belirsiz"]:          # satır kararıyla onaylanan / bekleyen eşleşme sayısı
        rs_ = [r for r in rows if r["doc_id"] == x["doc_id"] and "insan_reddetti" not in r["flags"]]
        x["bekleyen"] = sum(1 for r in rs_ if r["birim_onay_bekliyor"])
        x["onaylanan"] = sum(1 for r in rs_ if "birim_aitligi_onaylandi" in r["flags"])
    rows.sort(key=lambda r: (id_key(r["olcut"]), r["yuva"], r["belge"]))
    by_c: dict[str, list] = {}
    for r in rows:
        by_c.setdefault(r["olcut"], []).append(r)
    ids = sorted(allowed | set(by_c), key=id_key)
    cyc = {c: _cycle(rule, by_c.get(c, []), period) for c in ids}
    ek = {}
    for c in ids:
        ek[c] = sv.criterion(by_c.get(c, []), _slot_links(cs, tags, c)[1])
        ek[c]["faaliyetler"] = sv.activities_for(by_c.get(c, []))
    rows += _puko(cs, tags, ws, docs, own, sv, by_c, ek, review, rule, names, links, inv, surum, uy)
    rows.sort(key=lambda r: (id_key(r["olcut"]), r["yuva"], r["belge"]))
    for x in (*rows, *sayfa):  # komisyon kontrolü: tablodan özgün dosyaya gidebilsin
        x["kaynak_dosya"] = inv.get(x.get("doc_id") or "", "")
    crits = [_criterion(cs, tags, c, by_c.get(c, []), allowed, rule, cyc[c], ek[c], od_kar.get(c)) for c in ids]
    sayfa.sort(key=lambda x: x["belge"])
    return Audit(ws, out, profile, cs, tags, rows, crits, file_sha(dpath), uy, period, birim, sayfa,
                 file_sha(out / FILES["birim"]), sv.faaliyet_sha, sv.unrealized(),
                 file_sha(out / FILES["od"]))


def _puko(cs, tags, ws, docs, own, sv, by_c, ek, review, rule, names, links, inv, surum, uy) -> list[dict]:
    """Belgeler arası açık atıf zinciriyle önlem halkası (bkz. puko.py). Yeni satırları döndürür;
    var olan satırlar ve `ek[ölçüt]` (notlar, `puko_zinciri`) yerinde güncellenir."""
    from . import puko as P
    baglar, bnot = P.build_links(docs, own, sv.text, (sv.faaliyet or {}).get("faaliyetler") or [])
    if bnot:
        uy.append(f"{len(bnot)} belge göndermesi birden çok faaliyete uyuyor: bağ kurulmadı ({bnot[0]}"
                  + (" …" if len(bnot) > 1 else "") + ")")
    before = {c: len(v) for c, v in by_c.items()}

    def make_row(rec, m, dec):
        did = rec["doc_id"]
        return _row(cs, tags, docs, rec, m, dec, rule, names(did), links(did), False, inv.get(did), surum, None)

    def disp(did):
        return (docs.get(did) or {}).get("calisma_adi") or did

    zin = P.apply(by_c, baglar, docs=docs, recs=own, fmap=sv.fmap, slots_of=lambda c: _slot_links(cs, tags, c),
                  tags=tags, make_row=make_row, review=review, names=disp)
    new = []
    for c, zs in zin.items():
        new += by_c[c][before.get(c, 0):]
        ek[c]["puko_zinciri"] = zs
        say = [z for z in zs if z["sayilir"]]
        if say:
            ek[c].setdefault("notlar", []).append(
                "PUKÖ zinciri: " + "; ".join(f"`{z['yol']}`" for z in say)
                + " (Ö halkası metindeki açık atıfla; ara belgeler kanıt listesine önerilir)")
    return new


def od_distribution(a: Audit) -> dict[int, int]:
    d = {k: 0 for k in range(1, 6)}
    for c in a.criteria:
        d[c["od"]] += 1
    return d


def write_outputs(a: Audit, *, xlsx: bool = True) -> dict[str, Path]:
    from . import report, sheet
    a.out.mkdir(parents=True, exist_ok=True)
    paths = {"gaps": a.out / FILES["gaps"], "json": a.out / FILES["json"]}
    old = paths["gaps"].read_text(encoding="utf-8") if paths["gaps"].exists() else ""
    # öteki aşamaların işaretli bölümleri (`<!-- bidr:ingest -->`, kanıt seçimi, bağlantı yok,
    # kapsam, …) korunur; "Kanıtla cevaplanmayan sorular" `soru-kapsami.json`'dan yenilenir
    paths["gaps"].write_text(report.compose_gaps(report.gaps_md(a), old, a.ws.root), encoding="utf-8")
    js = {"surum": SURUM, "calisma_alani": str(a.ws.root), "profil": a.profile,
          "kararlar_sha": a.decisions_sha, "donem": a.donem, "od_dagilimi": od_distribution(a),
          "birim_aitligi": {**a.birim, "insan_karari": [
              {k: x[k] for k in ("doc_id", "model_iliskisi", "insan_birim_iliskisi", "durum")}
              for x in a.birim_sayfa if x["insan_birim_iliskisi"]]}, "olcutler": a.criteria}
    paths["json"].write_text(json.dumps(js, ensure_ascii=False, indent=1), encoding="utf-8")
    if xlsx:
        paths["xlsx"] = a.out / FILES["xlsx"]
        sheet.write_review(a, paths["xlsx"])
    return paths


def audit(ws_root: Path, *, out: Path | None = None, profile: str | None = None) -> tuple[Audit, dict]:
    """Tabloyu üretir. Var olan review.xlsx'teki henüz uygulanmamış kararlar kaybolmaz:
    yeni tabloya taşınır (önceki tablo `review.onceki.xlsx` olarak saklanır)."""
    from . import sheet
    ws = Workspace(ws_root)
    outp = Path(out).expanduser().resolve() if out else ws.root
    applied = load_review_decisions(outp)
    carry: dict[str, dict] = {}
    carry_names: dict[str, str] = {}
    carry_links: dict[str, str] = {}
    carry_units: dict[str, tuple[str, str]] = {}
    carry_od: dict[str, tuple] = {}
    old = outp / FILES["xlsx"]
    uy = []
    if old.exists():
        try:
            _, xrows = sheet.read_review(old)
        except Exception as e:   # bozuk/eski tablo: kararları taşıyamayız, üzerine yazmayız
            raise RuntimeError(f"var olan {old.name} okunamadı ({e}); taşıyın ya da silin") from e
        cs = load_criteria()
        for xr in xrows:
            dec, err = parse_decision(xr, cs)
            if dec and applied.get(dec["satir"]) != dec:
                carry[dec["satir"]] = dec
        carry_names = {sid: v for sid, v, _ in _name_edits(xrows)}
        carry_links = {str(xr.get("satir")): str(xr.get("baglanti")).strip() for xr in xrows
                       if str(xr.get("baglanti") or "").strip()
                       and str(xr.get("baglanti")).strip() != str(xr.get("baglanti_oneri") or "").strip()}
        pins = load_unit_pins(outp)
        for ur in sheet.read_unit_sheet(old) or []:
            if _unit_pending(ur, pins.get(ur["doc_id"])):
                carry_units[ur["doc_id"]] = (str(ur.get("insan_birim_iliskisi") or "").strip(),
                                             str(ur.get("not") or "").strip())
        prev_od = load_od_decisions(outp)
        for o in sheet.read_od_sheet(old) or []:
            if _od_pending([o], prev_od):
                carry_od[o["olcut"]] = (o.get("od"), o.get("not") or "")
        if carry:
            uy.append(f"{len(carry)} karar tabloda vardı ama uygulanmamıştı: yeni tabloya taşındı "
                      f"(OD'ye yansıması için `bidr audit apply`)")
        old.replace(outp / "review.onceki.xlsx")
    else:
        xrows = []
    a = build(ws_root, out=outp, profile=profile, review=applied)
    n_rb = _mark_relook(a, outp, applied, carry, {str(xr.get("satir")): xr for xr in xrows})
    if n_rb:
        uy.append(f"{n_rb} kararlı satır yeniden bakılmalı (karardan sonra yeni inceleme işareti ya da sayılan "
                  f"aşama/OD değişti): eski karar korundu; review.xlsx 'YENİDEN BAK' sütunu (tablonun başında). "
                  f"Karar aynı kalacaksa 'bakıldı' = evet, sonra `bidr audit apply`")
    if carry_names:
        n = 0
        for r in a.rows:     # uygulanmamış kanıt adı düzeltmesi: tabloda kalır
            v = carry_names.get(r["satir"])
            if v and v != r["kanit_adi_oneri"]:
                r["kanit_adi"] = v
                n += 1
        if n:
            uy.append(f"{n} satırda kanıt adı düzeltmesi uygulanmamıştı: yeni tabloya taşındı")
    if carry_links:
        n = 0
        for r in a.rows:     # uygulanmamış bağlantı düzeltmesi: tabloda kalır
            v = carry_links.get(r["satir"])
            if v and v != r["baglanti_oneri"]:
                r["baglanti"] = v
                n += 1
        if n:
            uy.append(f"{n} satırda bağlantı düzeltmesi uygulanmamıştı: yeni tabloya taşındı")
    if carry_units:          # uygulanmamış birim kararı: sayfada kalır
        n = 0
        for x in a.birim_sayfa:
            if x["doc_id"] in carry_units:
                x["insan_birim_iliskisi"], x["not"] = carry_units[x["doc_id"]]
                n += 1
        if n:
            uy.append(f"{n} belgede birim ilişkisi kararı uygulanmamıştı: yeni tabloya taşındı")
    if carry_od:             # uygulanmamış OD onayı: "Ölçüt özeti"nde kalır (OD'ye/kayda yansımaz)
        for c in a.criteria:
            if c["olcut"] in carry_od:
                v, nt = carry_od[c["olcut"]]
                c["od_onayli"] = v
                c["od_onay"] = {**(c.get("od_onay") or {}), "od": v, "not": nt}
        uy.append(f"{len(carry_od)} ölçütte ONAYLANAN OD uygulanmamıştı: yeni tabloya taşındı")
    a.uyarilar.extend(uy)
    if carry:   # tabloda göster, OD hesabına katma (uygulanmadı)
        for r in a.rows:
            d = carry.get(r["satir"])
            if d:
                r.update(_decision_cells(d))
    paths = write_outputs(a)
    return a, paths


def _mark_relook(a: Audit, outp: Path, applied: dict[str, dict], carry: dict[str, dict],
                 old_rows: dict[str, dict]) -> int:
    """İşlenmiş kararı olan satırlarda görülen durumla yeni durumu karşılaştırır; değişeni
    `yeniden_bak` gerekçesiyle işaretler (karar değişmez). Görülen durum kaydı yoksa (bu özellikten
    önceki çalışma alanı) önceki tablonun satırından alınır: o zaman yalnız yeni işaret karşılaştırılır
    (önceki tablo kararsız hesaplanmış olabilir; aşama/OD karşılaştırması yanıltır).
    Önceki tabloda 'bakıldı' = evet yazılmışsa görülen durum o satırdır."""
    seen = load_seen(outp)
    n = 0
    for sid in list(seen):
        if sid not in applied:
            seen.pop(sid)
    for r in a.rows:
        sid = r["satir"]
        dec = applied.get(sid)
        if not dec or sid in carry:
            continue
        xr = old_rows.get(sid)
        if xr is not None and "isaretler" in xr and (sid not in seen or _acknowledged(xr)):
            seen[sid] = {**seen_state(xr), "tam": _acknowledged(xr)}
        base = seen.get(sid)
        if not base:
            continue
        cur = seen_state(r)
        why = relook_reason(base, cur, dec["karar"] if base.get("tam") else "")
        if why:
            r["yeniden_bak"] = why
            n += 1
    _save_seen(outp, seen)
    return n


def _update_seen(a: Audit, outp: Path, prev: dict[str, dict], merged: dict[str, dict],
                 xrows: list[dict]) -> int:
    """`audit apply`: kararın gördüğü durumu kaydeder. Yeni/değişen kararda, 'bakıldı' = evet
    satırda ya da kaydı olmayan satırda görülen durum = şimdiki durum; aksi halde (yeniden bakılmayı
    bekleyen satır) eski görülen durum korunur. Döner: hâlâ yeniden bakılmayı bekleyen satır sayısı."""
    seen = {k: v for k, v in load_seen(outp).items() if k in merged}
    xr_by = {str(xr.get("satir")): xr for xr in xrows}
    rows = a.by_key
    n = 0
    for sid, dec in merged.items():
        r = rows.get(sid)
        if not r:
            continue
        cur = seen_state(r)
        base = seen.get(sid)
        if (base is None or prev.get(sid) != dec or _acknowledged(xr_by.get(sid))
                or not relook_reason(base, cur, dec["karar"] if base.get("tam") else "")):
            seen[sid] = {**cur, "tam": True}
        else:
            n += 1
    _save_seen(outp, seen)
    return n


# -- karar okuma / uygulama ---------------------------------------------------------------

_TR = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")


def _norm(v) -> str:
    return str(v or "").strip().translate(_TR).lower()


def parse_decision(xr: dict, cs: CriteriaSet) -> tuple[dict | None, str | None]:
    """Tablo satırı → karar kaydı. (None, None): karar boş. (None, hata): geçersiz."""
    from bidr.criteria.slots import STAGES
    k = _norm(xr.get("karar"))
    k = {"red": "ret", "reddet": "ret", "onay": "kabul", "duzeltme": "duzelt"}.get(k, k)
    sid = xr.get("satir") or ""
    if "|" not in sid:
        return None, "satır kimliği bozuk"
    did, yuva = sid.split("|", 1)
    et_k = _norm(xr.get("etiket_karari"))
    if not k:
        return (None, "etiket kararı var ama satır kararı boş") if et_k else (None, None)
    if k not in KARARLAR:
        return None, f"karar '{xr.get('karar')}' geçersiz (kabul/ret/duzelt)"
    rec = {"satir": sid, "doc_id": did, "olcut": xr.get("olcut_model") or yuva.split("/")[0],
           "yuva": yuva, "karar": k, "duzelt": None, "etiket": None,
           "not": str(xr.get("not") or "").strip()}
    if k == "duzelt":
        yo = str(xr.get("duzelt_yuva") or "").strip()
        oo = str(xr.get("duzelt_olcut") or "").strip()
        aa = _norm(xr.get("duzelt_asama")).replace(" ", "_")
        if not (yo or oo or aa):
            return None, "duzelt: en az bir düzelt sütunu dolu olmalı"
        if oo and not yo:
            return None, "duzelt: ölçüt değişince yuva da verilmeli (ör. B.1.2/3)"
        if yo:
            try:
                sl = cs.get_slot(yo)
            except KeyError:
                return None, f"duzelt: yuva '{yo}' yok"
            if sl.footnote:
                return None, f"duzelt: '{yo}' dipnot, kanıt yuvası değil"
            if oo and oo != sl.criterion:
                return None, f"duzelt: yuva {yo} ölçüt {oo}'a ait değil"
            oo = sl.criterion
        if aa and aa not in LINKS:
            return None, f"duzelt: aşama '{xr.get('duzelt_asama')}' geçersiz ({', '.join(LINKS)})"
        rec["duzelt"] = {"olcut": oo or None, "yuva": yo or None, "asama": aa or None}
    if et_k:
        if et_k not in ETIKET_KARARLARI:
            return None, f"yuva etiketi kararı '{xr.get('etiket_karari')}' geçersiz (onayla/duzelt)"
        yeni = [_norm(x).replace(" ", "_") for x in str(xr.get("etiket_yeni") or "").replace(";", ",").split(",")
                if x.strip()]
        if et_k == "duzelt":
            if not yeni or any(x not in STAGES for x in yeni):
                return None, f"yuva etiketi düzeltmesi: aşamalar {', '.join(STAGES)} içinden, virgülle"
            if "belirsiz" in yeni and len(yeni) > 1:
                return None, "yuva etiketi: belirsiz başka aşamayla birlikte olamaz"
        target = (rec["duzelt"] or {}).get("yuva") or yuva
        rec["etiket"] = {"karar": et_k, "yuva": target, "asama": list(dict.fromkeys(yeni)) if et_k == "duzelt" else []}
    return rec, None


# Birim sayfası açılır listesindeki ek seçenek: insan kararını kaldır, modelin kararına dön.
MODEL_DON = "model"
BIRIM_SECENEKLERI = (*INSAN_ILISKILERI, MODEL_DON)


def _unit_cell(ur: dict) -> str:
    """Birim sayfası hücresi → normalleştirilmiş değer ('' boş; geçersizse ham metin)."""
    raw = str(ur.get("insan_birim_iliskisi") or "").strip()
    v = _norm(raw).replace(" ", "_").replace("-", "_")
    return v if v in BIRIM_SECENEKLERI else raw


def _unit_pending(ur: dict, pin: dict | None) -> bool:
    """Sayfa satırı uygulanmamış bir değişiklik taşıyor mu. Boş hücre önceki kararı korur
    (ana sayfadaki boş KARAR gibi): değişiklik değildir; `model` yalnız karar varsa değişikliktir."""
    v = _unit_cell(ur)
    if not v:
        return False
    if v == MODEL_DON:
        return bool(pin)
    p = pin or {}
    return (v, str(ur.get("not") or "").strip()) != (p.get("birim_iliskisi") or "", p.get("not") or "")


def parse_units(urows: list[dict], prev: dict[str, dict], recs: dict[str, dict]
                ) -> tuple[dict[str, dict], dict[str, str], dict]:
    """Birim sayfası → yeni birim kararları. Boş hücre önceki insan kararını korur (ana sayfadaki
    boş KARAR hücresi gibi); `model` kararı kaldırır (modelin kararına dönülür); sayfada olmayan
    belgelerin kararı korunur. (kararlar, hatalar, özet)."""
    import time
    out = dict(prev)
    errs: dict[str, str] = {}
    oz = {"geri_alinan": [], "yeniden_karar": [], "baska_birim_onay": [], "kaldirilan": []}
    for ur in urows:
        did = str(ur.get("doc_id") or "").strip()
        if not did:
            continue
        v = _unit_cell(ur)
        nt = str(ur.get("not") or "").strip()
        if not v:
            continue
        if v == MODEL_DON:
            if out.pop(did, None):
                oz["kaldirilan"].append(did)
            continue
        if v not in INSAN_ILISKILERI:
            errs[f"birim:{did}"] = (f"insan_birim_iliskisi '{v}' geçersiz ({', '.join(BIRIM_SECENEKLERI)}; "
                                    f"boş: önceki karar korunur)")
            continue
        rec = recs.get(did)
        p = prev.get(did) or {}
        r = {"doc_id": did, "birim_iliskisi": v, "kaynak": "insan",
             "model_iliskisi": ((rec or {}).get("ince") or {}).get("birim_iliskisi_model")
             or record_unit_relation(rec),
             "yeniden_karar": needs_redecide(rec, v), "not": nt}
        same = {k: p.get(k) for k in r} == r
        r["zaman"] = p.get("zaman") if same and p.get("zaman") else time.strftime("%Y-%m-%dT%H:%M:%S")
        out[did] = r
        key = ("baska_birim_onay" if v == BIRIM_DISI else "yeniden_karar" if r["yeniden_karar"]
               else "geri_alinan")
        oz[key].append(did)
    return out, errs, oz


def _od_cell(v) -> int | None | str:
    """ONAYLANAN OD hücresi → 1..5, None (boş) ya da ham metin (geçersiz)."""
    t = str(v or "").strip().upper().removeprefix("OD").strip()
    if not t:
        return None
    try:
        n = int(float(t))
    except ValueError:
        return str(v)
    return n if 1 <= n <= 5 and float(t) == n else str(v)


def parse_od(orows: list[dict], prev: dict[str, dict]) -> tuple[dict[str, dict], dict[str, str]]:
    """"Ölçüt özeti" ONAYLANAN OD sütunu → insan OD kararları (kod önerisinden ayrı kayıt).
    Boş hücre kararı kaldırır (sütun her zaman tabloda görünür; boşaltmak geri almaktır)."""
    import time
    out, errs = {}, {}
    for o in orows:
        cid, v = o["olcut"], _od_cell(o.get("od"))
        if v is None:
            continue
        if isinstance(v, str):
            errs[f"od:{cid}"] = f"ONAYLANAN OD '{v}' geçersiz (1-5)"
            if cid in prev:
                out[cid] = prev[cid]
            continue
        r = {"olcut": cid, "od": v, "kod_onerisi": o.get("kod_onerisi"), "not": o.get("not") or "",
             "kaynak": "insan"}
        p = prev.get(cid) or {}
        same = {k: p.get(k) for k in ("od", "not")} == {k: r[k] for k in ("od", "not")}
        r["zaman"] = p.get("zaman") if same and p.get("zaman") else time.strftime("%Y-%m-%dT%H:%M:%S")
        out[cid] = r
    return out, errs


def _od_pending(orows: list[dict] | None, prev: dict[str, dict]) -> set[str]:
    """Tablodaki ONAYLANAN OD / OD notu kayıttan farklı olan ölçütler (uygulanmamış)."""
    pend = set()
    for o in orows or []:
        v = _od_cell(o.get("od"))
        p = prev.get(o["olcut"]) or {}
        if v is None and not p:
            continue
        if (v, o.get("not") or "") != (p.get("od"), p.get("not") or ""):
            pend.add(f"od:{o['olcut']}")
    return pend


def review_state(out: Path, ws_root: Path | None = None) -> dict:
    """Tamamlanma denetimi için salt okunur durum."""
    from . import sheet
    out = Path(out)
    x = out / FILES["xlsx"]
    st = {"tablo": x.exists(), "guncel": False, "satir": 0, "kararli": 0, "gecersiz": 0,
          "uygulanmamis": 0}
    if not x.exists():
        return st
    meta, xrows = sheet.read_review(x)
    dsha = file_sha(Path(ws_root or out) / "decisions.jsonl")
    # birim kararları değişince tablo da değişir (geri alınan eşleşmeler satır olur)
    # faaliyetler.json değişince sayılan aşamalar değişebilir (faaliyet → audit)
    st["guncel"] = (meta.get("kararlar_sha") == dsha
                    and (meta.get("birim_sha") or "") == file_sha(out / FILES["birim"])
                    and (meta.get("faaliyet_sha") or "") == file_sha(Path(ws_root or out) / "faaliyetler.json"))
    applied = load_review_decisions(out)
    cs = load_criteria()
    st["satir"] = len(xrows)
    for xr in xrows:
        dec, err = parse_decision(xr, cs)
        if err:
            st["gecersiz"] += 1
        elif dec:
            st["kararli"] += 1
            if applied.get(dec["satir"]) != dec:
                st["uygulanmamis"] += 1
    # kanıt adı / bağlantı düzeltmeleri: tabloda var ama `apply` ile kayda geçmemiş
    from bidr.file.links import load_links
    from bidr.name.check import clean
    from bidr.name.resolve import load_names
    names, links = load_names(out), load_links(out)
    pend: set[str] = set()
    for sid, v, _ in _name_edits(xrows):
        did = sid.split("|", 1)[0]
        if clean(((names.get(did) or {}).get("insan") or {}).get("ad") or "") != v:
            pend.add(f"ad:{did}")
    for xr in xrows:
        sid = str(xr.get("satir") or "")
        v = str(xr.get("baglanti") or "").strip()
        if "|" in sid and v and v != str(xr.get("baglanti_oneri") or "").strip():
            did = sid.split("|", 1)[0]
            if (links.get(did) or {}).get("baglanti") != v:
                pend.add(f"baglanti:{did}")
    pins = load_unit_pins(out)
    for ur in sheet.read_unit_sheet(x) or []:
        if _unit_pending(ur, pins.get(ur["doc_id"])):
            pend.add(f"birim:{ur['doc_id']}")
    pend |= _od_pending(sheet.read_od_sheet(x), load_od_decisions(out))
    st["uygulanmamis_duzeltme"] = len(pend)
    # yeniden bakılmalı: işlenmiş kararı değişmemiş, 'bakıldı' yazılmamış satırlar
    st["yeniden_bak"] = 0
    seen = load_seen(out)
    for xr in xrows:
        dec, err = parse_decision(xr, cs)
        if not dec or applied.get(dec["satir"]) != dec or not str(xr.get("yeniden_bak") or "").strip():
            continue
        if relook_pending(xr):
            st["yeniden_bak"] += 1
        else:       # 'bakıldı' yazıldı: görülen durum kaydına geçmediyse apply bekler
            b = seen.get(dec["satir"])
            if not (b and b.get("tam") and not relook_reason(b, seen_state(xr), dec["karar"])):
                pend.add(f"bakildi:{dec['satir']}")
    st["uygulanmamis_duzeltme"] = len(pend)
    return st


def apply(ws_root: Path, *, out: Path | None = None, profile: str | None = None) -> dict:
    """review.xlsx → review-decisions.jsonl (+ slot-tags-oneri.yaml); gaps.md ve
    audit-olcutler.json yeni kararlarla yeniden yazılır (tablo yeniden yazılmaz)."""
    from . import sheet
    ws = Workspace(ws_root)
    outp = Path(out).expanduser().resolve() if out else ws.root
    x = outp / FILES["xlsx"]
    if not x.exists():
        raise FileNotFoundError(f"{x} yok: önce `bidr audit`")
    _, xrows = sheet.read_review(x)
    cs = load_criteria()
    prev = load_review_decisions(outp)
    hatalar, yeni = {}, {}
    bos = 0
    for xr in xrows:
        dec, err = parse_decision(xr, cs)
        if err:
            hatalar[xr.get("satir") or "?"] = err
        elif dec:
            yeni[dec["satir"]] = dec
        else:
            bos += 1
    merged = {**prev, **yeni}
    for sid in hatalar:            # geçersiz satırın eski kararı da geçersizdir
        merged.pop(sid, None)
    write_jsonl(outp / FILES["decisions"], [merged[k] for k in sorted(merged)])
    adlar, ad_hata = parse_names(xrows)
    if adlar:
        from bidr.name.resolve import NAMES, upsert
        upsert(outp / NAMES, adlar)
    from bidr.file.links import LINKS, parse_link_edits, upsert_links
    baglar, bag_hata = parse_link_edits(xrows)
    if baglar:
        upsert_links(outp / LINKS, baglar)
    oneri = write_tag_proposals(outp, merged, cs)
    urows = sheet.read_unit_sheet(x)          # None: eski tablo (sayfa yok), birim kararı değişmez
    pins = load_unit_pins(outp)
    birim_hata, birim_oz = {}, {}
    if urows is not None:
        recs = {r["doc_id"]: r for r in read_jsonl(ws.root / "decisions.jsonl") if r.get("doc_id")} \
            if (ws.root / "decisions.jsonl").exists() else {}
        pins, birim_hata, birim_oz = parse_units(urows, pins, recs)
        bp = outp / FILES["birim"]
        if pins:
            write_jsonl(bp, [pins[k] for k in sorted(pins)])
        elif bp.exists():
            bp.unlink()
    orows = sheet.read_od_sheet(x)            # None: eski tablo (sütun yok), OD kararları değişmez
    od_hata: dict[str, str] = {}
    if orows is not None:
        ods, od_hata = parse_od(orows, load_od_decisions(outp))
        op = outp / FILES["od"]
        if ods:
            write_jsonl(op, [ods[k] for k in sorted(ods, key=id_key)])
        elif op.exists():
            op.unlink()
    a = build(ws.root, out=outp, profile=profile, review=merged, pins=pins)
    write_outputs(a, xlsx=False)
    n_rb = _update_seen(a, outp, prev, merged, xrows)
    from collections import Counter
    return {"satir": len(xrows), "kararli": len(yeni), "bos": bos, "gecersiz": hatalar,
            "karar": dict(Counter(d["karar"] for d in yeni.values())),
            "etiket_onerisi": oneri, "od_dagilimi": od_distribution(a),
            "kanit_adi": len(adlar), "kanit_adi_gecersiz": ad_hata,
            "baglanti": len(baglar), "baglanti_gecersiz": bag_hata,
            "birim": {k: v for k, v in birim_oz.items() if v}, "birim_gecersiz": birim_hata,
            "od_onayli": len(load_od_decisions(outp)), "od_gecersiz": od_hata, "yeniden_bak": n_rb}


def _name_edits(xrows: list[dict]) -> list[tuple[str, str, str]]:
    """(satır, düzeltilmiş ad, öneri): "kanıt adı" hücresi doldurulmuş ve öneriden farklı."""
    from bidr.name.check import clean
    out = []
    for xr in xrows:
        sid = str(xr.get("satir") or "")
        v, o = clean(xr.get("kanit_adi") or ""), clean(xr.get("kanit_adi_oneri") or "")
        if sid and "|" in sid and v and v != o:
            out.append((sid, v, o))
    return out


def parse_names(xrows: list[dict]) -> tuple[list[dict], dict[str, str]]:
    """Tablodaki kanıt adı düzeltmeleri → `kanit-adlari.jsonl` kayıtları (`kaynak: insan`).
    Ad belgeye aittir: aynı belgenin satırlarında farklı düzeltme ya da kişi adı/unvan/
    e-posta içeren ad geçersizdir (hata anahtarı `kanit_adi:<doc_id>`)."""
    import time

    from bidr.name.check import check_name
    by: dict[str, dict[str, list[str]]] = {}
    prev: dict[str, str] = {}
    for sid, v, o in _name_edits(xrows):
        did = sid.split("|", 1)[0]
        by.setdefault(did, {}).setdefault(v, []).append(sid)
        prev[did] = o
    recs, errs = [], {}
    for did in sorted(by):
        vs = by[did]
        if len(vs) > 1:
            errs[f"kanit_adi:{did}"] = "aynı belgenin satırlarında farklı kanıt adları: " + " | ".join(vs)
            continue
        (v, sids), = vs.items()
        ad, e = check_name(v)
        if e:
            errs[f"kanit_adi:{did}"] = f"kanıt adı '{v}' geçersiz ({', '.join(e)}): kişi adı/unvan/e-posta yok, 2-10 sözcük"
            continue
        recs.append({"doc_id": did, "ad": ad, "kaynak": "insan", "onceki": prev[did], "satirlar": sorted(sids),
                     "zaman": time.strftime("%Y-%m-%dT%H:%M:%S")})
    return recs, errs


def write_tag_proposals(out: Path, decisions: dict[str, dict], cs: CriteriaSet) -> int:
    """Yuva etiketi kararlarını öneri dosyasına toplar. Paket verisini DEĞİŞTİRMEZ."""
    import yaml
    from bidr.criteria.slots import read_tags
    tags = load_tags(cs)
    by: dict[str, list] = {}
    for d in decisions.values():
        e = d.get("etiket")
        if e:
            by.setdefault(e["yuva"], []).append((d["satir"], e, d.get("not") or ""))
    oneriler, celiski = [], []
    for yuva in sorted(by, key=lambda s: (id_key(s.split("/")[0]), int(s.split("/")[1]))):
        t = tags.get(yuva)
        cur = list(t.stages) if t else []
        variants = {}
        for sid, e, nt in by[yuva]:
            st = tuple(cur) if e["karar"] == "onayla" else tuple(e["asama"])
            variants.setdefault(st, []).append((sid, nt))
        if len(variants) > 1:
            celiski.append({"yuva": yuva, "secenekler": [{"asama": list(k), "satirlar": [s for s, _ in v]}
                                                         for k, v in variants.items()]})
            continue
        (st, src), = variants.items()
        oneriler.append({
            "yuva": yuva, "metin": cs.get_slot(yuva).text,
            "mevcut": {"asama": cur, "od": list(t.od) if t else [], "durum": t.state if t else None},
            "oneri": {"asama": list(st), "od": sorted({STAGE_OD[x] for x in st if x in STAGE_OD}),
                      "durum": "onayli"},
            "degisiklik": "yalniz_onay" if list(st) == cur else "asama_degisiyor",
            "satirlar": [s for s, _ in src], "notlar": [n for _, n in src if n]})
    p = Path(out) / FILES["tag_oneri"]
    if not oneriler and not celiski:
        if p.exists():
            p.unlink()
        return 0
    head = ("# Yuva etiketi ÖNERİLERİ (bidr audit apply). Bu dosya hiçbir şeyi değiştirmez.\n"
            "# Kullanıcı onaylarsa `bidr/data/criteria/slot-tags-yokak-2025.yaml`'daki ilgili kayıtlara\n"
            "# asama/od/durum olarak elle (ya da şefin aracıyla) işlenir; `bidr criteria` doğrulaması sonra\n"
            "# çalıştırılmalı. Çelişkiler (aynı yuvaya farklı öneri) önce çözülmeli.\n")
    body = {"surum": 1, "olcut_surumu": read_tags().get("olcut_surumu"), "oneriler": oneriler,
            "celiskiler": celiski}
    p.write_text(head + yaml.safe_dump(body, allow_unicode=True, sort_keys=False, width=110), encoding="utf-8")
    return len(oneriler)
