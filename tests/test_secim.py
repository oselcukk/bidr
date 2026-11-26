"""Kanıt seçimi (K18 ilgililik, K20 sürüm/kopya): sentetik çalışma alanı, model yok."""
from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from bidr.audit.run import audit, build
from bidr.file import run as R
from bidr.file import select as S


def _m(olcut, yuva, asama, alinti, guven="yuksek", isaret=()):
    od = {"planla": 2, "uygula": 3, "kontrol_et": 4, "onlem_al": 4, "ozgun": 5}[asama]
    return {"olcut": olcut, "yuva": yuva, "asama": asama, "od_onerisi": od, "alinti": alinti,
            "gerekce": "g", "guven": guven,
            "denetim": {"alinti_tutuyor": True, "alinti_skor": 1.0, "alinti_konum": None,
                        "red": [], "isaret": list(isaret)},
            "od_kabul": od, "kabul": True}


def _ws(tmp_path: Path, docs: list[dict]) -> tuple[Path, Path]:
    """docs: {id, text, eslesmeler, doc_type?, tarih?, surum_grubu?, birim?}"""
    src, ws = tmp_path / "kaynak", tmp_path / "ws"
    (ws / "text").mkdir(parents=True)
    src.mkdir()
    with open(ws / "inventory.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["doc_id", "sha256", "rel_path", "ext", "size", "pages", "chars", "method", "status",
                    "dup_of", "error"])
        for d in docs:
            (src / f"{d['id']}.docx").write_bytes(b"PK sentetik " + d["id"].encode())
            w.writerow([d["id"], d["id"] * 4, f"{d['id']}.docx", ".docx", 1, 1, len(d["text"]), "x", "ok", "", ""])
    with open(ws / "documents.jsonl", "w", encoding="utf-8") as f:
        for d in docs:
            f.write(json.dumps({"doc_id": d["id"], "doc_type": d.get("doc_type", "bolum_kurulu_karari"),
                                **({"donem": 2025, "donem_ici": d["donem_ici"]} if "donem_ici" in d else {}),
                                "baslik": d.get("baslik", f"Belge {d['id']} Başlığı"),
                                "calisma_adi": f"calisma_{d['id']}", "tarih": d.get("tarih"),
                                "surum_grubu": d.get("surum_grubu")}, ensure_ascii=False) + "\n")
    with open(ws / "decisions.jsonl", "w", encoding="utf-8") as f:
        for d in docs:
            (ws / "text" / f"{d['id']}.txt").write_text(d["text"], encoding="utf-8")
            f.write(json.dumps({"doc_id": d["id"], "durum": "ok", "asama": "ince", "karar": "olcut_var",
                                **({"ince": {"birim_iliskisi": d["birim"]}} if d.get("birim") else {}),
                                "eslesmeler": d["eslesmeler"]}, ensure_ascii=False) + "\n")
    return ws, src


def _index(out: Path) -> list[dict]:
    with open(out / R.INDEX, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _secim(out: Path) -> dict:
    return json.loads((out / S.SECIM).read_text(encoding="utf-8"))


def _decision_count(ws: Path) -> int:
    return sum(1 for r in build(ws).rows)


def _karar(i: int, guven="yuksek", isaret=(), yuva="B.1.1/4", asama="uygula") -> dict:
    t = f"Bölüm kurulu {i} numaralı kararı ile program uygulaması yürütülmüştür."
    return {"id": f"k{i:02d}", "text": t, "tarih": f"2025-03-{i + 1:02d}",
            "eslesmeler": [_m("B.1.1", yuva, asama, t[:30], guven, isaret)]}


# -- K18: ilgililik ---------------------------------------------------------------------------

def test_cap_keeps_audit_od_and_lists_dropped(tmp_path):
    docs = [_karar(i) for i in range(13)]                         # varsayılan sınır 10 (2026-11-19)
    docs.append({"id": "kontrol", "text": "Program izleme raporu değerlendirildi.",
                 "eslesmeler": [_m("B.1.1", "B.1.1/6", "kontrol_et", "Program izleme raporu")]})
    ws, src = _ws(tmp_path, docs)
    out = tmp_path / "out"
    n_before = _decision_count(ws)
    st = R.run(ws, out=out, source=src)
    rows = [r for r in _index(out) if r["olcut"] == "B.1.1"]
    assert len(rows) == 10 and st["elenen"] == 4 and st["aday"] == 14
    assert "kontrol" in {r["doc_id"] for r in rows}             # en yüksek OD önce
    # audit eşleşme kaybetmez: satırlar ve OD seçimden bağımsız
    a = build(ws)
    assert len(a.rows) == n_before == 14
    assert {e["neden"] for e in _secim(out)["elenen"]} == {"ust_sinir"}
    g = (out / "gaps.md").read_text(encoding="utf-8")
    assert S.GAPS_BEGIN in g and "Kanıt listesine alınmayan diğer belgeler" in g and "ölçüt üst sınırı dolu" in g
    # config.yaml `rapor.kanit_secimi` sınırı değiştirir; manifest eskir
    assert R.status(out, ws)["guncel"]
    (ws / "config.yaml").write_text("rapor:\n  kanit_secimi:\n    olcut_basina_en_fazla: 3\n", encoding="utf-8")
    assert not R.status(out, ws)["guncel"]
    R.run(ws, out=out, source=src)
    assert len(_index(out)) == 3 and R.status(out, ws)["guncel"]
    (ws / "config.yaml").write_text("rapor:\n  kanit_secimi:\n    olcut_basina_en_fazla: null\n", encoding="utf-8")
    R.run(ws, out=out, source=src)
    assert len(_index(out)) == 14


def test_low_confidence_and_indirect_dropped_but_chain_kept(tmp_path):
    docs = [_karar(0), _karar(1, guven="dusuk"), _karar(2, isaret=["asama_dusuruldu"]),
            {"id": "tekK", "text": "İzleme sonuçları değerlendirildi.",          # K halkasının tek kanıtı
             "eslesmeler": [_m("B.1.1", "B.1.1/6", "kontrol_et", "İzleme sonuçları", "orta",
                               ["asama_yuva_etiketine_uymuyor"])]}]
    ws, src = _ws(tmp_path, docs)
    out = tmp_path / "out"
    R.run(ws, out=out, source=src)
    by = {r["doc_id"]: r for r in _index(out)}
    assert set(by) == {"k00", "tekK"}
    assert "zincir_icin_secildi" in by["tekK"]["isaretler"]
    el = {e["doc_id"]: e["neden"] for e in _secim(out)["elenen"]}
    assert el == {"k01": "dusuk_guven", "k02": "dolayli"}
    assert {s["doc_id"]: s["neden"] for s in _secim(out)["secilen"]} == {"k00": "dogrudan", "tekK": "zincir"}


def test_uncounted_candidates_ranked_last(tmp_path):
    docs = [dict(_karar(i), donem_ici=True) for i in range(10)]
    # tarihi çelişkili olay (önceki yıl birincil, rapor yılı da geçiyor): OD'ye sayılmaz. Tarihsiz olay artık
    # dönem içi varsayılır (kullanıcı kararı 2026-11-26), sayılmayan aday örneği değildir.
    docs.append(dict(_karar(19), donem_ici=False, tarih="2023-05-10", tarihler=["2023-05-10", "2025-04-01"]))
    ws, src = _ws(tmp_path, docs)
    out = tmp_path / "out"
    R.run(ws, out=out, source=src)
    assert [(e["doc_id"], e["neden"]) for e in _secim(out)["elenen"]] == [("k19", "ust_sinir")]
    (ws / "config.yaml").write_text("rapor:\n  kanit_secimi:\n    olcut_basina_en_fazla: 11\n", encoding="utf-8")
    R.run(ws, out=out, source=src)
    k9 = next(r for r in _index(out) if r["doc_id"] == "k19")
    assert "od_sayilmadi" in k9["isaretler"]                     # elenmez, işaretli girer


def test_kurum_geneli_limit_prefers_article_quotes(tmp_path):
    docs = []
    for i in range(7):
        madde = i in (2, 4, 6)
        t = (f"MADDE {i + 3} - Program tasarımı usulü {i}." if madde else f"Genel hükümler yönetmelik {i} amaç.")
        docs.append({"id": f"y{i}", "text": t, "doc_type": "yonetmelik",
                     "eslesmeler": [_m("B.1.1", "B.1.1/1", "planla", t[:25])]})
    docs.append(_karar(0))
    ws, src = _ws(tmp_path, docs)
    out = tmp_path / "out"
    st = R.run(ws, out=out, source=src)
    ids = {r["doc_id"] for r in _index(out)}
    assert ids == {"k00", "y2", "y4", "y6"}                      # madde alıntılı üçü (sınır 3)
    assert st["elenen_kurum_geneli"] == 4
    g = (out / "gaps.md").read_text(encoding="utf-8")
    assert "### Elenen kurum geneli belgeler" in g and "madde alıntısı yok" in g
    assert all(f"`y{i}`" in g for i in (0, 1, 3, 5))
    # audit yeniden yazılınca file'ın bölümü korunur
    audit(ws, out=out)
    g2 = (out / "gaps.md").read_text(encoding="utf-8")
    assert g2.count(S.GAPS_BEGIN) == 1 and "### Elenen kurum geneli belgeler" in g2
    # sınır yapılandırılabilir
    (ws / "config.yaml").write_text("rapor:\n  kanit_secimi:\n    kurum_geneli_en_fazla: 0\n", encoding="utf-8")
    R.run(ws, out=out, source=src)
    # P halkasının kanıtı yalnız kurum geneli: zincir için madde alıntılı biri kalır
    by = {r["doc_id"]: r for r in _index(out)}
    assert set(by) == {"k00", "y2"} and "zincir_icin_secildi" in by["y2"]["isaretler"]


def test_cited_and_human_override_cap(tmp_path):
    docs = [_karar(i) for i in range(4)]
    ws, src = _ws(tmp_path, docs)
    out = tmp_path / "out"
    R.run(ws, out=out, source=src)
    first = {r["doc_id"]: r for r in _index(out)}
    # write sonrası metin: son numaralı kanıta atıf
    last = max(first.values(), key=lambda r: int(r["kanit_no"].split("_")[0]))
    (ws / "texts").mkdir()
    (ws / "texts" / "B.1.1.json").write_text(json.dumps({
        "olcut": "B.1.1", "paragraflar": [{"metin": f"Uygulanmaktadır [{last['kanit_no']}].",
                                            "atiflar": [last["kanit_no"]]}],
        "kanitlar": [{"no": last["kanit_no"], "ad": last["ad"], "dosya": last["dosya"]}]}), encoding="utf-8")
    (ws / "config.yaml").write_text("rapor:\n  kanit_secimi:\n    olcut_basina_en_fazla: 1\n", encoding="utf-8")
    R.run(ws, out=out, source=src)
    sel = {s["doc_id"]: s["neden"] for s in _secim(out)["secilen"]}
    # atıf sınırdan yer tutar (düşmez): write sonrası dosyalama elenmişleri geri alıp listeyi büyütmez
    assert sel == {last["doc_id"]: "atif"}
    # toplu `kabul` (audit_tamam her satıra karar ister) seçimi devre dışı bırakmaz
    _review(ws, {d: "kabul" for d in first})
    R.run(ws, out=out, source=src)
    sel = {s["doc_id"]: s["neden"] for s in _secim(out)["secilen"]}
    assert sel == {last["doc_id"]: "atif"}
    # insan yerleştirmesi (duzelt) sınır yüzünden düşmez; seçim yenilenince numara değişse de
    # metnin atfı aynı belgeye bağlı kalır (evidence-secim.json atıf eşlemesi)
    other = next(d for d in first if d not in sel)
    _review(ws, {**{d: "kabul" for d in first}, other: "duzelt"})
    R.run(ws, out=out, source=src)
    sel = {s["doc_id"]: s["neden"] for s in _secim(out)["secilen"]}
    assert sel == {other: "insan", last["doc_id"]: "atif"}     # insan sınıra sayılır


def _review(ws: Path, kararlar: dict[str, str], yuva: str = "B.1.1/4") -> None:
    with open(ws / R.REVIEW, "w", encoding="utf-8") as f:
        for d, k in kararlar.items():
            f.write(json.dumps({"satir": f"{d}|{yuva}", "doc_id": d, "olcut": yuva.split("/")[0], "yuva": yuva,
                                "karar": k, "duzelt": {"olcut": None, "yuva": yuva, "asama": None}
                                if k == "duzelt" else None, "etiket": None, "not": ""}) + "\n")


def test_settings_validation(tmp_path):
    (tmp_path / "config.yaml").write_text("rapor:\n  kanit_secimi:\n    en_dusuk_guven: cok\n", encoding="utf-8")
    with pytest.raises(S.SelectionError):
        S.load_settings(tmp_path)
    (tmp_path / "config.yaml").write_text("rapor:\n  kanit_secimi:\n    kurum_geneli_en_fazla: -1\n",
                                          encoding="utf-8")
    with pytest.raises(S.SelectionError):
        S.load_settings(tmp_path)
    s = S.load_settings(None)
    assert (s.olcut_en_fazla, s.kurum_geneli_en_fazla, s.en_dusuk_guven, s.gecmis_en_fazla) == (10, 3, "orta", 1)
    (tmp_path / "config.yaml").write_text("rapor:\n  kanit_secimi:\n    gecmis_kanit_en_fazla: -1\n",
                                          encoding="utf-8")
    with pytest.raises(S.SelectionError):
        S.load_settings(tmp_path)


# -- K20: sürüm ve kopya ----------------------------------------------------------------------

TABLO = ("Program Performans Göstergeleri Tablosu {baslik}\n"
         "Gösterge mezun oranı {a} öğrenci memnuniyeti {b} hedef gerçekleşme {c}\n")


def _tablo(i: str, baslik: str, nums: tuple, tarih=None, grup="sg-tablo", asama="kontrol_et") -> dict:
    t = TABLO.format(baslik=baslik, a=nums[0], b=nums[1], c=nums[2])
    return {"id": i, "text": t, "tarih": tarih, "surum_grubu": grup, "doc_type": "faaliyet_raporu",
            "eslesmeler": [_m("B.1.5", "B.1.5/3" if asama == "kontrol_et" else "B.1.5/1", asama,
                              "Program Performans Göstergeleri")]}


def test_versions_counted_once_latest_representative(tmp_path):
    docs = [_tablo("v1", "2025 yılı 1. çeyrek", (10, 20, 30), "2025-04-02"),
            _tablo("v2", "2025 yılı 1. çeyrek", (11, 20, 30), "2025-04-10"),
            _tablo("v3", "2025 yılı birinci çeyrek", (11, 21, 30), "2025-04-20")]
    ws, src = _ws(tmp_path, docs)
    out = tmp_path / "out"
    st = R.run(ws, out=out, source=src)
    rows = _index(out)
    assert [r["doc_id"] for r in rows] == ["v3"]                 # en güncel temsilci
    assert set(rows[0]["kopyalar"].split("; ")) == {"v1", "v2"}
    assert "surum_temsilcisi" in rows[0]["isaretler"] and "surum_belirsiz" not in rows[0]["isaretler"]
    assert st["surum_birlesen"] == 2 and st["elenen"] == 0
    assert len(build(ws).rows) == 3                              # audit üç eşleşmeyi de görür
    g = (out / "gaps.md").read_text(encoding="utf-8")
    assert "### Tek kanıt sayılan sürümler" in g and "aynı dönem işaretleri" in g


def test_different_quarters_stay_separate(tmp_path):
    docs = [_tablo("q1", "2025 yılı 1. çeyrek", (10, 20, 30), "2025-04-02"),
            _tablo("q2", "2025 yılı 2. çeyrek", (12, 22, 33), "2025-07-02"),
            _tablo("q3", "2025 yılı üçüncü çeyrek", (13, 23, 34), "2025-10-02")]
    ws, src = _ws(tmp_path, docs)
    out = tmp_path / "out"
    R.run(ws, out=out, source=src)
    assert {r["doc_id"] for r in _index(out)} == {"q1", "q2", "q3"}
    assert _secim(out)["surum_birlestirme"] == []


def test_uncertain_version_counted_once_and_flagged(tmp_path):
    docs = [_tablo("u1", "", (10, 20, 30)), _tablo("u2", "", (14, 25, 31))]
    ws, src = _ws(tmp_path, docs)
    out = tmp_path / "out"
    R.run(ws, out=out, source=src)
    rows = _index(out)
    assert len(rows) == 1 and "surum_belirsiz" in rows[0]["isaretler"]
    g = (out / "gaps.md").read_text(encoding="utf-8")
    assert "### Sürümü doğrulanacak belgeler" in g
    # insan üyeyi onaylarsa ayrı kanıt kalır
    other = "u2" if rows[0]["doc_id"] == "u1" else "u1"
    _review(ws, {"u1": "kabul", "u2": "kabul", other: "duzelt"}, yuva="B.1.5/3")
    R.run(ws, out=out, source=src)
    assert {r["doc_id"] for r in _index(out)} == {"u1", "u2"}
    _review(ws, {"u1": "kabul", "u2": "kabul"}, yuva="B.1.5/3")      # yalnız kabul: tek kalır
    R.run(ws, out=out, source=src)
    assert len(_index(out)) == 1
    _review(ws, {"u1": "kabul", "u2": "kabul", other: "duzelt"}, yuva="B.1.5/3")
    R.run(ws, out=out, source=src)
    assert {r["doc_id"] for r in _index(out)} == {"u1", "u2"}


def test_blank_template_and_filled_form_separate(tmp_path):
    bos = ("Öğrenci Memnuniyet Anketi Formu\nDersin içeriği ____ Öğretim elemanı ____ "
           "Ölçme ____ Genel ____\n")
    dolu = ("Öğrenci Memnuniyet Anketi Formu\nDersin içeriği 4,2 Öğretim elemanı 4,5 "
            "Ölçme 3,9 Genel 4,1\n")
    docs = [{"id": "bos", "text": bos, "surum_grubu": "sg-anket", "doc_type": "anket_formu",
             "eslesmeler": [_m("B.1.5", "B.1.5/1", "planla", "Öğrenci Memnuniyet Anketi")]},
            {"id": "dolu", "text": dolu, "surum_grubu": "sg-anket", "doc_type": "anket_formu",
             "eslesmeler": [_m("B.1.5", "B.1.5/4", "uygula", "Öğrenci Memnuniyet Anketi")]}]
    ws, src = _ws(tmp_path, docs)
    out = tmp_path / "out"
    R.run(ws, out=out, source=src)
    assert {r["doc_id"] for r in _index(out)} == {"bos", "dolu"}


def test_relation_unit():
    def v(text, tarih=None, stages=("kontrol_et",), donem=None):
        return S.Version("x", {"tarih": tarih, "akademik_donem": donem or []}, text, frozenset(stages))
    assert S.relation(v("2024-2025 Güz dönemi sonuçları 5"), v("2024-2025 Bahar dönemi sonuçları 5")) \
        == ("ayri", "farkli_donem")
    assert S.relation(v("Mart 2025 tablo 1 2"), v("Mart 2025 tablo 3 4")) == ("ayni", "ayni_donem")
    assert S.relation(v("tablo 1", "2024-05-01"), v("tablo 2", "2025-05-01")) == ("ayri", "farkli_yil")
    assert S.relation(v("tablo 1", "2025-05-01"), v("tablo 2", "2025-06-01")) == ("belirsiz", "donem_belirsiz")
    assert S.relation(v("tablo 1 2"), v("tablo 1 2 ")) == ("ayni", "ayni_veri")
    assert S.relation(v("form", stages=("planla",)), v("form", stages=("uygula",))) \
        == ("ayri", "bos_form_dolu_form")


# -- audit savunmaları: kanıt değil (yürürlükten kalkmış, hariç tür) -----------------------------

def test_defence_flags_not_published_and_listed_with_reason(tmp_path):
    """Audit'in `yururlukten_kalkmis` / `haric_tur` işaretli belgesi yayımlanan listeye girmez
    (atıf ve OD zinciri de aşmaz; insan `kabul`ü de), gaps.md'de nedeniyle görünür."""
    eski = "Staj süresi 20 iş günüdür. Bölüm staj usul ve esasları."
    yeni = ("Staj süresi 30 iş günüdür. Bu usul ve esasların yürürlüğe girmesiyle 12 Mart 2019 tarihli "
            "staj usul ve esasları yürürlükten kalkar.")
    docs = [
        {"id": "eski", "text": eski, "tarih": "2019-03-12", "doc_type": "yonerge", "donem_ici": False,
         "eslesmeler": [_m("B.1.1", "B.1.1/1", "planla", "Staj süresi 20 iş günüdür.")]},
        {"id": "yeni", "text": yeni, "tarih": "2025-03-05", "doc_type": "bolum_kurulu_karari", "donem_ici": True,
         "eslesmeler": [_m("B.1.1", "B.1.1/1", "planla", "Staj süresi 30 iş günüdür.")]},
        {"id": "taslak", "text": "Bölümümüz program uygulamalarını yürütmüştür.", "tarih": "2025-01-15",
         "doc_type": "bidr_raporu", "donem_ici": True,
         "eslesmeler": [_m("B.1.1", "B.1.1/4", "uygula", "Bölümümüz program uygulamalarını yürütmüştür.")]},
    ]
    ws, src = _ws(tmp_path, docs)
    a = build(ws)
    assert "yururlukten_kalkmis" in a.by_key["eski|B.1.1/1"]["flags"]
    assert "haric_tur" in a.by_key["taslak|B.1.1/4"]["flags"]
    out = tmp_path / "out"
    R.run(ws, out=out, source=src)
    assert {r["doc_id"] for r in _index(out)} == {"yeni"}
    el = {e["doc_id"]: e["neden"] for e in _secim(out)["elenen"]}
    assert el == {"eski": "yururlukten_kalkmis", "taslak": "haric_tur"}
    g = (out / "gaps.md").read_text(encoding="utf-8")
    assert S.NEDEN["yururlukten_kalkmis"] in g and S.NEDEN["haric_tur"] in g
    # insan `kabul`ü yürürlükten kaldırmayı ve hariç türü aşmaz (docs/AUDIT.md)
    _review(ws, {"eski": "kabul"}, yuva="B.1.1/1")
    R.run(ws, out=out, source=src)
    assert "eski" not in {r["doc_id"] for r in _index(out)}


def test_donem_disi_reason_unit():
    r = lambda *f: {"flags": list(f)}        # noqa: E731
    assert S.donem_disi([r("yururlukten_kalkmis")]) == "yururlukten_kalkmis"
    assert S.donem_disi([r("donem_sonrasi"), r("surum_donem_sonrasi")]) == "sonra"
    assert S.donem_disi([r("yururlukten_kalkmis", "surum_yururlukten_kalkmis")]) == "yururlukten_kalkmis"
    assert S.donem_disi([r("madde_baska_birim"), r("donem_sonrasi")]) == "madde_baska_birim"
    assert S.donem_disi([r("bilgisiz_ekran"), r("gecmis_kanit")]) == "gecmis"     # bir satır sayılabilir kanıt
    assert S.donem_disi([r("ozgun_kanitsiz")]) == ""                              # destekleyici kalabilir
