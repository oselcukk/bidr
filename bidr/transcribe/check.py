"""Tamamlanma denetimi (pipeline.yaml'a kaydedilince `bidr/pipeline/checks.py`'ye
`CHECKS["transcribe_tamam"]` olarak eklenir). Salt okunur."""
from __future__ import annotations

import json


def transcribe_tamam(c):
    from bidr.pipeline.checks import AJAN, KOMUT, Check, _sample

    from . import run as R

    ws = c.ws
    if not ws.inventory.exists():
        return Check(kim=KOMUT, neden="inventory.csv yok")
    _, rows = R.read_inventory(ws)
    prim = R._primary(rows)
    log = R.load_log(ws)
    lowq = {d for d, r in prim.items() if str(r.get("low_quality", "")).strip() == "1"
            and (r.get("ext") or "").lower() in R.PDF_EXTS | R.DIRECT_IMG | R.CONVERT_IMG}
    done = {d for d in prim if R.is_done(ws, d, log)}
    # iki denemede de aynı nedenle reddedilen belge: karar verildi (metni OCR'da), aşama beklemez
    from bidr.pipeline import cevap as CV
    kesin = CV.Kesin(ws.root, "transcribe")
    # bölümün kesin kararı verilen belge de (içeriği değişmedikçe) beklenmez
    elle = {d for d in lowq - done if R.elle_bakilmali(ws, d, log) or kesin.get(d)}
    todo = lowq - done - elle
    prog = {"dusuk_kalite": len(lowq | done), "yaziya_gecirilen": len(done)}
    uy = []
    if elle:
        prog["elle_bakilmali"] = len(elle)
        uy.append(f"{len(elle)} belgenin görsel okuması iki denemede de reddedildi; elle bakılmalı, metni OCR'da "
                  f"kaldı (work/transcribe/{R.ELLE_MD}): {_sample(elle)}")
    if not todo:
        if not lowq and not done:
            return Check(atlandi=True, neden="düşük kaliteli (görsel/PDF) belge yok")
        return Check(bitti=True, ilerleme=prog, uyarilar=uy,
                     neden=f"{len(done)} belge yazıya geçirildi"
                           + (f", {len(elle)} belge elle bakılmalı" if elle else ""))
    d = R.work_dir(ws)
    pk = {x for x in todo if (d / x / f"{x}.json").exists()}
    if todo - pk:
        return Check(kim=KOMUT, ilerleme=prog, uyarilar=uy,
                     neden=f"{len(todo - pk)} düşük kaliteli belgenin paketi yok")
    apply_ = c.fmt(c.stage["komut"][2]) if c.stage.get("komut") else None
    no_out = {x for x in pk if not (d / x / f"{x}.out.json").exists()}
    if no_out:
        den = R.denemeler(ws)
        red = {x for x in no_out if den.kenarda(x)}
        return Check(kim=AJAN, ilerleme=prog, uyarilar=uy, bekleyen=sorted(no_out),
                     komutlar=["(ajan) work/transcribe/README.md'yi oku; cevapsız her <doc_id>/ için görüntüleri "
                               "okuyup <doc_id>.out.json yaz (reddedilenlerin gerekçesi GECERSIZ.md'de)"]
                              + ([apply_] if apply_ else []),
                     neden=f"{len(no_out)} paket cevapsız: görsel okuma ajanda"
                           + (f" ({len(red)} tanesinin önceki cevabı reddedildi, yeniden okunacak)" if red else ""))
    # cevaplar yazılmış: yalnız apply (prepare değil: paketler hazır, verilmiş cevaplar korunur)
    return Check(kim=KOMUT, ilerleme=prog, uyarilar=uy, komutlar=[apply_] if apply_ else None,
                 neden=f"{len(pk)} cevap işlenmemiş: apply (geçersiz/şüpheli cevap kenara alınır, yeniden "
                       "okunur; aynı nedenle ikinci ret elle bakılmalı olur)")


def belirsiz_okuma_tamam(c):
    """Aşama `belirsiz_okuma`: ince kararda birimi belirsiz kalan OCR'lı belgelerin görsel
    yeniden okuması. Aday yoksa bitti (koşullu aşama: kendiliğinden geçer). Okunan belgenin
    metni değiştiyse türetilmiş kayıtları geçersiz kılınmıştır; karar_ince bitmediği için bu
    aşama zaten engellidir ve `bidr next` identify → … → ince karara yönlendirir. Belge başına
    bir tur: transcribe.jsonl'de kaydı olan belge aday olmaz."""
    from bidr.decide.run import BIRIM_BELIRSIZ, load_decisions, record_unit_relation
    from bidr.pipeline.checks import AJAN, KOMUT, Check

    from . import run as R

    ws = c.ws
    sel, info = R.select_belirsiz(ws)
    log = R.load_log(ws)
    tur = {d for d, r in log.items() if r.get("tur") == R.BELIRSIZ}
    recs = load_decisions(ws) if tur else {}
    hala = sorted(d for d in tur if record_unit_relation(recs.get(d)) == BIRIM_BELIRSIZ)
    prog = {"aday": len(sel), "yeniden_okunan": len(tur), "hala_belirsiz": len(hala),
            "metin_ayni": sum(1 for d in tur if log[d].get("metin_ayni")),
            "paketlenemeyen": info["paketlenemedi"],
            "elle_bakilmali": sum(1 for d in tur if log[d].get("durum") == R.ELLE)}
    if not sel:
        if not tur and not info["paketlenemedi"]:
            return Check(bitti=True, ilerleme=prog,
                         neden=f"aday yok: ince kararda birimi belirsiz {info['belirsiz']} belgenin hiçbiri "
                               "OCR'lı/düşük kaliteli görüntü ya da PDF değil (ya da zaten görsel okundu)")
        uy = []
        if hala or info["paketlenemedi"]:
            uy.append(f"yeniden okumadan sonra da birimi belirsiz {len(hala)} belge"
                      + (f", paketlenemeyen {info['paketlenemedi']} belge (work/transcribe/belirsiz.json)"
                         if info["paketlenemedi"] else "")
                      + ": komisyona gider (audit → gaps.md 'Birim aitliği doğrulanmalı')")
        if prog["elle_bakilmali"]:
            uy.append(f"{prog['elle_bakilmali']} belgenin yeniden okuması iki denemede de reddedildi; elle bakılmalı, "
                      f"metni değişmedi (work/transcribe/{R.ELLE_MD})")
        return Check(bitti=True, ilerleme=prog, uyarilar=uy,
                     neden=f"{len(tur)} belge görsel okumayla yeniden okundu ve yeniden karara bağlandı")
    prep, apply_ = c.fmt(c.stage["komut"][0]), c.fmt(c.stage["komut"][2])
    d = R.work_dir(ws)
    pk = {x for x in sel if (d / x / f"{x}.json").exists()}
    if set(sel) - pk:
        return Check(kim=KOMUT, ilerleme=prog, komutlar=[prep],
                     neden=f"birimi belirsiz {len(sel)} OCR'lı belgeden {len(set(sel) - pk)} tanesinin "
                           "görsel okuma paketi yok")
    no_out = {x for x in pk if not (d / x / f"{x}.out.json").exists()}
    if no_out:
        return Check(kim=AJAN, ilerleme=prog, bekleyen=sorted(no_out),
                     komutlar=["(ajan) work/transcribe/README.md'yi oku; cevapsız her <doc_id>/ için "
                               "görüntüleri okuyup <doc_id>.out.json yaz (hepsini bitirip bir kez apply)", apply_],
                     neden=f"{len(no_out)} paket cevapsız: görsel okuma ajanda")
    return Check(kim=KOMUT, ilerleme=prog, komutlar=[apply_],
                 neden=f"{len(pk)} cevap işlenmemiş ya da geçersiz/şüpheli: apply (work/transcribe/GECERSIZ.md)")
