"""Belgeler arası açık atıf ("dayanır" bağı) ve PUKÖ zinciri (bidr/faaliyet/atif.py, bidr/audit/puko.py).
Yalnız sentetik veri; model yok. Kurallar: docs/AUDIT.md "PUKÖ zinciri"."""
from __future__ import annotations

import json

from bidr.audit.run import audit, build
from bidr.faaliyet import atif as A

from test_audit_od import _c, _m, _ws

YAZI = ("Evrak Tarih ve Sayısı: 27.01.2025-E.111222\n\nÖRNEK ÜNİVERSİTESİ\nÖrnek Bölümü Başkanlığı\n"
        "Sayı : E-12345678-770-111222                         27.01.2025\nKonu : Açılacak Seçmeli Dersler\n\n"
        "Bölümümüzde açılacak olan ÖRN 401 ve ÖRN 402 derslerinin dış paydaş görüşleri ve anket\n"
        "komisyonu kararı doğrultusunda hazırlanan içerikleri ekte verilmiştir.\n")
KURUL = ("ÖRNEK FAKÜLTESİ KURUL KARARLARI\n\nKARAR-25/01: Fakültemiz Örnek Bölümü Başkanlığının 27.01.2025 tarih\n"
         "ve E.111222 sayılı yazısı görüşüldü. ÖRN 401 ve ÖRN 402 derslerinin açılmasına karar verilmiştir.\n")
ANKET = ("Örnek Bölümü anket komisyonu toplantısı. Seçmeli ders anketi sonuçları değerlendirilmiş, "
         "öğrencilerin yeni seçmeli ders talep ettiği belirlenmiştir.")


def _rec(id_, ad, tarih, belgeler, asama="degerlendirme"):
    return {"id": id_, "ad": ad, "adlar": [ad], "tarih": tarih, "tarih_araligi": [tarih, tarih],
            "durum": "gerceklesme_dolayli", "yalniz_duyuru": False, "asamalar": {asama: list(belgeler)},
            "eksik": [], "belgeler": [{"doc_id": d, "asama": asama} for d in belgeler]}


# -- atıf çıkarımı ----------------------------------------------------------------------------

def test_number_citation_links_to_own_header():
    docs = {"yazi": {"text": YAZI, "tarih": "2025-01-27"}, "kurul": {"text": KURUL, "tarih": "2025-02-03"},
            "baska": {"text": "Sayı : E-1-999111\n27.01.2025\nBaşka yazı.", "tarih": "2025-01-27"}}
    bag, _ = A.links(docs, [])
    assert [(b["kaynak"], b["hedef"], b["tur"]) for b in bag] == [("kurul", ["yazi"], "sayi")]
    assert "27.01.2025 tarih ve E.111222 sayılı yazısı görüşüldü" in bag[0]["atif"]
    # tarih tutmuyorsa (aynı sayı, başka gün) bağ yok
    docs["kurul"]["text"] = KURUL.replace("27.01.2025", "28.01.2025")
    assert A.links(docs, [])[0] == []


def test_named_reference_needs_unique_prior_activity():
    docs = {"yazi": {"text": YAZI, "tarih": "2025-01-27"}}
    f1 = _rec("F001", "Bölüm Anket Komisyonu Toplantısı", "2025-01-14", ["anket"])
    bag, notlar = A.links(docs, [f1])
    assert [(b["kaynak"], b["hedef"], b["faaliyet"], b["tur"]) for b in bag] == [("yazi", ["anket"], "F001", "ad")]
    # gelecekteki ya da pencere dışındaki faaliyet: bağ yok
    assert A.links(docs, [_rec("F001", "Bölüm Anket Komisyonu Toplantısı", "2025-02-14", ["anket"])])[0] == []
    assert A.links(docs, [_rec("F001", "Bölüm Anket Komisyonu Toplantısı", "2024-01-14", ["anket"])])[0] == []
    # iki aday: tahmin yok, not düşer
    f2 = _rec("F002", "Anket Komisyonu Toplantısı", "2025-01-20", ["anket2"])
    bag, notlar = A.links(docs, [f1, f2])
    assert bag == [] and notlar and "F001, F002" in notlar[0]


def test_named_reference_rejects_generic_mentions():
    f = _rec("F001", "Fakülte Yönetim Kurulu Toplantısı", "2025-01-10", ["fyk"])
    for t in ("Fakülte Kurulu, Fakülte Yönetim Kurulu ve danışma kurullarının değerlendirmeleri "
              "doğrultusunda güncellemeler yapılmaktadır.",          # türsüz sayım, genel anma
              "Fakülte yönetim kurullarının kararları doğrultusunda işlem yapılır.",    # çoğul: genel
              "Dersler anket sonuçlarına göre güncellenmiştir."):     # ad tutmuyor
        assert A.links({"d": {"text": t, "tarih": "2025-02-01"}}, [f])[0] == [], t
    ok = "Fakülte Yönetim Kurulu kararı doğrultusunda ders açılmıştır."
    assert A.links({"d": {"text": ok, "tarih": "2025-02-01"}}, [f])[0][0]["faaliyet"] == "F001"


def test_reach_follows_chain():
    bag = [{"kaynak": "kurul", "hedef": ["yazi"], "faaliyet": None, "tur": "sayi", "atif": "a"},
           {"kaynak": "yazi", "hedef": ["anket", "anket2"], "faaliyet": "F001", "tur": "ad", "atif": "b"}]
    r = A.reach(bag, "kurul")
    assert set(r) == {"yazi", "anket", "anket2"} and [b["atif"] for b in r["anket"]] == ["a", "b"]
    assert A.reach(bag, "anket") == {}


# -- audit: izleme → önlem halkası ----------------------------------------------------------------

def _docs(yazi=YAZI, anket_asama="kontrol_et", kurul_b12=False):
    kurul = [_m("B.1.5", "B.1.5/2", "uygula", "derslerinin açılmasına karar verilmiştir")]
    if kurul_b12:                       # modelin aynı belgeden B.1.2/3 eşleşmesi (insan reddedecek)
        kurul.append(_m("B.1.2", "B.1.2/3", "uygula", "derslerinin açılmasına karar verilmiştir"))
    return {
        "plan": ("bolum_kurulu_karari", "2025-01-05", "Örnek Bölümü kurulunda seçmeli ders havuzu "
                 "uygulanmış, ÖRN 300 dersi okutulmuştur.",
                 [_m("B.1.2", "B.1.2/2", "uygula", "ÖRN 300 dersi okutulmuştur")]),
        "anket": ("komisyon_tutanagi", "2025-01-14", ANKET,
                  [_m("A.4.2", "A.4.2/2", "uygula", "Seçmeli ders anketi sonuçları değerlendirilmiş"),
                   _m("B.1.2", "B.1.2/4", anket_asama, "Seçmeli ders anketi sonuçları değerlendirilmiş")]),
        "yazi": ("resmi_yazi", "2025-01-27", yazi, []),
        "kurul": ("fakulte_kurulu_karari", "2025-02-03", KURUL,
                  kurul, "ust_birim_bu_birim_hakkinda"),
    }


FA = {"sema": 1, "faaliyetler": [_rec("F001", "Bölüm Anket Komisyonu Toplantısı", "2025-01-14", ["anket"])]}


def test_chain_completes_onlem_link(tmp_path):
    w = _ws(tmp_path, _docs(), faaliyet=FA)
    a, paths = audit(w, out=tmp_path / "out")
    for cid, yuva in (("A.4.2", "A.4.2/3"), ("B.1.2", "B.1.2/3")):
        r = a.by_key[f"kurul|{yuva}"]
        assert r["etkin_asama"] == "onlem_al" and r["sayilir"] and "puko_zinciri" in r["flags"]
        assert "E.111222 sayılı yazısı" in r["alinti"]
        c = _c(a, cid)
        assert c["zincir"]["onlem_al"]["durum"] == "var" and c["zincir"]["kontrol_et"]["durum"] in ("var", "dusuk", "yok")
        z = c["puko_zinciri"][0]
        assert (z["onlem"], z["izleme"], z["ara_belgeler"]) == ("kurul", "anket", ["yazi"])
        assert any(n.startswith("PUKÖ zinciri:") for n in c["notlar"])
    assert _c(a, "B.1.2")["od"] == 4
    js = json.loads(paths["json"].read_text(encoding="utf-8"))
    assert next(x for x in js["olcutler"] if x["olcut"] == "A.4.2")["puko_zinciri"][0]["satir"] == "kurul|A.4.2/3"
    # B.1.5'te izleme kanıtı yok: zincir satırı açılmaz
    assert not _c(a, "B.1.5")["puko_zinciri"]


def test_chain_needs_explicit_reference_and_monitoring(tmp_path):
    # ara yazıda atıf yok → bağ kopuk
    w = _ws(tmp_path / "a", _docs(yazi=YAZI.replace("doğrultusunda hazırlanan", "ile hazırlanan")), faaliyet=FA)
    a = build(w)
    assert not any("puko_zinciri" in r["flags"] for r in a.rows) and _c(a, "B.1.2")["od"] == 3
    # faaliyet kaydı yok: ad göndermesi kurulamaz
    w = _ws(tmp_path / "b", _docs())
    assert not any("puko_zinciri" in r["flags"] for r in build(w).rows)
    # izleme halkası yok (anket yalnız uygula, faaliyette değerlendirme değil)
    fa = {"sema": 1, "faaliyetler": [_rec("F001", "Bölüm Anket Komisyonu Toplantısı", "2025-01-14", ["anket"],
                                          asama="gerceklesme")]}
    w = _ws(tmp_path / "c", _docs(anket_asama="uygula"), faaliyet=fa)
    assert not any("puko_zinciri" in r["flags"] for r in build(w).rows)


def test_human_decision_overrides_chain(tmp_path):
    w = _ws(tmp_path / "a", _docs(), faaliyet=FA)
    # zincir satırı reddedildi: sayılmaz, başka yuvaya da taşınmaz
    a = build(w, review={"kurul|A.4.2/3": {"satir": "kurul|A.4.2/3", "karar": "ret"},
                         "kurul|B.1.2/3": {"satir": "kurul|B.1.2/3", "karar": "ret"}})
    r = a.by_key["kurul|A.4.2/3"]
    assert not r["sayilir"] and "insan_reddetti" in r["flags"] and _c(a, "A.4.2")["zincir"]["onlem_al"]["durum"] != "var"
    assert "kurul|B.1.2/4" not in a.by_key and not a.by_key["kurul|B.1.2/3"]["sayilir"]
    # modelin aynı yuvadaki (başka iddialı) eşleşmesi reddedildiyse sıradaki önlem yuvası denenir
    w = _ws(tmp_path / "b", _docs(kurul_b12=True), faaliyet=FA)
    a = build(w, review={"kurul|B.1.2/3": {"satir": "kurul|B.1.2/3", "karar": "ret"}})
    assert not a.by_key["kurul|B.1.2/3"]["sayilir"] and "puko_zinciri" not in a.by_key["kurul|B.1.2/3"]["flags"]
    assert a.by_key["kurul|B.1.2/4"]["sayilir"] and "puko_zinciri" in a.by_key["kurul|B.1.2/4"]["flags"]
