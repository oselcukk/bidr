"""İmza önerileri varsayılan açık (kullanıcı kararı 2026-11-26 20:12; sentetik rapor, maskeleme hesabı yok): kararı
verilmemiş imza önerisi (taşan imza, imza izi dahil) karartılmaz, sorulmaz; yalnız imza yüzünden "başarısız" olan
dosya tamam görünür. Yalnız okuma/karar katmanı."""
from __future__ import annotations

import json

from bidr.mask import inceleme as I
from bidr.mask.run import REPORT


def _b(i, tur, kaynak, karar="onay_bekliyor", kapali=False):
    return {"id": f"abcd1234-s1-{i}", "sayfa": 1, "kutu": [0, 0, 10, 10], "tur": tur, "karar": karar,
            "neden": "n", "kaynak": kaynak, "guven": 0.5, "kapali": kapali}


def _rapor(ws, dosyalar):
    (ws / REPORT).write_text(json.dumps({"mod": "kanit", "dosyalar": dosyalar}, ensure_ascii=False), encoding="utf-8")


def test_imza_onerisi_varsayilan_acik(tmp_path):
    imza = {"dosya": "a.pdf", "sha256": "abcd1234" * 8, "durum": "basarisiz", "kalan": {},
            "kalan_sorunlar": ["imza: elle bakılmalı (s.1)", "imza: elle bakılmalı — basılı metinle örtüşen imza "
                               "kapatılmadı (s.1)"],
            "bolgeler": [_b(1, "imza", "etiketsiz_aday"), _b(2, "imza", "imza_tasmasi"),
                         _b(3, "kisisel_veri", "imza_izi")], "onay_bekleyen": 3}
    karma = {"dosya": "b.pdf", "sha256": "ef561234" * 8, "durum": "basarisiz", "kalan": {},
             "kalan_sorunlar": ["imza: elle bakılmalı (s.1)", "redaksiyon doğrulaması başarısız (1 kutu): x"],
             "bolgeler": [{**_b(1, "imza", "etiketsiz_aday"), "id": "ef561234-s1-1"},
                          {**_b(2, "el_yazisi_alan", "rakam_dizisi"), "id": "ef561234-s1-2"},
                          {**_b(3, "imza", "imza_metin", kapali=True), "id": "ef561234-s1-3"}], "onay_bekleyen": 3}
    _rapor(tmp_path, [imza, karma])
    r = I.bekleyenler(tmp_path)
    bek = {b["id"] for b in r["bolgeler"]}
    # imza önerileri sorulmaz; el yazısı alanı ve kutusu kapatılmış imza (geri basma) sorulur
    assert bek == {"ef561234-s1-2", "ef561234-s1-3"}
    tum = {b["id"]: b for b in r["tum_bolgeler"]}
    for i in ("abcd1234-s1-1", "abcd1234-s1-2", "abcd1234-s1-3", "ef561234-s1-1"):
        assert tum[i]["karar"] == "birakildi" and tum[i]["varsayilan"] and not tum[i]["kapali"]
    d = {x["dosya"]: x for x in r["dosyalar"]}
    assert d["a.pdf"]["durum"] == "tamam" and d["a.pdf"]["bidr_durum"] == "tamam"
    assert d["b.pdf"]["durum"] == "karar_bekliyor" and d["b.pdf"]["bidr_durum"] == "basarisiz"
    assert r["dosya"] == 1
    # bölümün açık kararı varsayılanı aşar: "kapat" denmiş imza önerisi karar verilmişlerde görünür
    (tmp_path / "maskeleme-kararlari.jsonl").write_text(json.dumps(
        {"id": "abcd1234-s1-1", "karar": "kapat", "kim": "x", "zaman": "t"}) + "\n", encoding="utf-8")
    r = I.bekleyenler(tmp_path)
    assert [b["id"] for b in r["karar_verilmis"]] == ["abcd1234-s1-1"]

