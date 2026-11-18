"""verify_quote: Türkçe katlama, boşluk/satır sonu, tireyle bölünme, OCR hataları. Sentetik metin."""
from __future__ import annotations

import pytest

from bidr.llm import verify_quote

DOC = ("BİRİM İÇ DEĞERLENDİRME\n"
       "Bu dönemde BÖLÜM KURULU toplantısında öğrenci geri bildirim-\n"
       "lerinin değer-\nlendirilmesi İLE ilgili karar alınmıştır.\n"
       "Işık Üniversitesi ile ortak çalıştay   düzenlendi; ﬁnal sınavı­ takvimi güncellendi.\n"
       "Toplantıya 12 öğretim üyesi katılmıştır.")


def _span(r):
    return DOC[r.span[0]:r.span[1]]


def test_exact_and_span():
    r = verify_quote("öğrenci geri bildirimlerinin", DOC)
    assert r.ok and r.score == 1.0 and _span(r) == "öğrenci geri bildirim-\nlerinin"


@pytest.mark.parametrize("quote", [
    "bölüm kurulu toplantısında",                 # büyük/küçük harf, İ/I
    "birim iç değerlendirme",                     # İ → i
    "IŞIK ÜNİVERSİTESİ İLE ORTAK ÇALIŞTAY",       # ı/I ↔ i/İ
    "değerlendirilmesi ile ilgili karar",         # tireyle bölünmüş sözcük
    "ortak çalıştay düzenlendi",                  # fazla boşluk
    "final sınavı takvimi",                       # ligatür + yumuşak tire
    "Bolum Kurulu toplantisinda ogrenci",         # aksansız (OCR/klavye)
    "Toplantıya l2 öğretim üyesi",                # 1 ↔ l
    "Toplantiya 12 ogretim uyesi katilmistir",
])
def test_tolerant_full_score(quote):
    r = verify_quote(quote, DOC)
    assert r.ok and r.score == 1.0, (quote, r)


def test_ocr_rn_m():
    doc = "Komisyon modern laboratuvar ortamını inceledi."
    r = verify_quote("Komisyon modem laboratuvar ortamını inceledi", doc)  # 'rn' → 'm' OCR'ı
    assert r.ok and r.score == 1.0


@pytest.mark.parametrize("quote,minscore", [
    ("Bolum kuru1u toplantısmda", 0.9),              # 'ın' → 'm' + 1/l
    ("ogrenci geri bi1dirimlerinin degerlendrilmesi ile ilgili karar", 0.95),  # düşen harf
    ("öğrenci geri bildirimleriinin değerlendirilmesi", 0.95),             # fazladan harf
])
def test_fuzzy_ocr_errors(quote, minscore):
    r = verify_quote(quote, DOC)
    assert r.ok and minscore <= r.score < 1.0, r
    assert r.span is not None


def test_threshold_parameter():
    q = "Bolum kuru1u toplantısmda"
    r = verify_quote(q, DOC, threshold=0.99)
    assert not r.ok and r.score < 0.99 and r.span is not None


@pytest.mark.parametrize("quote", [
    "rektörlük senatosu bütçe kararını onayladı",
    "öğrenci memnuniyet anketi sonuçları yayımlandı",
])
def test_fabricated_quote_rejected(quote):
    r = verify_quote(quote, DOC)
    assert not r.ok and r.score < 0.7


def test_empty_inputs():
    assert verify_quote("", DOC) == (False, 0.0, None)
    assert verify_quote("x", "") == (False, 0.0, None)
    assert verify_quote("—", DOC) == (False, 0.0, None)


def test_long_document_fast_and_located():
    import time

    filler = "Lorem ipsum dolor sit amet, consectetur adipiscing elit. " * 3000
    doc = filler + DOC + filler
    t = time.time()
    r = verify_quote("ogrenci geri bi1dirimlerinin degerlendrilmesi ile ilgili karar", doc)
    assert time.time() - t < 2.0
    assert r.ok and r.span[0] >= len(filler) and r.span[1] <= len(filler) + len(DOC)
    r2 = verify_quote("rektörlük senatosu bütçe kararını onayladı", doc)
    assert not r2.ok


def test_unpacks_as_tuple():
    ok, score, span = verify_quote("ortak çalıştay", DOC)
    assert ok and score == 1.0 and isinstance(span, tuple)
