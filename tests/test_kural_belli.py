"""Kural belliyse sorulmaz (kullanıcı kararı 2026-11-26 17:57; sentetik veri, model yok):
birden çok sürümde en yeni sürüm yürürlükte sayılır (eskisi `surum_eski`, bilgi, sayılmaz); kurum/fakülte geneli
düzenleme OD2 tavanıyla kanıt sayılır, sorulmaz; kodun hesapladığı aşama esastır (aşama/yuva uyuşmazlığı ve
gerçekleşme kanıtı yok sorulmaz). Geçmiş yıl belgesi, sıralanamayan sürüm ve başka birim maddesi sorulmaya devam eder."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from openpyxl import load_workbook

from bidr.audit import donem as D
from bidr.audit import sade as S
from bidr.audit.run import apply, audit, build, load_review_decisions, seen_state
from bidr.audit.sheet import read_review
from bidr.criteria.loader import load_criteria

YIL = 2025


def _doc(tur, tarih=None, **kw):
    d = {"doc_type": tur, "tarih": tarih, "donem": YIL, "akademik_donem": [], **kw}
    d.setdefault("donem_ici", (int(tarih[:4]) == YIL) if tarih else None)
    return d


def _st(docs, text=None):
    return D.version_status(docs, D.load_rule(), text=text)


# -- sürüm sırası -------------------------------------------------------------------------------

def test_en_yeni_surum_yururlukte():
    g = {"surum_grubu": "g"}
    # yıl sırası; rapor yılında çıkan en yeni sürüm öncülünü de eskitir (eskiden ikisi de sayılırdı)
    assert _st({"a": _doc("yonerge", "2019-01-01", **g), "b": _doc("yonerge", "2022-03-01", **g),
                "c": _doc("yonerge", "2025-02-01", **g)}) == {"a": "surum_eski", "b": "surum_eski"}
    # aynı yıl: tam tarih ayırır
    assert _st({"a": _doc("yonerge", "2023-02-01", **g), "b": _doc("yonerge", "2023-09-15", **g)}) == {"a": "surum_eski"}
    # rapor yılından sonraki sürüm: eski kural (dönemdeki en yeni sürüm sayılır, sonraki sorulur)
    assert _st({"a": _doc("yonerge", "2020-01-01", **g), "b": _doc("yonerge", "2023-01-01", **g),
                "c": _doc("yonerge", "2026-04-01", **g)}) == {"a": "surum_eski", "c": "surum_donem_sonrasi"}


def test_siralanamayan_surum_sorulur():
    g = {"surum_grubu": "g"}
    # hepsi tarihsiz ve revizyonsuz: sorulur, sayılır
    assert _st({"a": _doc("yonerge", **g), "b": _doc("yonerge", **g)}) == {
        "a": "surum_dogrulanmali", "b": "surum_dogrulanmali"}
    # tarihli en yeni sürüm sorulmadan sayılır; tarihsiz üye sorulur ve sayılmaz; eski tarihli eskidir
    assert _st({"a": _doc("yonerge", "2021-01-01", **g), "b": _doc("yonerge", "2024-01-01", **g),
                "t": _doc("yonerge", **g)}) == {"a": "surum_eski", "t": "surum_dogrulanmali_sayilmaz"}
    # aynı yılın tam tarihsiz iki sürümü: ayırt edilemez, ikisi de sayılır (eskisi gibi sorulmaz)
    assert _st({"a": _doc("yonerge", "2024", **g), "b": _doc("yonerge", "2024", **g)}) == {}
    # tek tarihsiz aday + dönem sonrası sürüm: tarihsiz, sonrakinin kopyası olabilir: sorulur
    assert _st({"t": _doc("yonerge", **g), "s": _doc("yonerge", "2026-01-01", **g)}) == {"t": "surum_dogrulanmali"}


def test_revizyon_numarasi_siralar():
    g = {"surum_grubu": "g"}
    metin = {"r2": "Doküman No: YÖ-0058 Revizyon No: 2\nYönerge", "r5": "Doküman No: YÖ-0058 Revizyon No: 5\nYönerge",
             "t": "Yönerge metni"}
    docs = {k: _doc("yonerge", **g) for k in metin}
    # r5 r2'yi geçer; revizyonsuz tarihsiz üye r5 ile sıralanamaz: ikisi sorulur
    assert _st(docs, text=metin.get) == {"r2": "surum_eski", "r5": "surum_dogrulanmali", "t": "surum_dogrulanmali"}
    del docs["t"]
    assert _st(docs, text=metin.get) == {"r2": "surum_eski"}
    docs["t"] = _doc("yonerge", surum_grubu="g")
    # metin verilmezse yalnız tarih: hepsi sorulur (eski davranış)
    assert set(_st(docs).values()) == {"surum_dogrulanmali"}


def test_farkli_ders_kodu_surum_degil():
    """Benzerlik grubu iki dersin bilgi formunu birleştirmiş: baş bölgedeki ders kodları çelişiyor, sürüm değiller
    (en yeni sürüm kuralı birini sessizce düşürmesin)."""
    g = {"surum_grubu": "g"}
    metin = {"a": "Ders Bilgi Formu\nDers kodu: MAT 301\nİçerik ...", "b": "Ders Bilgi Formu\nDers kodu: MAT 401\n...",
             "c": "Ders Bilgi Formu\nDers kodu: MAT 401\n..."}
    docs = {"a": _doc("ders_bilgi_formu", "2022-01-01", **g), "b": _doc("ders_bilgi_formu", "2023-01-01", **g),
            "c": _doc("ders_bilgi_formu", "2024-01-01", **g)}
    assert _st(docs, text=metin.get) == {"b": "surum_eski"}          # aynı dersin sürümleri sıralanır
    assert _st(docs) == {"a": "surum_eski", "b": "surum_eski"}        # metinsiz: bölünmez


# -- İnceleme: sorulmayanlar -----------------------------------------------------------------------

def test_kural_belli_isaretler_bakin_yapmaz():
    base = {"sayilir": True, "od": 2, "karar": "", "zayif": False}
    for fl in (["kurum_geneli"], ["kurum_geneli", "fakulte_geneli", "uygulama_kaniti_eksik"],
               ["asama_yuva_etiketine_uymuyor"], ["asama_dusuruldu", "kurum_geneli"]):
        assert S.dikkat({**base, "flags": fl}, YIL) == ([], False), fl
    # eski sürüm: sayılmaz ama sorulmaz, "Şu an kanıt sayılmıyor" yazılmaz
    assert S.dikkat({**base, "sayilir": False, "flags": ["surum_eski"]}, YIL) == ([], False)
    # gerçekleşme kanıtı yok: plan sayıldı; bilgi metni kalır (panel "etkinlik yapıldı mı" sorusunu bundan tanır)
    uy, bak = S.dikkat({**base, "flags": ["gerceklesme_kaniti_yok", "asama_yuva_etiketine_uymuyor"]}, YIL)
    assert not bak and "Yalnız duyuru ya da plan" in uy[0] and "etkinlik yapıldı" in uy[0]
    # karar verilmeyenler sorulmaya devam eder
    # geçmiş yıl belgesi (kullanıcı kararı 2026-11-26 20:12): sayılmaz, sorulmaz, Dikkat yazmaz
    assert S.dikkat({**base, "sayilir": False, "flags": ["gecmis_kanit"]}, YIL) == ([], False)
    for fl, say in ((["surum_dogrulanmali"], True), (["madde_baska_birim"], False),
                    (["surum_donem_sonrasi"], False)):
        uy, bak = S.dikkat({**base, "sayilir": say, "flags": fl}, YIL)
        assert bak and uy, fl
    # sayılmayan başka nedenli satır eski sürüm işaretiyle susmaz
    uy, bak = S.dikkat({**base, "sayilir": False, "flags": ["surum_eski", "madde_baska_birim"]}, YIL)
    assert bak


def test_bilgi_isaretleri_yeniden_baktirmaz():
    st = seen_state({"satir": "x|A.1.1/1", "flags": ["kurum_geneli", "fakulte_geneli", "surum_eski",
                                                     "asama_yuva_etiketine_uymuyor", "gerceklesme_kaniti_yok",
                                                     "uygulama_kaniti_eksik", "asama_dusuruldu", "gecmis_kanit",
                                                     "madde_baska_birim"]})
    assert st["isaretler"] == ["madde_baska_birim"]


# -- uçtan uca: eski sürüm toplu kabulle sayılmaz --------------------------------------------------

def _m(olcut, yuva, asama):
    od = {"planla": 2, "uygula": 3}[asama]
    return {"olcut": olcut, "yuva": yuva, "asama": asama, "od_onerisi": od, "od_kabul": od, "alinti": "x" * 30,
            "gerekce": "g", "guven": "yuksek", "kabul": True,
            "denetim": {"alinti_tutuyor": True, "red": [], "isaret": []}}


def _ws(tmp_path: Path) -> Path:
    docs = {
        "v_eski": (_doc("yonerge", "2022-04-01", surum_grubu="g"), [_m("B.1.1", "B.1.1/1", "planla")], None),
        "v_yeni": (_doc("yonerge", "2024-05-01", surum_grubu="g"), [_m("B.1.1", "B.1.1/1", "planla")], None),
        "kg": (_doc("resmi_yazi", "2025-03-01"), [_m("B.1.2", "B.1.2/1", "uygula")], "kurum_geneli"),
    }
    ws = tmp_path / "ws"
    (ws / "text").mkdir(parents=True)
    with open(ws / "inventory.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["doc_id", "sha256", "rel_path", "ext", "size", "pages", "chars", "method", "status", "dup_of",
                    "error"])
        for did in docs:
            w.writerow([did, did * 4, f"{did}.docx", ".docx", 1, 1, 10, "x", "ok", "", ""])
    with open(ws / "documents.jsonl", "w", encoding="utf-8") as f, \
            open(ws / "decisions.jsonl", "w", encoding="utf-8") as g:
        for did, (d, ms, rel) in docs.items():
            (ws / "text" / f"{did}.txt").write_text(f"Belge {did} metni.", encoding="utf-8")
            f.write(json.dumps({"doc_id": did, "calisma_adi": did, **d}, ensure_ascii=False) + "\n")
            g.write(json.dumps({"doc_id": did, "durum": "ok", "asama": "ince", "karar": "olcut_var",
                                **({"ince": {"birim_iliskisi": rel}} if rel else {}), "eslesmeler": ms},
                               ensure_ascii=False) + "\n")
    return ws


def test_eski_surum_ve_kurum_geneli_ucdan_uca(tmp_path):
    ws = _ws(tmp_path)
    a = build(ws)
    by = a.by_key
    eski, yeni, kg = by["v_eski|B.1.1/1"], by["v_yeni|B.1.1/1"], by["kg|B.1.2/1"]
    assert not eski["sayilir"] and "surum_eski" in eski["flags"] and "daha yeni sürümü var" in eski["donem_kurali"]
    assert yeni["sayilir"] and not {"surum_dogrulanmali", "surum_eski"} & set(yeni["flags"])
    assert kg["sayilir"] and kg["od"] == 2 and {"kurum_geneli", "uygulama_kaniti_eksik"} <= set(kg["flags"])
    x = {r["satir"]: r for r in S.inceleme_satirlari(a, load_criteria())}
    for k in ("v_eski|B.1.1/1", "v_yeni|B.1.1/1", "kg|B.1.2/1"):
        assert x[k]["bolum"] == 2 and x[k]["oneri"] == "Kabul" and not x[k]["dikkat"], k
    # 2. bölüm "Hepsini kabul" (panelin varsayılan kabulü): eski sürüme uygulanmaz, kural geçerli kalır
    a, paths = audit(ws)
    wb = load_workbook(paths["xlsx"])
    sh = wb[S.SH_INC]
    head = [c.value for c in sh[1]]
    col = {k: head.index(h) + 1 for k, h, _, _ in S.INC_COLS}
    for r in range(2, sh.max_row + 1):
        if sh.cell(r, col["satir"]).value == S.TOPLU_SATIR:
            sh.cell(r, col["karar"], S.TOPLU)
    wb.save(paths["xlsx"])
    _, rows = read_review(paths["xlsx"])
    d = {r["satir"]: r for r in rows}
    assert d["v_yeni|B.1.1/1"]["karar"] == d["kg|B.1.2/1"]["karar"] == "kabul"
    assert not d["v_eski|B.1.1/1"]["karar"]
    assert not apply(ws)["gecersiz"]
    assert "v_eski|B.1.1/1" not in load_review_decisions(ws)
    a2 = build(ws)
    assert not a2.by_key["v_eski|B.1.1/1"]["sayilir"] and a2.by_key["v_yeni|B.1.1/1"]["sayilir"]
    # bölüm eski sürümü tek tek kabul ederse sayılır (bölüm değiştirebilir)
    a3 = build(ws, review={**load_review_decisions(ws), "v_eski|B.1.1/1": {"satir": "v_eski|B.1.1/1", "karar": "kabul"}})
    assert a3.by_key["v_eski|B.1.1/1"]["sayilir"]
