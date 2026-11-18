"""Tamamlanma denetimi (pipeline.yaml'a kaydedilince `bidr/pipeline/checks.py`'ye
`CHECKS["transcribe_tamam"]` olarak eklenir). Salt okunur."""
from __future__ import annotations

import json


def transcribe_tamam(c):
    from bidr.pipeline.checks import AJAN, KOMUT, Check

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
    todo = lowq - done
    prog = {"dusuk_kalite": len(lowq | done), "yaziya_gecirilen": len(done)}
    if not todo:
        if not lowq and not done:
            return Check(atlandi=True, neden="düşük kaliteli (görsel/PDF) belge yok")
        return Check(bitti=True, ilerleme=prog, neden=f"{len(done)} belge yazıya geçirildi")
    d = R.work_dir(ws)
    pk = {x for x in todo if (d / x / f"{x}.json").exists()}
    if todo - pk:
        return Check(kim=KOMUT, ilerleme=prog, neden=f"{len(todo - pk)} düşük kaliteli belgenin paketi yok")
    no_out = {x for x in pk if not (d / x / f"{x}.out.json").exists()}
    if no_out:
        return Check(kim=AJAN, ilerleme=prog,
                     komutlar=["(ajan) work/transcribe/README.md'yi oku; her <doc_id>/ için görüntüleri "
                               "okuyup <doc_id>.out.json yaz"],
                     neden=f"{len(no_out)} paket cevapsız: görsel okuma ajanda")
    return Check(kim=KOMUT, ilerleme=prog, neden=f"{len(pk)} cevap işlenmemiş ya da geçersiz/şüpheli: apply "
                                                 "(work/transcribe/GECERSIZ.md)")
