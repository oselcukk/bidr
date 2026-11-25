"""Belge kimliği maskeli kopyanın baytına bağlı değil (K1): maskeli kaynakta özgün dosyanın sha'sı.

Sentetik: `girdi/` özgün dosyalar, `maskeli/` bidr maskeli kopyası kılığında (işaret + rapor: hedef → özgün
sha256). Maskeli kopyanın baytı metni değiştirmeden değişebilsin diye docx kullanılır (zip zaman damgası:
canlıda docx/xlsx'in yeniden üretimde baytını değiştiren şeyin kendisi).
"""
from __future__ import annotations

import csv
import hashlib
import json
import zipfile
from pathlib import Path

from bidr.cli import main
from bidr.common import Workspace, read_jsonl, write_jsonl
from bidr.ingest import kimlik as K
from bidr.ingest import onar as O
from bidr.ingest import pipeline as P

DOCX = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
        '<w:p><w:r><w:t>{}</w:t></w:r></w:p></w:body></w:document>')
CT = ('<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/'
      'content-types"><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/'
      'document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.'
      'main+xml"/></Types>')


def _docx(p: Path, metin: str, yil: int = 2025) -> None:
    """Aynı metin, `yil` değişince farklı bayt (zip girdisi zaman damgası)."""
    p.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(p, "w") as z:
        for ad, veri in (("[Content_Types].xml", CT), ("word/document.xml", DOCX.format(metin))):
            z.writestr(zipfile.ZipInfo(ad, date_time=(yil, 1, 1, 0, 0, 0)), veri)


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _isaretle(tmp: Path, ozgun: dict[str, str]) -> None:
    """`maskeli/`yi bidr maskeli kaynak kopyası yap: işaret + rapor (hedef → özgün sha256)."""
    mask = tmp / "maskeli"
    rapor = tmp / ("maskeli" + K.REPORT_SUFFIX)
    rapor.write_text(json.dumps({"mod": "kaynak", "kaynak_klasor": str(tmp / "girdi"), "maskeli_klasor": str(mask),
                                 "dosyalar": [{"dosya": rel, "hedef": rel, "sha256": sha, "durum": "tamam"}
                                              for rel, sha in ozgun.items()]}), encoding="utf-8")
    (mask / K.MARKER).write_text(json.dumps({"surum": 1, "mod": "kaynak", "durum": "tamam", "rapor": str(rapor)}),
                                 encoding="utf-8")


def _inv(ws: Path) -> dict[str, dict]:
    with open(ws / "inventory.csv", newline="", encoding="utf-8") as f:
        return {r["rel_path"]: r for r in csv.DictReader(f)}


def _ingest(tmp: Path) -> dict[str, dict]:
    P.run(tmp / "maskeli", tmp / "ws", use_ocr=False, workers=1, log=lambda m: None)
    return _inv(tmp / "ws")


METIN = {"a.docx": "Bölüm kurulu toplantı tutanağı gündem bir", "b.docx": "Danışma kurulu kararı yeni ders",
         "c.docx": "Mezun anketi sonuç raporu değerlendirme"}
OZGUN = {rel: hashlib.sha256(rel.encode()).hexdigest() for rel in METIN}      # özgün dosyaların (sanal) sha'ları


def _kur(tmp: Path, *, maskeli: bool) -> None:
    for rel, m in METIN.items():
        _docx(tmp / "maskeli" / rel, m)
    if maskeli:
        _isaretle(tmp, OZGUN)


def _kayit_yaz(ws: Path, inv: dict[str, dict]) -> None:
    """Belgelere bağlı türetilmiş ve insan kayıtları (kimlik anahtarlı)."""
    ids = [r["doc_id"] for r in inv.values()]
    for name in P.DERIVED_JSONL:
        write_jsonl(ws / name, [{"doc_id": d, "durum": "ok", "dosya": name} for d in sorted(ids)])
    write_jsonl(ws / "review-decisions.jsonl", [{"satir": f"{d}|y", "doc_id": d, "karar": "kabul"} for d in ids])
    for d in ids:
        (ws / "work" / "coarse").mkdir(parents=True, exist_ok=True)
        (ws / "work" / "coarse" / f"{d}.json").write_text("{}", encoding="utf-8")


def _ids(p: Path) -> set[str]:
    return {r["doc_id"] for r in read_jsonl(p)} if p.exists() else set()


def test_sabitler_maskeleme_koduyla_ayni():
    from bidr.mask import kaynak, onbellek, run
    assert K.MARKER == run.MARKER and K.REPORT_SUFFIX == kaynak.REPORT_SUFFIX and K.ONBELLEK == onbellek.DOSYA
    assert K._anahtar("kaynak_cikti", "ab" * 32) == onbellek.anahtar("kaynak_cikti", "ab" * 32)


def test_maskesiz_kaynakta_davranis_ayni(tmp_path):
    _kur(tmp_path, maskeli=False)
    inv = _ingest(tmp_path)
    for rel, r in inv.items():
        assert r["doc_id"] == _sha(tmp_path / "maskeli" / rel)[:16] and r["ozgun_sha256"] == ""
    ws = tmp_path / "ws"
    _kayit_yaz(ws, inv)
    eski = inv["a.docx"]["doc_id"]
    _docx(tmp_path / "maskeli" / "a.docx", METIN["a.docx"], yil=2026)          # bayt değişti: yeni belge (eskisi gibi)
    inv2 = _ingest(tmp_path)
    assert inv2["a.docx"]["doc_id"] != eski
    assert eski not in _ids(ws / "decisions.jsonl") and (ws / P.REMOVED_DIR / "text" / f"{eski}.txt").exists()
    assert not (ws / K.KAYIT).exists() and not (ws / K.OKSUZ_DIR).exists()


def test_maskeli_kopyanin_bayti_degisince_kimlik_ayni_kalir(tmp_path):
    _kur(tmp_path, maskeli=True)
    inv = _ingest(tmp_path)
    for rel, r in inv.items():
        assert r["doc_id"] == OZGUN[rel][:16] and r["ozgun_sha256"] == OZGUN[rel]
        assert r["sha256"] == _sha(tmp_path / "maskeli" / rel)
    ws = tmp_path / "ws"
    _kayit_yaz(ws, inv)
    (ws / "text" / f"{inv['a.docx']['doc_id']}.txt").write_text("MODEL METNİ", encoding="utf-8")   # transcribe çıktısı
    (ws / "text_ocr").mkdir()
    (ws / "text_ocr" / f"{inv['a.docx']['doc_id']}.txt").write_text(METIN["a.docx"] + "\n", encoding="utf-8")
    taban = P.ex.extract(tmp_path / "maskeli" / "a.docx", use_ocr=False).text
    (ws / "text_ocr" / f"{inv['a.docx']['doc_id']}.txt").write_text(taban, encoding="utf-8")
    for rel in METIN:                                                          # yeniden üretim: yalnız zaman damgası
        _docx(tmp_path / "maskeli" / rel, METIN[rel], yil=2026)
    msgs: list[str] = []
    P.run(tmp_path / "maskeli", ws, use_ocr=False, workers=1, log=msgs.append)
    inv2 = _inv(ws)
    for rel in METIN:
        assert inv2[rel]["doc_id"] == inv[rel]["doc_id"]
        assert inv2[rel]["sha256"] == _sha(tmp_path / "maskeli" / rel) != inv[rel]["sha256"]
        assert inv2[rel]["chars"] == inv[rel]["chars"] and inv2[rel]["status"] == inv[rel]["status"]
    assert (ws / "text" / f"{inv['a.docx']['doc_id']}.txt").read_text(encoding="utf-8") == "MODEL METNİ"
    for name in P.DERIVED_JSONL:
        assert _ids(ws / name) == {r["doc_id"] for r in inv.values()}
    assert not (ws / P.REMOVED_DIR).exists() and not (ws / K.OKSUZ_DIR).exists()
    assert any("metni aynı" in m for m in msgs)


def test_maskeli_kopyanin_metni_degisirse_kimlik_kalir_kayit_eskir(tmp_path):
    _kur(tmp_path, maskeli=True)
    inv = _ingest(tmp_path)
    ws = tmp_path / "ws"
    _kayit_yaz(ws, inv)
    a = inv["a.docx"]["doc_id"]
    _docx(tmp_path / "maskeli" / "a.docx", "Bölüm kurulu toplantı tutanağı [AD] gündem bir")     # maske değişti
    inv2 = _ingest(tmp_path)
    assert inv2["a.docx"]["doc_id"] == a
    assert "[AD]" in (ws / "text" / f"{a}.txt").read_text(encoding="utf-8")
    assert "[AD]" not in (ws / P.REMOVED_DIR / P.CHANGED_DIR / "text" / f"{a}.txt").read_text(encoding="utf-8")
    dec = {r["doc_id"]: r for r in read_jsonl(ws / "decisions.jsonl")}
    assert dec[a]["durum"] == "metin_degisti" and dec[a]["onceki"]["durum"] == "ok"
    assert a not in _ids(ws / "documents.jsonl")
    assert dec[inv["b.docx"]["doc_id"]]["durum"] == "ok"


def test_ayni_ozgun_dosya_kopyadir_ve_yeni_belge_ozgun_kimlik_alir(tmp_path):
    _kur(tmp_path, maskeli=True)
    _docx(tmp_path / "maskeli" / "d.docx", "Yeni eklenen belge staj raporu")
    _docx(tmp_path / "maskeli" / "z-kopya.docx", METIN["a.docx"], yil=2031)    # aynı özgün, başka maskeli bayt
    yeni = hashlib.sha256(b"d").hexdigest()
    _isaretle(tmp_path, {**OZGUN, "d.docx": yeni, "z-kopya.docx": OZGUN["a.docx"]})
    inv = _ingest(tmp_path)
    assert inv["d.docx"]["doc_id"] == yeni[:16]
    assert inv["z-kopya.docx"]["dup_of"] == "a.docx" and inv["z-kopya.docx"]["doc_id"] == inv["a.docx"]["doc_id"]
    assert inv["z-kopya.docx"]["chars"] == inv["a.docx"]["chars"]


def test_eski_calisma_alani_goc_eder(tmp_path):
    """Eski çalışma alanı (kimlik = maskeli sha): kimlikler korunur ve sabitlenir; maskeli baytı değişen belge
    metin eşitliğiyle ya da önbellekle doğrulanır; doğrulanamayan silinmez, `_oksuz/`a alınır."""
    _kur(tmp_path, maskeli=False)                       # eski sürüm: işaret yokmuş gibi (kimlik maskeli bayttan)
    eski = _ingest(tmp_path)
    ws = tmp_path / "ws"
    _kayit_yaz(ws, eski)
    assert all(r["doc_id"] == r["sha256"][:16] for r in eski.values())
    # yeni sürüm + maskeleme yeniden koştu: a aynı bayt; b yalnız zaman damgası; c hem bayt hem metin
    _docx(tmp_path / "maskeli" / "b.docx", METIN["b.docx"], yil=2026)
    _docx(tmp_path / "maskeli" / "c.docx", "Mezun anketi sonuç raporu [AD] değerlendirme", yil=2026)
    _isaretle(tmp_path, OZGUN)
    msgs: list[str] = []
    P.run(tmp_path / "maskeli", ws, use_ocr=False, workers=1, log=msgs.append)
    inv = _inv(ws)
    assert inv["a.docx"]["doc_id"] == eski["a.docx"]["doc_id"]
    assert inv["b.docx"]["doc_id"] == eski["b.docx"]["doc_id"]
    assert all(r["ozgun_sha256"] == OZGUN[rel] for rel, r in inv.items())
    pins = {r["ozgun_sha256"]: r for r in read_jsonl(ws / K.KAYIT)}
    assert pins[OZGUN["a.docx"]]["kaynak"] == "goc" and pins[OZGUN["b.docx"]]["kaynak"] == "goc-metin"
    c_eski = eski["c.docx"]["doc_id"]
    assert inv["c.docx"]["doc_id"] == OZGUN["c.docx"][:16] != c_eski          # belirsiz: yeni kimlik
    assert c_eski not in _ids(ws / "decisions.jsonl")
    arsiv = [r for r in read_jsonl(ws / K.OKSUZ_DIR / "kayitlar.jsonl") if r["dosya"] == "decisions.jsonl"]
    assert [r["kayit"]["doc_id"] for r in arsiv] == [c_eski]
    assert (ws / K.OKSUZ_DIR / "text" / f"{c_eski}.txt").exists() and not (ws / P.REMOVED_DIR).exists()
    assert [b["doc_id"] for b in K.bekleyenler(ws)] == [c_eski]
    assert any("BELİRSİZ" in m for m in msgs)
    assert _ids(ws / "decisions.jsonl") == {eski["a.docx"]["doc_id"], eski["b.docx"]["doc_id"]}
    # ikinci koşu hiçbir şeyi değiştirmez
    assert {rel: r["doc_id"] for rel, r in _ingest(tmp_path).items()} == {rel: r["doc_id"] for rel, r in inv.items()}
    # elle eşleme ile onarım: c eski kimliğine döner
    pl = O.plan(ws, tmp_path / "maskeli", esleme={c_eski: "c.docx"})
    assert [(x["eski"], x["yeni"], x["metin_ayni"]) for x in pl["ciftler"]] == [(c_eski, OZGUN["c.docx"][:16], False)]
    O.uygula(ws, pl, log=lambda m: None)
    assert _inv(ws)["c.docx"]["doc_id"] == c_eski and c_eski in _ids(ws / "decisions.jsonl")
    assert K.bekleyenler(ws) == []
    assert "[AD]" not in (ws / "text" / f"{c_eski}.txt").read_text(encoding="utf-8")       # --degisen-metin eski
    assert _ingest(tmp_path)["c.docx"]["doc_id"] == c_eski


def test_goc_onbellekle_dogrular(tmp_path):
    from bidr.mask import onbellek
    _kur(tmp_path, maskeli=False)
    eski = _ingest(tmp_path)
    ws = tmp_path / "ws"
    _kayit_yaz(ws, eski)
    ob = onbellek.Onbellek(ws / onbellek.DOSYA)
    ob.put_json("kaynak_cikti", onbellek.anahtar("kaynak_cikti", eski["c.docx"]["sha256"]),
                {"key": "k1", "girdi": {"sha": OZGUN["c.docx"]}, "rec": {}})
    ob.close()
    _docx(tmp_path / "maskeli" / "c.docx", "Mezun anketi sonuç raporu [AD] değerlendirme", yil=2026)
    _isaretle(tmp_path, OZGUN)
    inv = _ingest(tmp_path)
    c = eski["c.docx"]["doc_id"]
    assert inv["c.docx"]["doc_id"] == c                                        # özgün aynı: kimlik korunur
    assert {r["doc_id"]: r for r in read_jsonl(ws / "decisions.jsonl")}[c]["durum"] == "metin_degisti"
    assert not (ws / K.OKSUZ_DIR).exists()
    assert {r["ozgun_sha256"]: r["kaynak"] for r in read_jsonl(ws / K.KAYIT)}[OZGUN["c.docx"]] == "goc-onbellek"


def test_belirsiz_kimlik_model_isinden_once_durdurur(tmp_path):
    from bidr.pipeline import checks as CH
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "inventory.csv").write_text("doc_id,rel_path,status\n", encoding="utf-8")
    K.bekleyen_yaz(ws, [{"doc_id": "aaaa", "rel_path": "a.docx"}])
    c = CH.ingest_tamam(CH.Ctx(Workspace(ws), {"kaynak": str(tmp_path)}, lambda s: s.replace("{ws}", str(ws)), {}))
    assert not c.bitti and c.kim == CH.INSAN and "kimlik-onar" in c.komutlar[0]


def test_kimlik_onar_kaymis_kayitlari_geri_baglar(tmp_path):
    """Canlı olay: eski sürüm ingest, maskeli baytı değişen belgeleri yeni belge sayıp kayıtlarını
    `kaynaktan-cikarilan/`a taşıdı. `bidr kimlik-onar` eski kimlikleri geri bağlar; yeni belge yeni kalır."""
    _kur(tmp_path, maskeli=False)
    eski = _ingest(tmp_path)
    ws = tmp_path / "ws"
    _kayit_yaz(ws, eski)
    once = {name: sorted(json.dumps(r, sort_keys=True) for r in read_jsonl(ws / name)) for name in P.DERIVED_JSONL}
    yedek = tmp_path / "yedek"
    yedek.mkdir()
    for name in ("decisions.jsonl", "review-decisions.jsonl"):
        (yedek / name).write_bytes((ws / name).read_bytes())
    # olay: b ve c'nin maskeli kopyası yeniden üretildi (yalnız zaman damgası) + yeni belge d; eski ingest budadı
    for rel in ("b.docx", "c.docx"):
        _docx(tmp_path / "maskeli" / rel, METIN[rel], yil=2026)
    _docx(tmp_path / "maskeli" / "d.docx", "Yeni eklenen belge staj raporu")
    olay = _ingest(tmp_path)                                                   # işaret yok: eski davranış
    kayan = {eski[rel]["doc_id"]: olay[rel]["doc_id"] for rel in ("b.docx", "c.docx")}
    assert all(k != v for k, v in kayan.items()) and _ids(ws / "decisions.jsonl") == {eski["a.docx"]["doc_id"]}
    yeni_d = olay["d.docx"]["doc_id"]
    (ws / "work" / "describe" / kayan[eski["b.docx"]["doc_id"]]).mkdir(parents=True)      # bugünün artığı
    (ws / "work" / "describe" / "ffffffffffffffff").mkdir(parents=True)                    # eski öksüz paket
    (ws / "work" / "describe" / "ffffffffffffffff" / "ffffffffffffffff.json").write_text("{}", encoding="utf-8")
    ozgun = {**OZGUN, "d.docx": hashlib.sha256(b"d").hexdigest()}
    _isaretle(tmp_path, ozgun)
    w = str(ws)
    assert main(["kimlik-onar", "-w", w, "--kaynak", str(tmp_path / "maskeli")]) == 0     # kuru koşu
    assert _inv(ws)["b.docx"]["doc_id"] == olay["b.docx"]["doc_id"] and not (ws / K.KAYIT).exists()
    assert main(["kimlik-onar", "-w", w, "--kaynak", str(tmp_path / "maskeli"), "--yedek", str(yedek),
                 "--uygula"]) == 0
    inv = _inv(ws)
    assert {rel: inv[rel]["doc_id"] for rel in METIN} == {rel: eski[rel]["doc_id"] for rel in METIN}
    assert inv["d.docx"]["doc_id"] == yeni_d
    assert all(inv[rel]["ozgun_sha256"] == ozgun[rel] for rel in inv)
    assert inv["b.docx"]["sha256"] == _sha(tmp_path / "maskeli" / "b.docx")              # maskeli bayt bugünkü
    for name in P.DERIVED_JSONL:
        assert sorted(json.dumps(r, sort_keys=True) for r in read_jsonl(ws / name)) == once[name]
    for d in kayan:
        assert (ws / "text" / f"{d}.txt").exists() and (ws / "work" / "coarse" / f"{d}.json").exists()
    for n in kayan.values():
        assert not (ws / "text" / f"{n}.txt").exists() and not (ws / "work" / "describe" / n).exists()
    assert (ws / "text" / f"{yeni_d}.txt").exists()
    assert not (ws / "work" / "describe" / "ffffffffffffffff").exists()
    v = O.yedekle_karsilastir(ws, yedek)
    assert v["decisions.jsonl"]["ayni"] == 3 and not v["decisions.jsonl"]["eksik"] + v["decisions.jsonl"]["farkli"]
    assert v["review-decisions.jsonl"]["ayni"] == 3
    # sonraki ingest ve ikinci onarım hiçbir şeyi değiştirmez
    son = _ingest(tmp_path)
    assert {rel: r["doc_id"] for rel, r in son.items()} == {rel: r["doc_id"] for rel, r in inv.items()}
    assert _ids(ws / "decisions.jsonl") == {r["doc_id"] for rel, r in eski.items()}
    assert O.plan(ws, tmp_path / "maskeli")["ciftler"] == []


def test_kimlik_onar_maskesiz_kaynakta_calismaz(tmp_path):
    _kur(tmp_path, maskeli=False)
    _ingest(tmp_path)
    assert main(["kimlik-onar", "-w", str(tmp_path / "ws"), "--kaynak", str(tmp_path / "maskeli")]) == 2


def test_model_metni_olan_bos_cikarimli_belge_yeniden_cikarilmaz(tmp_path):
    """Görsel belge: ingest çıkarımı boş (status empty), metni transcribe/describe yazdı. Sonraki ingest bu metni
    ezmemeli (ezerse apply metni yeniden yazar, karar `metin_degisti` olur, belge her koşuda yeniden karara gider)."""
    _kur(tmp_path, maskeli=False)
    _docx(tmp_path / "maskeli" / "bos.docx", "")
    inv = _ingest(tmp_path)
    ws = tmp_path / "ws"
    assert inv["bos.docx"]["status"] == "empty"
    did = inv["bos.docx"]["doc_id"]
    (ws / "text" / f"{did}.txt").write_text("BETİMLEME: afiş", encoding="utf-8")
    rows = list(inv.values())
    for r in rows:
        if r["doc_id"] == did:
            r.update(method="agent_describe", chars=15)
    with open(ws / "inventory.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=P.FIELDS)
        w.writeheader()
        w.writerows(rows)
    inv2 = _ingest(tmp_path)
    assert (ws / "text" / f"{did}.txt").read_text(encoding="utf-8") == "BETİMLEME: afiş"
    assert inv2["bos.docx"]["method"] == "agent_describe" and inv2["bos.docx"]["chars"] == "15"
    P.run(tmp_path / "maskeli", ws, use_ocr=False, workers=1, force=True, log=lambda m: None)
    assert (ws / "text" / f"{did}.txt").read_text(encoding="utf-8") != "BETİMLEME: afiş"      # --force: yeniden


def test_metin_degisti_karari_geri_alinir(tmp_path):
    _kur(tmp_path, maskeli=True)
    inv = _ingest(tmp_path)
    ws = tmp_path / "ws"
    _kayit_yaz(ws, inv)
    a = inv["a.docx"]["doc_id"]
    from bidr.transcribe.run import invalidate_downstream
    invalidate_downstream(Workspace(ws), {a})
    assert (ws / "work" / "coarse" / f"{a}.json.eski").exists()
    pl = O.plan(ws, tmp_path / "maskeli")
    assert pl["metin_degisti"] == [a] and pl["ciftler"] == []
    st = O.uygula(ws, pl, metin_degisti_geri_al=True, log=lambda m: None)
    assert st["metin_degisti_geri"] == 1
    assert {r["doc_id"]: r["durum"] for r in read_jsonl(ws / "decisions.jsonl")}[a] == "ok"
    assert (ws / "work" / "coarse" / f"{a}.json").exists()


def test_maskeli_kopyanin_bayti_degisince_ingest_tamam_ingest_ister(tmp_path):
    """Maskeli kopyanın baytı ingest'ten sonra değişince (yeniden maskeleme) hat ingest ister; ingest metni
    karşılaştırır: metni aynı kalan belgenin kararı korunur, değişenin kararı `metin_degisti` olur."""
    import os
    import time

    from bidr.pipeline import checks as CH
    _kur(tmp_path, maskeli=True)
    inv = _ingest(tmp_path)
    ws = tmp_path / "ws"
    _kayit_yaz(ws, inv)
    ctx = CH.Ctx(Workspace(ws), {"kaynak": str(tmp_path / "maskeli")}, lambda s: s.replace("{ws}", str(ws)), {})
    assert CH.ingest_tamam(ctx).bitti
    # yeniden maskeleme: a'nın metni değişti, b yalnız bayt (zip zaman damgası), c dokunulmadı
    t = time.time() - 60
    for rel in METIN:
        os.utime(tmp_path / "maskeli" / rel, (t, t))
    os.utime(ws / "inventory.csv", (t + 10, t + 10))
    assert CH.ingest_tamam(ctx).bitti
    _docx(tmp_path / "maskeli" / "a.docx", "Bölüm kurulu toplantı tutanağı [AD] gündem bir")
    _docx(tmp_path / "maskeli" / "b.docx", METIN["b.docx"], yil=2026)
    c = CH.ingest_tamam(ctx)
    assert c.kim == CH.KOMUT and not c.bitti and "2 kaynak dosyanın baytı" in c.neden
    assert "a.docx" in c.neden and "b.docx" in c.neden and "c.docx" not in c.neden
    _ingest(tmp_path)
    assert CH.ingest_tamam(ctx).bitti
    dec = {r["doc_id"]: r for r in read_jsonl(ws / "decisions.jsonl")}
    assert dec[inv["a.docx"]["doc_id"]]["durum"] == "metin_degisti"
    assert dec[inv["b.docx"]["doc_id"]]["durum"] == "ok" and dec[inv["c.docx"]["doc_id"]]["durum"] == "ok"
    # saat kayması: zamanı gelecekte ama baytı aynı dosya ingest'ten sonra döngü yaratmaz (sha ile doğrulanır)
    g = time.time() + 3600
    os.utime(tmp_path / "maskeli" / "c.docx", (g, g))
    assert CH.ingest_tamam(ctx).bitti
