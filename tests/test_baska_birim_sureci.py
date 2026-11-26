"""Başka idari birimin iç süreci kanıt değil (kullanıcı kararı 2026-11-26 20:12; sentetik veri, model yok):
bölümün kendi yönetimini soran maddede (ör. A.3.4 süreç yönetimi) kurum geneli iş akışı ya da idari birimin kendi
yönergesi, bölüm süreçte görev almıyorsa sayılmaz ve sorulmaz (bilgi). Bölümün görev aldığı iş akışı (bölüm kurulu,
anabilim dalı, danışman) ve bütün akademik birimlere uygulanan düzenleme OD2 kanıt kalır; hizmet maddelerinde
(öğrenci kabulü, destek hizmetleri) kurum süreci kanıttır."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from bidr.audit import sade as S
from bidr.audit.run import build, seen_state
from bidr.audit.savunma import bolum_aktor
from bidr.criteria.loader import load_criteria

YIL = 2025


def test_bolum_aktor():
    assert bolum_aktor("Ders planı değişikliği Bölüm Kurulunda görüşülür.")
    assert bolum_aktor("Bölüm Müfredat Komisyonu formu kullanarak karar alır.")
    assert bolum_aktor("Öğrenci ilgili Bölüm Başkanı'na yönlendirilir.")
    assert bolum_aktor("Tez önerisi Anabilim Dalı Başkanlığına iletilir.")
    assert bolum_aktor("Danışman onayından sonra ders kaydı kesinleşir.")
    assert bolum_aktor("Birim kalite sorumlusu belirlenir.")
    # adı verilmiş başka birim, bildirim alıcısı ve rolsüz anış görev değildir
    assert not bolum_aktor("HAZIRLAYAN Örnek Diller Bölümü Kalite Sorumlusu")
    assert not bolum_aktor("Atama; Bölüme, seçilen adaya ve Rektörlük Makamına yazı ile bildirilir.")
    assert not bolum_aktor("Öğrenci İşleri Daire Başkanlığı kaydı başlatır. Mezun sistemi kontrol edilir.")
    assert not bolum_aktor("Danışmanlık hizmeti randevu ile verilir.")


def _m(olcut, yuva, asama="planla"):
    od = {"planla": 2, "uygula": 3}[asama]
    return {"olcut": olcut, "yuva": yuva, "asama": asama, "od_onerisi": od, "od_kabul": od, "alinti": "x" * 30,
            "gerekce": "g", "guven": "yuksek", "kabul": True,
            "denetim": {"alinti_tutuyor": True, "red": [], "isaret": []}}


METIN = {
    "ia_dis": "İŞ AKIŞ ADI: KAYIT İŞLEMİ\nİşlem Öğrenci İşleri Daire Başkanlığı tarafından başlatılır.\n"
              "Sistemde kayıt kontrol edilir.",
    "ia_bolum": "İŞ AKIŞ ADI: DERS PLANI GÜNCELLEMESİ\nBölüm Müfredat Komisyonu uygunluk kontrolü yapar.\n"
                "Değişiklik Bölüm Kurulunda görüşülür.",
    "yon_idari": "ÖRNEK KOORDİNATÖRLÜĞÜ YÖNERGESİ\nMadde 1 Koordinatörlüğün yönetim organları şunlardır.",
    "yon_genel": "LİSANS EĞİTİM VE ÖĞRETİM YÖNERGESİ\nMadde 1 Bu yönerge lisans programlarını kapsar.",
}
DOCS = {
    # did: (tür, eşleşmeler)
    "ia_dis": ("is_akisi", [_m("A.3.4", "A.3.4/1"), _m("B.3.2", "B.3.2/1")]),
    "ia_bolum": ("is_akisi", [_m("A.3.4", "A.3.4/1")]),
    "yon_idari": ("yonerge", [_m("A.1.1", "A.1.1/1")]),
    "yon_genel": ("yonerge", [_m("A.3.4", "A.3.4/1")]),
}


def _ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "text").mkdir(parents=True)
    (ws / "config.yaml").write_text("bidr:\n  surum: 1\n  birim: Örnek Bölümü\n  profil: akademik_bolum\n"
                                    f"  donem: {YIL}\n", encoding="utf-8")
    with open(ws / "inventory.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["doc_id", "sha256", "rel_path", "ext", "size", "pages", "chars", "method", "status", "dup_of",
                    "error"])
        for did in DOCS:
            w.writerow([did, did * 4, f"{did}.pdf", ".pdf", 1, 1, 10, "pdftotext", "ok", "", ""])
    with open(ws / "documents.jsonl", "w", encoding="utf-8") as f, \
            open(ws / "decisions.jsonl", "w", encoding="utf-8") as g:
        for did, (tur, ms) in DOCS.items():
            (ws / "text" / f"{did}.txt").write_text(METIN[did], encoding="utf-8")
            f.write(json.dumps({"doc_id": did, "calisma_adi": did, "doc_type": tur, "tarih": f"{YIL}-03-01",
                                "donem": YIL, "donem_ici": True, "baslik": METIN[did].splitlines()[0]},
                               ensure_ascii=False) + "\n")
            g.write(json.dumps({"doc_id": did, "durum": "ok", "asama": "ince", "karar": "olcut_var",
                                "ince": {"birim_iliskisi": "kurum_geneli"}, "eslesmeler": ms},
                               ensure_ascii=False) + "\n")
    return ws


def test_baska_birim_sureci_ucdan_uca(tmp_path):
    ws = _ws(tmp_path)
    a = build(ws)
    by = a.by_key
    dis, hizmet = by["ia_dis|A.3.4/1"], by["ia_dis|B.3.2/1"]
    assert not dis["sayilir"] and "baska_birim_sureci" in dis["flags"]
    # hizmet maddesinde aynı kurum süreci OD2 kanıt kalır
    assert hizmet["sayilir"] and hizmet["od"] == 2 and "baska_birim_sureci" not in hizmet["flags"]
    # bölümün görev aldığı iş akışı kanıt kalır
    assert by["ia_bolum|A.3.4/1"]["sayilir"] and "baska_birim_sureci" not in by["ia_bolum|A.3.4/1"]["flags"]
    # idari birimin kendi yönergesi bölümün yönetişim maddesinde kanıt değil; bütün birimlere uygulanan yönerge OD2
    assert not by["yon_idari|A.1.1/1"]["sayilir"] and "baska_birim_sureci" in by["yon_idari|A.1.1/1"]["flags"]
    assert by["yon_genel|A.3.4/1"]["sayilir"] and by["yon_genel|A.3.4/1"]["od"] == 2
    # İnceleme: sorulmaz ("Bakın" yapmaz), bilgi metni kalır, "Şu an kanıt sayılmıyor" yazılmaz
    x = {r["satir"]: r for r in S.inceleme_satirlari(a, load_criteria())}
    r = x["ia_dis|A.3.4/1"]
    assert r["oneri"] == "Kabul" and "Başka bir idari birimin iç süreci" in r["dikkat"]
    assert "Şu an kanıt sayılmıyor" not in r["dikkat"]
    # bölüm Kabul derse sayılır (bölüm değiştirebilir)
    a2 = build(ws, review={"ia_dis|A.3.4/1": {"satir": "ia_dis|A.3.4/1", "karar": "kabul"}})
    assert a2.by_key["ia_dis|A.3.4/1"]["sayilir"] and "baska_birim_sureci" not in a2.by_key["ia_dis|A.3.4/1"]["flags"]


def test_toplu_kabul_uygulanmaz_ve_yeniden_baktirmaz():
    assert "baska_birim_sureci" in S.SESSIZ_SAYILMAZ
    st = seen_state({"satir": "x|A.3.4/1", "flags": ["kurum_geneli", "baska_birim_sureci", "madde_baska_birim"]})
    assert st["isaretler"] == ["madde_baska_birim"]
