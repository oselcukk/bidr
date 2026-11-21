"""İnsan kontrolü: onay bekleyen bölgeler, bölge kararları, elle maskelenmiş sürüm yükleme.

- `bekleyenler(ws)`: `maskeleme-raporu.json`'dan onay bekleyen bölgeler (kararı verilmiş ama henüz
  uygulanmamışlar ayrı) ve bölgesi olmayan kontrol bekleyen dosyalar (yalnız elle maskeleme).
- `karar(ws, id, kapat|birak, kim)`: `maskeleme-kararlari.jsonl`'a satır ekler (bölgenin kutusu, türü ve
  kaynağıyla; yanlış bölgeye uygulanmasın). Bir sonraki `bidr maskele` uygular.
- `yukle(ws, kanit, maskeli)`: elle maskelenmiş sürümü kabul eder: `maskeleme-elle/<kanıt yolu>`'na
  kopyalanır, `maskeleme-elle.json`'a (kanıtın sha256'sıyla) yazılır, rapordaki kayıt
  `elle_maskelendi` olur ve kopya `evidence-maskeli/`'ye konur (yeniden `bidr maskele` gerekmez; sonraki
  çalıştırmalar kanıt değişmedikçe aynı sürümü kullanır). Yüklenen dosyada metin desenine uyan kişisel
  veri kalmışsa reddedilir (`zorla` ile kabul).
"""
from __future__ import annotations

import json
import shutil
import unicodedata
from datetime import datetime
from pathlib import Path

from . import bolge as BG
from .run import ELLE, ELLE_DIR, ELLE_KAYIT, REPORT, bekliyor, elle_kayit, yaz_rapor


class IncelemeError(RuntimeError):
    pass


def _rapor(ws: Path) -> dict:
    p = Path(ws) / REPORT
    if not p.is_file():
        raise IncelemeError(f"maskeleme raporu yok: {p} (önce bidr maskele -w {ws})")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except ValueError as e:
        raise IncelemeError(f"maskeleme raporu okunamadı: {e}") from None


def bekleyenler(ws: Path) -> dict:
    ws = Path(ws).expanduser().resolve()
    rap = _rapor(ws)
    kararlar = BG.kararlar_yukle(ws)
    bolgeler, verilmis, bolgesiz = [], [], []
    for r in rap.get("dosyalar") or []:
        onay = BG.onay_bekleyen(r.get("bolgeler"))
        for b in onay:
            item = {"dosya": r["dosya"], **{k: b.get(k) for k in ("id", "sayfa", "kutu", "tur", "neden", "kaynak", "guven")}}
            if b["id"] in kararlar:
                item["karar"] = kararlar[b["id"]]["karar"]
                verilmis.append(item)
            else:
                bolgeler.append(item)
        if bekliyor(r) and not onay:
            bolgesiz.append({"dosya": r["dosya"], "durum": r.get("durum"), "neden": r.get("neden")})
    return {"bolgeler": bolgeler, "karar_verilmis": verilmis, "bolgesiz": bolgesiz,
            "dosya": len({x["dosya"] for x in bolgeler + bolgesiz})}


def _bul(rap: dict, bolge_id: str) -> tuple[dict, dict] | None:
    for r in rap.get("dosyalar") or []:
        for b in r.get("bolgeler") or []:
            if b.get("id") == bolge_id:
                return r, b
    return None


def karar(ws: Path, bolge_id: str, karar_: str, kim: str | None = None) -> dict:
    ws = Path(ws).expanduser().resolve()
    if karar_ not in ("kapat", "birak"):
        raise IncelemeError("karar 'kapat' ya da 'birak' olmalı")
    hit = _bul(_rapor(ws), bolge_id)
    if hit is None:
        raise IncelemeError(f"bölge bulunamadı: {bolge_id} (bidr maskele bolgeler -w {ws})")
    _, b = hit
    if karar_ == "kapat" and b.get("kaynak") == "model_metni":
        raise IncelemeError("model metni bölgesinin yeri bilinmiyor (yalnız sayfa): kapatmak için maskeli sürümü "
                            "elle hazırlayıp `bidr maskele yukle` kullanın; değer kişisel veri değilse 'birak'")
    if b.get("karar") == BG.KAPATILDI and karar_ == "birak" and b.get("tur") != "imza":
        raise IncelemeError("desen/etiket alanı bulgusu 'birak' ile açılamaz (yalnız imza ve onay bekleyen bölgeler)")
    return BG.karar_yaz(ws, bolge_id, karar_, kim, kutu=b.get("kutu"), tur=b.get("tur"), kaynak=b.get("kaynak"))


def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def yukle(ws: Path, kanit: Path | str, maskeli: Path | str, kim: str | None = None, *, zorla: bool = False) -> dict:
    import os
    from .detect import MaskRules, read_ws_config
    from .formats import kind_of, scan_file
    from .onbellek import sha256_file
    ws = Path(ws).expanduser().resolve()
    rap = _rapor(ws)
    ev = Path(rap.get("kanit_klasoru") or ws / "evidence")
    k = Path(kanit).expanduser()
    if k.is_absolute() or (Path.cwd() / k).exists() and not (ev / k).exists():
        k = k.resolve()
        try:
            rel = k.relative_to(ev.resolve()).as_posix()
        except ValueError:
            raise IncelemeError(f"kanıt dosyası kanıt klasöründe değil: {k} ({ev})") from None
    else:
        rel = k.as_posix()
    recs = {_nfc(r["dosya"]): r for r in rap.get("dosyalar") or []}
    rec = recs.get(_nfc(rel))
    if rec is None:
        raise IncelemeError(f"maskeleme raporunda yok: {rel}")
    src = ev / rec["dosya"]
    m = Path(maskeli).expanduser().resolve()
    if not m.is_file():
        raise IncelemeError(f"maskeli dosya yok: {m}")
    if not src.is_file():
        raise IncelemeError(f"kanıt dosyası yok: {src}")
    uyari = []
    if kind_of(m) is not None:
        rules = MaskRules.from_config(read_ws_config(ws), ws)
        try:
            sc = scan_file(m, rules)
            kalan = {k_: n for k_, n in (sc.get("bulgular") or {}).items() if n}
        except Exception as e:                       # noqa: BLE001 — okunamayan yükleme: uyarıyla
            kalan, sc = {}, {}
            uyari.append(f"yüklenen dosya taranamadı ({type(e).__name__})")
        if kalan:
            msg = "yüklenen dosyada kişisel veri kalmış görünüyor: " + ", ".join(f"{a}×{b}" for a, b in sorted(kalan.items()))
            if not zorla:
                raise IncelemeError(msg + " (yine de kabul için --zorla)")
            uyari.append(msg + " (--zorla ile kabul edildi)")
    hedef = ws / ELLE_DIR / Path(rec["dosya"]).with_suffix(m.suffix or Path(rec["dosya"]).suffix)
    hedef.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(m, hedef)
    zaman = datetime.now().astimezone().isoformat(timespec="seconds")
    kayit = elle_kayit(ws)
    kayit[rec["dosya"]] = {"dosya": hedef.relative_to(ws).as_posix(), "kaynak_sha": sha256_file(src),
                           "sha256": sha256_file(hedef), "kim": kim or os.environ.get("USER") or "?", "zaman": zaman}
    (ws / ELLE_KAYIT).write_text(json.dumps(kayit, ensure_ascii=False, indent=1), encoding="utf-8")
    # raporu hemen güncelle: kopya evidence-maskeli/'ye, kayıt elle_maskelendi
    mk = Path(rap.get("maskeli_klasor") or ws / "evidence-maskeli")
    if rec.get("kopya"):
        kp = ws / rec["kopya"]
        if kp.is_file():
            kp.unlink()
    out = mk / Path(rec["dosya"]).with_suffix(hedef.suffix)
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(hedef, out)
    keep = {k_: rec[k_] for k_ in ("dosya", "bicim", "sha256", "bolgeler", "bolge_ozet") if k_ in rec}
    rec.clear()
    rec.update(keep, durum=ELLE, elle_bakilmali=False, neden="elle maskelendi (bidr maskele yukle)",
               elle_yukleme={"kim": kayit[keep["dosya"]]["kim"], "zaman": zaman, "sha256": kayit[keep["dosya"]]["sha256"]},
               uyarilar=uyari)
    if out.relative_to(mk).as_posix() != keep["dosya"]:
        rec["maskeli"] = out.relative_to(mk).as_posix()
    rap["yayimlanamaz"] = [y for y in rap.get("yayimlanamaz") or [] if _nfc(y.get("dosya", "")) != _nfc(keep["dosya"])]
    from collections import Counter
    dur = Counter(r["durum"] for r in rap.get("dosyalar") or [])
    oz = rap.setdefault("ozet", {})
    for d in ("tamam", "basarisiz", "taranamadi", "hata", "desteklenmiyor", ELLE):
        oz.pop(d, None)
    oz.update(dict(sorted(dur.items())))
    oz["kontrol_bekleyen_dosya"] = sum(1 for r in rap.get("dosyalar") or [] if bekliyor(r))
    yaz_rapor(ws / REPORT, rap)
    return {"dosya": keep["dosya"], "elle": hedef.relative_to(ws).as_posix(), "maskeli": str(out), "uyarilar": uyari}
