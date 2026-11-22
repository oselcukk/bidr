"""Tamamlanma denetimi `describe_tamam` (`bidr/pipeline/checks.py`'de kayıtlı). Salt okunur."""
from __future__ import annotations

from pathlib import Path


def describe_tamam(c):
    from bidr.pipeline.checks import AJAN, KOMUT, Check, _sample

    from bidr.transcribe import run as T

    from . import run as R

    ws = c.ws
    if not ws.inventory.exists():
        return Check(kim=KOMUT, neden="inventory.csv yok")
    log = R.load_log(ws)
    sel = R.select_auto(ws, Path(c.sec["kaynak"]), log)
    applied = {d for d, r in log.items() if r.get("durum") == "uygulandi"}
    need = set(sel) | applied
    if not need:
        return Check(atlandi=True, neden="metni seyrek görsel belge/sayfa yok")
    from bidr import notlar as N
    notes = N.load(ws.root)
    done = {d for d in need if R.settled(ws, d, log, notes)}
    todo = need - done
    tlog = T.load_log(ws)
    mb = {d for d in done if log.get(d, {}).get("durum") == "metin_belgesi"}
    # ajanın 'metin sayfası' dediği belge sonradan transcribe ile yazıya geçirildiyse iş bitmiştir
    tb_ok = {d for d in mb if T.is_done(ws, d, tlog)}
    tb = sorted(mb - tb_ok)
    sk = sorted(d for d in done if log.get(d, {}).get("durum") == "atlandi")
    uy = []
    if tb:
        uy.append(f"{len(tb)} belgeyi ajan 'metin sayfası' saydı, betimlenmedi; yazıya geçirilmeli: "
                  + c.fmt("bidr transcribe prepare -w {ws}") + f" --only {','.join(tb)}")
    if sk:
        uy.append(f"{len(sk)} belge paketlenemedi (describe.jsonl neden): {_sample(sk)}")
    # seçimden sonra (ör. transcribe ile) metni çoğalan belgenin eski paketi seçim dışında kalır
    wd = R.work_dir(ws)
    disari = sorted(p.parent.name for p in wd.glob("*/*.json") if p.stem == p.parent.name
                    and p.parent.name not in need) if wd.exists() else []
    if disari:
        uy.append(f"{len(disari)} paket otomatik seçimde değil ('seçilen' sayısına girmez; paketlendikten "
                  f"sonra metni yazıya geçirildi ya da --only ile eklendi): betimlenmesi isteğe bağlı, cevabı "
                  f"yazılırsa apply işler: {_sample(disari)}")
    prog = {"secilen": len(need), "betimlenen": len(done - mb - set(sk)),
            "metin_belgesi": len(tb), "metin_belgesi_yazildi": len(tb_ok), "atlanan": len(sk)}
    if disari:
        prog["secim_disi_paket"] = len(disari)
    if not todo:
        return Check(bitti=True, ilerleme=prog, uyarilar=uy, neden=f"{len(done)} görsel belge işlendi")
    d = R.work_dir(ws)
    pk = {x for x in todo if (d / x / f"{x}.json").exists()}
    if todo - pk:
        return Check(kim=KOMUT, ilerleme=prog, uyarilar=uy,
                     neden=f"{len(todo - pk)} görsel belgenin paketi yok ({_sample(todo - pk)})")
    no_out = {x for x in pk if not (d / x / f"{x}.out.json").exists()}
    if no_out:
        return Check(kim=AJAN, ilerleme=prog, uyarilar=uy,
                     komutlar=["(ajan) work/describe/README.md'yi oku; her <doc_id>/ için görüntülere bakıp "
                               "<doc_id>.out.json yaz", c.fmt(c.stage["komut"][2])],
                     neden=f"{len(no_out)} paket cevapsız: görsel betimleme ajanda")
    return Check(kim=KOMUT, ilerleme=prog, uyarilar=uy, komutlar=[c.fmt(c.stage["komut"][2])],
                 neden=f"{len(pk)} cevap işlenmemiş ya da geçersiz/şüpheli: apply "
                       "(work/describe/GECERSIZ.md)")
