"""Etkinlik dosyası ve planlama kanıtı (yol haritası Faz 1 madde 9). Yalnız sentetik veri."""
from __future__ import annotations

import json

from bidr.decide import run as R
from bidr.faaliyet import dosya as D
from bidr.faaliyet import run as F
from bidr.ihtiyac import rapor as IR
from bidr.llm.quote import verify_quote

from synth import make_ws
from test_ihtiyac import _m, _metin
from test_ihtiyac import _ws as _ws_ihtiyac

AFIS = "SENTETIK BOLUMU\nUlusal Staj Programi\nAcilis: 1 Temmuz 2026\nHerkes davetlidir."
FOTO = "[Görsel betimleme]\nGörsel türü: fotoğraf\nSahne: bir salonda konuşma yapan kişi ve dinleyiciler\n"
LAB = "[Görsel betimleme]\nGörsel türü: fotoğraf\nSahne: boş bir laboratuvar, cihazlar ve masalar\n"


def _jsonl(p, rows):
    p.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def _ince(did, faaliyet=None, alan=None, karar="olcut_var", eslesmeler=()):
    ince = {"karar": karar, "birim_iliskisi": "kendi", "faaliyet": faaliyet}
    if alan:
        ince[D.ALAN] = alan
    return {"doc_id": did, "durum": "ok", "asama": "ince", "karar": karar, "kaba": {"secilen": ["D.1.1"]},
            "ince": ince, "eslesmeler": list(eslesmeler)}


def _kaba(did):
    return {"doc_id": did, "durum": "ok", "asama": "kaba", "kaba": {"secilen": ["D.1.1", "B.3.5"]}}


def _ws(tmp_path, recs_fn=None):
    docs = [{"id": "afis", "text": AFIS, "path": "Etkinlikler/Ulusal Staj/ulusal staj afis.pdf"},
            {"id": "foto1", "text": FOTO, "path": "Etkinlikler/Ulusal Staj/ulusal staj 2026-1.jpg"},
            {"id": "foto2", "text": FOTO, "path": "Etkinlikler/Ulusal Staj/ulusal staj 2026-2.jpg"},
            {"id": "yalniz", "text": FOTO, "path": "Diger/IMG.jpg"},
            {"id": "lab", "text": LAB, "path": "Diger/lab.jpg"},
            {"id": "kok", "text": FOTO, "path": "foto 1.jpg"}]
    root = make_ws(tmp_path / "ws", docs)
    _jsonl(root / "documents.jsonl", [
        {"doc_id": "afis", "doc_type": "etkinlik_duyurusu", "tarih": "2026-07-01"},
        *({"doc_id": d, "doc_type": "fotograf", "tarih": "2026-07-03"} for d in ("foto1", "foto2", "yalniz",
                                                                                 "lab", "kok"))])
    afis_f = {"ad": "Ulusal Staj Programı", "tarih": "2026-07-01", "asama": "duyuru"}
    recs = [_ince("afis", afis_f), _kaba("foto1"), _kaba("foto2"), _kaba("yalniz"), _kaba("lab"), _kaba("kok")]
    if recs_fn:
        recs = recs_fn(recs)
    _jsonl(root / "decisions.jsonl", recs)
    return root


def test_series_key_and_groups(tmp_path):
    assert D.seri_koku("A/ulusal staj 2026-1.jpg") == D.seri_koku("A/ulusal staj 2026-5.jpg") == "ulusal staj 2026"
    assert D.seri_koku("A/afis (2).png") == "afis"
    assert D.seri_koku("A/afis.png") is None and D.seri_koku("A/12.jpg") is None
    paths = {"a": "E/gezi 1.jpg", "b": "E/gezi 2.jpg", "c": "F/gezi 3.jpg", "d": "gezi 4.jpg", "e": "E/x 5.jpg"}
    assert D.gruplar(paths, {}, {}) == [["a", "b"]]            # başka klasör ve kök klasör gruplanmaz
    # aynı klasör + yakın tarih: fotoğraf ile faaliyet adı taşıyan belge
    paths = {"p": "E/poster.pdf", "f": "E/foto.jpg", "g": "E/uzak.jpg"}
    docs = {"f": {"doc_type": "fotograf", "tarih": "2026-07-05"}, "g": {"doc_type": "fotograf", "tarih": "2026-09-01"}}
    recs = {"p": _ince("p", {"ad": "Kariyer Günü", "tarih": "2026-07-01", "asama": "duyuru"})}
    assert D.gruplar(paths, docs, recs) == [["f", "p"]]


def test_photo_package_gets_event_hint_and_decision_records_it(tmp_path):
    root = _ws(tmp_path)
    ctx = R.Context.load(root, profile=None)
    recs = R.load_decisions(ctx.ws)
    inp, meta = R.fine_inputs(ctx, "foto1", recs["foto1"])
    assert "etkinlik dosyası adayı" in inp["belge_bilgisi"] and "«Ulusal Staj Programı» (2026-07-01, duyuru)" \
        in inp["belge_bilgisi"]
    assert meta[D.ALAN] == ["afis"]
    # afişin kendisine, gruba bağlanmayan ve kök klasördeki fotoğrafa ipucu yok
    for did in ("afis", "yalniz", "kok"):
        rec = recs[did] if did != "afis" else {**recs["afis"], "asama": "kaba"}
        i, m = R.fine_inputs(ctx, did, rec)
        assert "etkinlik dosyası" not in i["belge_bilgisi"] and D.ALAN not in m
    out = {"karar": "olcut_yok", "birim_iliskisi": "kendi", "kanit_adi": "Ulusal Staj Fotoğrafı",
           "faaliyet": {"ad": "Ulusal Staj Programı", "tarih": "2026-07-01", "asama": "gerceklesme"},
           "eslesmeler": [], "gerekce": ""}
    rec = R.apply_fine(ctx, "foto1", recs["foto1"], out, meta, "m", lambda q, t: verify_quote(q, t))
    assert rec["ince"][D.ALAN] == ["afis"]


def test_hint_is_stable_and_not_chained(tmp_path):
    """Kendi içeriğinden faaliyet adı almış fotoğrafın paketi değişmez; ipucuyla karar almış fotoğraf başka
    fotoğrafa kaynak olmaz (zincir yok), kendi paketi ipucuyla aynı kalır (yeniden karar döngüsü yok)."""
    kendi = {"ad": "Staj Açılışı", "tarih": "2026-07-03", "asama": "gerceklesme"}
    ipuclu = {"ad": "Ulusal Staj Programı", "tarih": "2026-07-01", "asama": "gerceklesme"}

    def recs_fn(recs):
        return [r if r["doc_id"] not in ("foto1", "foto2") else
                (_ince("foto1", kendi) if r["doc_id"] == "foto1" else _ince("foto2", ipuclu, alan=["afis"]))
                for r in recs]
    root = _ws(tmp_path, recs_fn)
    ctx = R.Context.load(root, profile=None)
    recs = R.load_decisions(ctx.ws)
    i1, m1 = R.fine_inputs(ctx, "foto1", recs["foto1"])
    assert "etkinlik dosyası" not in i1["belge_bilgisi"]                       # kendi adı var: ipucu yok
    i2, m2 = R.fine_inputs(ctx, "foto2", recs["foto2"])
    assert m2[D.ALAN] == ["afis", "foto1"]                                     # foto1 kaynak (kendi içeriği)
    h = D.yukle(root)
    assert all(x["doc_id"] != "foto2" for xs in h.values() for x in xs)        # ipuçlu karar kaynak değil


def test_activity_file_series_merge_and_contextless_photos(tmp_path):
    def recs_fn(recs):
        out = []
        for r in recs:
            if r["doc_id"] == "foto1":
                r = _ince("foto1", {"ad": "Ulusal Staj 2026-1", "tarih": "2026-07-03", "asama": "gerceklesme"})
            elif r["doc_id"] == "foto2":
                r = _ince("foto2", {"ad": "Ulusal Staj 2026-2", "tarih": "2026-07-03", "asama": "gerceklesme"})
            elif r["doc_id"] in ("yalniz", "lab", "kok"):
                r = _ince(r["doc_id"], None, karar="olcut_yok")
            out.append(r)
        return out
    root = _ws(tmp_path, recs_fn)
    dest, data = F.run(root)
    by = {b["doc_id"]: k for k in data["faaliyetler"] for b in k["belgeler"]}
    assert by["foto1"] is by["foto2"]                    # ad sayısı farklı ama aynı dosya serisi
    assert by["foto1"]["durum"] == "gerceklesme_kanitli" and all("seri" not in b for b in by["foto1"]["belgeler"])
    assert {x["doc_id"] for x in data["baglamsiz_fotograflar"]} == {"yalniz", "lab", "kok"}
    # hat denetimi (bidr/pipeline/checks.py) aynı kurulumla karşılaştırır
    assert json.loads(dest.read_text(encoding="utf-8")) == json.loads(json.dumps(F.build_ws(R.Workspace(root))))


def test_poster_is_planning_and_realised_event_counts_as_implementation(tmp_path):
    from bidr.audit.savunma import Savunma
    foto = {"doc_id": "foto1", "asama": "gerceklesme", "eslesmeler": [{"olcut": "D.1.1", "yuva": "D.1.1/3"}]}
    fk = {"id": "F001", "ad": "Ulusal Staj Programı", "durum": "gerceklesme_kanitli", "yalniz_duyuru": False,
          "belgeler": [{"doc_id": "afis", "asama": "duyuru", "eslesmeler": []}, foto]}
    m = {"olcut": "D.1.1", "yuva": "D.1.1/3", "alinti": "Ulusal Staj Programi Acilis: 1 Temmuz 2026"}
    root = _ws(tmp_path)
    sv = Savunma.load(root, {}, None)
    sv.fmap = {"afis": (fk, "duyuru")}
    rec = R.load_decisions(R.Workspace(root))["afis"]
    out = sv.row(rec, m, "etkinlik_duyurusu", "planla", human=False)
    assert out["etkin"] == "uygula" and "etkinlik_gerceklesti" in out["flags"]
    sv.fmap = {"afis": ({**fk, "durum": "gerceklesme_kanitsiz", "yalniz_duyuru": True}, "duyuru")}
    out = sv.row(rec, m, "etkinlik_duyurusu", "uygula", human=False)
    assert out["etkin"] == "planla" and out["sayilir"] is not False          # planlama kanıtı, kanıt dışı değil
    sv.fmap = {"afis": (fk, "duyuru")}
    out = sv.row(rec, {**m, "yuva": "D.1.1/2"}, "etkinlik_duyurusu", "planla", human=False)
    assert out["etkin"] == "planla"                                          # yuva yalnız planlama
    # gerçekleşme kanıtı başka ölçütte: afiş kendi ölçütünde planlama kalır (OD şişmez)
    sv.fmap = {"afis": ({**fk, "belgeler": [{**foto, "eslesmeler": [{"olcut": "B.3.5", "yuva": "B.3.5/2"}]}]},
                        "duyuru")}
    out = sv.row(rec, m, "etkinlik_duyurusu", "planla", human=False)
    assert out["etkin"] == "planla" and "etkinlik_gerceklesti" not in out["flags"]
    # aynı ölçütteki gerçekleşme eşleşmesi incelemede reddedildiyse de planlama
    (root / "review-decisions.jsonl").write_text(json.dumps({"satir": "foto1|D.1.1/3", "karar": "ret"}) + "\n",
                                                 encoding="utf-8")
    sv = Savunma.load(root, {}, None)
    sv.fmap = {"afis": (fk, "duyuru")}
    assert sv.row(rec, m, "etkinlik_duyurusu", "planla", human=False)["etkin"] == "planla"


def test_prompt_and_principle_accept_posters():
    from bidr.decide.prompt import evidence_principles
    p = evidence_principles()
    assert "yalnız duyuru" in p and "planla" in p and "etkinlik dosyası adayı" in p
    v = (R.TASKS_DIR / "verify_text" / "prompt.md").read_text(encoding="utf-8")
    assert "planlanmış/duyurulmuştur" in v
    assert R.task_version(R.FINE) == "10" and R.task_version("verify_text") == "4"     # sürüm artmadı


T1 = _metin("SENTETIK BELGE", "korvane", "lispat", "durmeko", "faslin", "gortev")


def _metinler(res, cid):
    r = {x["olcut"]: x for x in res["sade"]}.get(cid)
    return [m["metin"] for m in r["maddeler"]] if r else []


def _sade(res, cid):
    return {r["olcut"]: r for r in res["sade"]}.get(cid)


def _hedef(tmp_path, docs):
    return _ws_ihtiyac(tmp_path / "guncel", 2026, docs)


# -- etkinlik adıyla istekler (madde 9) -----------------------------------------------------------

def _faaliyetli(tmp_path, ekle: dict):
    """Afiş (B.3.5) + ilgisiz kurul kararı; `ekle`: doc_id → (tür, faaliyet, yol) ek belgeler."""
    docs = {"afis": ("etkinlik_duyurusu", True, "2026-03-01", "Kultur Konusmalari I Afisi", T1,
                     [_m("B.3.5", "B.3.5/1", "planla", 2)], "kabul")}
    ws = _hedef(tmp_path, docs)
    fa = {"afis": {"ad": "Kültür Konuşmaları I", "tarih": "2026-03-12", "asama": "duyuru"}, **{
        k: v[1] for k, v in ekle.items()}}
    recs = [json.loads(x) for x in (ws / "decisions.jsonl").read_text(encoding="utf-8").splitlines()]
    with open(ws / "documents.jsonl", "a", encoding="utf-8") as f:
        for k, (t, _, _) in ekle.items():
            f.write(json.dumps({"doc_id": k, "doc_type": t, "tarih": "2026-03-12"}) + "\n")
            (ws / "text" / f"{k}.txt").write_text("[Görsel betimleme]\nGörsel türü: fotoğraf\nSahne: konuşmacı ve "
                                                  "dinleyiciler\n", encoding="utf-8")
            recs.append({"doc_id": k, "durum": "ok", "asama": "ince", "karar": "olcut_yok", "eslesmeler": [],
                         "ince": {"karar": "olcut_yok", "birim_iliskisi": "kendi"}})
    for r in recs:
        r["ince"]["birim_iliskisi"] = "kendi"
        r["ince"]["faaliyet"] = fa.get(r["doc_id"])
    (ws / "decisions.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs),
                                        encoding="utf-8")
    inv = ["doc_id,rel_path"] + [f"{k},{v[2]}" for k, v in ekle.items()] + ["afis,Etkinlik/kultur afis.pdf"]
    (ws / "inventory.csv").write_text("\n".join(inv) + "\n", encoding="utf-8")
    return ws


def test_etkinlik_gerceklesme_istegi_adiyla(tmp_path):
    ws = _faaliyetli(tmp_path, {"bos": ("fotograf", None, "Diger/IMG_1.jpg")})
    res = IR.run(ws, out=tmp_path / "o")
    m = _metinler(res, "B.3.5")
    assert m[0] == ("«Kültür Konuşmaları I (2026-03-12)» etkinliğinin gerçekleştiğini gösteren fotoğraf, haber, "
                    "sosyal medya paylaşımı ya da katılım listesi")
    r = _sade(res, "B.3.5")
    assert r["maddeler"][0]["dosyada"] == "planlama: Kultur Konusmalari I Afisi"
    assert "etkinlikleri adıyla" in r["neden"]
    g = _metinler(res, "Genel")
    assert g == ["Bu fotoğraf hangi etkinliğe ait? Belgeler sayfasında belge notu yazın: Diger/IMG_1.jpg"]


def test_etkinlik_gerceklesmisse_istek_yok_ve_gruba_bagli_fotograf_sorulmaz(tmp_path):
    ws = _faaliyetli(tmp_path, {
        "foto": ("fotograf", {"ad": "Kültür Konuşmaları I", "tarih": "2026-03-12", "asama": "gerceklesme"},
                 "Etkinlik/kultur 1.jpg"),
        "foto2": ("fotograf", None, "Etkinlik/kultur 2.jpg")})        # aynı seri: etkinlik dosyasında
    res = IR.run(ws, out=tmp_path / "o")
    assert not any("gerçekleştiğini" in m for m in _metinler(res, "B.3.5"))
    assert not _metinler(res, "Genel")


def test_etkinlik_mi_yalniz_gercek_etkinlik_turleri():
    from bidr.ihtiyac.etkinlik import etkinlik_mi
    for ad in ("Iraksak Seriler Semineri", "Ulusal Staj Programı 2026", "Bilim Şenliği", "Matematik Kulübü Söyleşisi",
               "Tercih Günü Tanıtım Standı", "COVER Çalıştayı", "Kültür Konuşmaları I", "Temel Bilimler Festivali"):
        assert etkinlik_mi(ad), ad
    for ad in ("Bölüm Kurulu Toplantısı 2026-3", "Kalite Komisyonu Toplantısı", "Lise İş Birliği Protokolü İmzası",
               "Erasmus Anlaşması", "Öğrenci Temsilcisi Seçimleri", "Lisansüstü Giriş Mülakatları",
               "Uluslararası Kongre Katılımı", "Yönetimin Gözden Geçirmesi Toplantısı"):
        assert not etkinlik_mi(ad), ad


def test_etkinlik_istekleri_daralir_ve_madde_basina_birlesir(tmp_path):
    """Gerçekleşme isteği yalnız bölümün gerçek etkinliklerine; aynı maddedeki etkinlikler tek satırda."""
    def d(ad):
        return ("etkinlik_duyurusu", True, "2026-03-01", ad, T1, [_m("B.3.5", "B.3.5/1", "planla", 2)], "kabul")
    ws = _hedef(tmp_path, {"s1": d("Seminer A Afisi"), "s2": d("Seminer B Afisi"), "pr": d("Protokol Imza Duyurusu"),
                           "ku": d("Kurum Bilim Senligi Duyurusu")})
    fa = {"s1": ("Sayılar Kuramı Semineri", "2026-03-12", "kendi"), "s2": ("Topoloji Semineri", "2026-04-02", "kendi"),
          "pr": ("Lise İş Birliği Protokolü İmzası", "2026-03-20", "kendi"),
          "ku": ("Kampüs Bilim Şenliği", "2026-05-05", "kurum_geneli")}
    recs = [json.loads(x) for x in (ws / "decisions.jsonl").read_text(encoding="utf-8").splitlines()]
    for r in recs:
        ad, t, bi = fa[r["doc_id"]]
        r["ince"].update({"birim_iliskisi": bi, "faaliyet": {"ad": ad, "tarih": t, "asama": "duyuru"}})
    (ws / "decisions.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs),
                                        encoding="utf-8")
    res = IR.run(ws, out=tmp_path / "o")
    e = [m for m in _sade(res, "B.3.5")["maddeler"] if m["tur"] == "etkinlik"]
    assert [m["metin"] for m in e] == [
        "Şu etkinliklerin gerçekleştiğini gösteren fotoğraf, haber, sosyal medya paylaşımı ya da katılım listesi: "
        "«Sayılar Kuramı Semineri (2026-03-12)», «Topoloji Semineri (2026-04-02)»"]
    assert e[0]["dosyada"] == ("planlama: Sayılar Kuramı Semineri (2026-03-12): Seminer A Afisi · "
                               "Topoloji Semineri (2026-04-02): Seminer B Afisi")
    assert not any("Protokol" in m["metin"] or "Şenliği" in m["metin"] for r in res["sade"] for m in r["maddeler"])
