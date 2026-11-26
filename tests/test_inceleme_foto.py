"""Fotoğraflar (kullanıcı kararı 2026-11-26): yüklenen fotoğraf bölümün sayılır; mekân fotoğrafı fiziksel koşullar
maddesinde (B.3.1, B.3.3) kanıttır; gerçek fotoğraflar İnceleme'de madde başına (etkinlik/mekân ayrı) bir kez sorulur,
düşük güven ya da betimleme alıntısı tek başına "Bakın" yapmaz; gerçek sorunu olan fotoğraf ve taranmış yazılı belge tek
tek kalır. Bilgi işareti (`etkinlik_gerceklesti`) satırı "Bakın" yapmaz. Sentetik veri."""
from __future__ import annotations

import csv
import json

from openpyxl import load_workbook

from bidr.audit import sade as S
from bidr.audit.run import apply, audit, build, load_review_decisions
from bidr.audit.savunma import Savunma, unit_names
from bidr.audit.sheet import read_review
from bidr.criteria.loader import load_criteria

BAS = "[GÖRSEL BETİMLEME · bidr describe] Bu metindeki \"Betimleme\" bölümleri belgenin kendi yazısı DEĞİLDİR.\n\n"


def _blok(sahne: str, etkinlik: str, kalabalik: str, betimleme: str, yazi: str = "") -> str:
    t = (f"[Betimleme · görsel 1]\nGörsel türü: fotoğraf\nSahne: {sahne}\nEtkinlik: {etkinlik}\n"
         f"Kalabalık: {kalabalik}\n")
    if yazi:
        t += f"Görünen yazı (pano): \"{yazi}\"\n"
    return BAS + t + f"Betimleme: {betimleme}\n"


ETK = _blok("seminer salonunda konuşmacı ve dinleyiciler", "bölüm semineri", "21-50 kişi",
            "Öğrenciler seminer sunumunu dinliyor")
LAB = _blok("bilgisayar laboratuvarı", "yok", "kişi yok", "Bilgisayar laboratuvarında sıralar ve bilgisayarlar")


def _m(olcut, yuva, asama, alinti, guven="orta", od=3):
    return {"olcut": olcut, "yuva": yuva, "asama": asama, "od_onerisi": od, "od_kabul": od, "guven": guven,
            "alinti": alinti, "gerekce": "sentetik", "kabul": True, "denetim": {"red": [], "isaret": []}}


# doc_id: (tür, dosya, metin, eşleşmeler, ince ek alanları, belge ek alanları)
DOCS = {
    "p1": ("fotograf", "Etkinlik/sem-1.jpg", ETK, [_m("B.3.5", "B.3.5/2", "uygula", "Öğrenciler seminer sunumunu dinliyor",
                                                     "dusuk")], {}, {}),
    "p2": ("fotograf", "Etkinlik/sem-2.jpg", ETK, [_m("B.3.5", "B.3.5/2", "uygula", "Öğrenciler seminer sunumunu dinliyor")],
           {}, {}),
    "p3": ("fotograf", "Olanak/lab.jpg", LAB, [_m("B.3.1", "B.3.1/1", "uygula", "Bilgisayar laboratuvarında sıralar")],
           {}, {}),
    "p4": ("fotograf", "Olanak/lab2.jpg", LAB, [_m("A.1.5", "A.1.5/2", "uygula", "Bilgisayar laboratuvarında sıralar")],
           {}, {}),
    # model kurum geneli dedi: fotoğraf bölümün sayılır (soru yok, OD2 tavanı kalkar)
    "p5": ("fotograf", "Etkinlik/sem-3.jpg", ETK, [{**_m("B.3.5", "B.3.5/2", "uygula",
                                                       "Öğrenciler seminer sunumunu dinliyor"), "od_kabul": 2, "denetim":
                                                    {"red": [], "isaret": ["uygulama_kaniti_eksik"]}}],
           {"birim_iliskisi": "kurum_geneli"}, {}),
    # taranmış yazılı belge (tür bilinmiyor, görsel dosya): grup dışında, tek tek
    "s1": ("bilinmiyor", "Tarama/yazi.jpg", ETK, [_m("B.3.5", "B.3.5/2", "uygula", "Öğrenciler seminer sunumunu dinliyor",
                                                    "dusuk")], {}, {}),
    # "fotograf" türünde PDF: gerçek fotoğraf değil (faaliyet.dosya.fotograf_mi ile aynı tanım)
    "x1": ("fotograf", "Belge/ekran.pdf", ETK, [_m("B.3.5", "B.3.5/2", "uygula", "Öğrenciler seminer sunumunu dinliyor",
                                                  "dusuk")], {}, {}),
}


def _ws(tmp_path):
    w = tmp_path / "ws"
    (w / "text").mkdir(parents=True)
    inv = []
    with open(w / "decisions.jsonl", "w", encoding="utf-8") as f, \
            open(w / "documents.jsonl", "w", encoding="utf-8") as g:
        for did, (tur, yol, metin, ms, ince, belge) in DOCS.items():
            (w / "text" / f"{did}.txt").write_text(metin, encoding="utf-8")
            f.write(json.dumps({"doc_id": did, "durum": "ok", "asama": "ince", "karar": "olcut_var", "eslesmeler": ms,
                                "ince": {"karar": "olcut_var", "gerekce": "", **ince}}, ensure_ascii=False) + "\n")
            g.write(json.dumps({"doc_id": did, "doc_type": tur, "calisma_adi": did, **belge}, ensure_ascii=False) + "\n")
            inv.append({"doc_id": did, "sha256": did * 8, "rel_path": yol, "ext": yol.rsplit(".", 1)[-1], "status": "ok",
                        "dup_of": ""})
    with open(w / "inventory.csv", "w", encoding="utf-8", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=list(inv[0]))
        wr.writeheader()
        wr.writerows(inv)
    return w


def _sade(a):
    return {x["satir"]: x for x in S.inceleme_satirlari(a, load_criteria())}


def test_bilgi_isareti_bakin_yapmaz():
    r = {"flags": ["etkinlik_gerceklesti"], "sayilir": True, "od": 3, "vurgu": "etkinlik dosyasında gerçekleşme var"}
    assert S.dikkat(r, 2025) == ([], False)
    r["flags"] = ["elle_eslesme"]
    assert S.dikkat(r, 2025) == ([], False)


def test_fotograflar_gruplanir_sorunlu_ve_taranmis_tek_tek(tmp_path):
    a = build(_ws(tmp_path))
    by = a.by_key
    assert {did: by[f"{did}|{ms[0]['yuva']}"]["foto"] for did, (_, _, _, ms, _, _) in DOCS.items()} == {
        "p1": "etkinlik", "p2": "etkinlik", "p3": "mekan", "p4": "mekan", "p5": "etkinlik", "s1": "", "x1": ""}
    x = _sade(a)
    g = {k: v["grup"] for k, v in x.items()}
    assert g["p1|B.3.5/2"] == g["p2|B.3.5/2"] == g["p5|B.3.5/2"] == "#foto:B.3.5:etkinlik"
    assert g["p3|B.3.1/1"] == "#foto:B.3.1:mekan" and g["p4|A.1.5/2"] == "#foto:A.1.5:mekan"
    for k in ("p1|B.3.5/2", "p3|B.3.1/1", "p4|A.1.5/2"):
        assert x[k]["bolum"] == S.FOTO_BOLUM and x[k]["oneri"] == "Kabul"
    # düşük güvenli fotoğrafın satırında düşük güven/betimleme uyarısı yok (grup bir kez sorulur)
    assert "emin değil" not in x["p1|B.3.5/2"]["dikkat"] and "betimlemesi" not in x["p1|B.3.5/2"]["dikkat"]
    # taranmış yazılı belge ve fotoğraf türlü PDF: tek tek, "Bakın"
    for k in ("s1|B.3.5/2", "x1|B.3.5/2"):
        assert x[k]["bolum"] == 1 and x[k]["oneri"] == "Bakın" and not x[k]["grup"]
    # fiziksel koşullar maddesinde mekân fotoğrafı sayılır; başka maddede planla
    assert "fotograf_fiziksel" in by["p3|B.3.1/1"]["flags"] and by["p3|B.3.1/1"]["etkin_asama"] == "uygula"
    assert "fotograf_mekan" in by["p4|A.1.5/2"]["flags"] and by["p4|A.1.5/2"]["etkin_asama"] == "planla"
    # kurum geneli denen fotoğraf bölümün: soru yok, tavan kalktı
    p5 = by["p5|B.3.5/2"]
    assert p5["birim_iliskisi"] == "kendi" and "kurum_geneli" not in p5["flags"] and p5["od"] == 3
    assert "birim_varsayildi" in p5["flags"]


def test_grup_karari_gidis_donus_ve_apply(tmp_path):
    w = _ws(tmp_path)
    a, paths = audit(w)
    wb = load_workbook(paths["xlsx"])
    sh = wb[S.SH_INC]
    head = [c.value for c in sh[1]]
    col = {k: head.index(h) + 1 for k, h, _, _ in S.INC_COLS}
    basliklar = {}
    for r in range(2, sh.max_row + 1):
        sid = str(sh.cell(r, col["satir"]).value or "")
        if sid.startswith(S.FOTO_ON):
            basliklar[sid] = r
        if sid == "p2|B.3.5/2":
            sh.cell(r, col["karar"], "Ret")                    # tek tek verilen karar grup kararından önce gelir
    assert set(basliklar) == {"#foto:B.3.5:etkinlik", "#foto:B.3.1:mekan", "#foto:A.1.5:mekan"}
    assert "Etkinlik fotoğrafları" in sh.cell(basliklar["#foto:B.3.5:etkinlik"], 1).value
    sh.cell(basliklar["#foto:B.3.5:etkinlik"], col["karar"], S.FOTO_KABUL)
    sh.cell(basliklar["#foto:B.3.1:mekan"], col["karar"], S.FOTO_TEK)
    wb.save(paths["xlsx"])
    _, rows = read_review(paths["xlsx"])
    d = {r["satir"]: r for r in rows}
    assert d["p1|B.3.5/2"]["karar"] == d["p5|B.3.5/2"]["karar"] == "kabul" and S.FOTO_NOT in d["p1|B.3.5/2"]["not"]
    assert d["p2|B.3.5/2"]["karar"] == "ret"
    assert not d["p3|B.3.1/1"]["karar"] and not d["p4|A.1.5/2"]["karar"]   # tek tek / kararsız grup: değişiklik yok
    assert not d["s1|B.3.5/2"]["karar"]                                       # grup dışı satıra dokunulmaz
    st = apply(w)
    assert not st["gecersiz"]
    dec = load_review_decisions(w)
    assert dec["p1|B.3.5/2"]["karar"] == "kabul" and dec["p2|B.3.5/2"]["karar"] == "ret" and "p3|B.3.1/1" not in dec
    # kabul edilen düşük güvenli fotoğraf artık sayılır; yeni tabloda 3. bölüm
    a2, _ = audit(w)
    assert not a2.by_key["p1|B.3.5/2"]["zayif"] and _sade(a2)["p1|B.3.5/2"]["bolum"] == 3
    # geçersiz grup değeri: grubun kararsız satırları hata olur
    wb = load_workbook(paths["xlsx"])
    sh = wb[S.SH_INC]
    for r in range(2, sh.max_row + 1):
        if sh.cell(r, col["satir"]).value == "#foto:A.1.5:mekan":
            sh.cell(r, col["karar"], "Belki")
    wb.save(paths["xlsx"])
    _, rows = read_review(paths["xlsx"])
    assert "geçersiz" in next(r for r in rows if r["satir"] == "p4|A.1.5/2")["sade_hata"]


def test_fotografta_baska_birim_yalniz_gorunen_yazidan(tmp_path):
    w = tmp_path / "w"
    (w / "text").mkdir(parents=True)
    anlatim = _blok("Fizik Bölümü binası önünde öğrenciler", "yok", "6-20 kişi", "Fizik Bölümü binası önü")
    gorunen = _blok("bina girişi", "yok", "kişi yok", "giriş", yazi="Fizik Bölümü")
    for did, t in (("a", anlatim), ("b", gorunen), ("c", anlatim)):
        (w / "text" / f"{did}.txt").write_text(t, encoding="utf-8")
    docs = {"a": {"doc_type": "fotograf"}, "b": {"doc_type": "fotograf"}, "c": {"doc_type": "resmi_yazi"}}
    sv = Savunma(w, "Örnek Bölümü", birim_adlari=unit_names(["Örnek Bölümü", "Fizik Bölümü"]), docs=docs)
    assert sv.other_unit("a") == []                 # modelin anlatımı: aitlik sorusu doğurmaz
    assert sv.other_unit("b") == ["fizik"]          # görüntüde okunan yazı: açık başka birim
    assert sv.other_unit("c") == ["fizik"]          # fotoğraf olmayan belge: kural değişmedi
