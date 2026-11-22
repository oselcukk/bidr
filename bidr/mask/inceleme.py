"""İnsan kontrolü: onay bekleyen bölgeler, bölge kararları, elle maskelenmiş sürüm yükleme.

- `bekleyenler(ws)`: `maskeleme-raporu.json`'dan onay bekleyen bölgeler (kararı verilmiş ama henüz
  uygulanmamışlar ayrı) ve bölgesi olmayan kontrol bekleyen dosyalar (yalnız elle maskeleme).
- `karar(ws, id, kapat|birak, kim)`: `maskeleme-kararlari.jsonl`'a satır ekler (bölgenin kutusu, türü ve
  kaynağıyla; yanlış bölgeye uygulanmasın). Bir sonraki `bidr maskele` uygular.
- `yukle(ws, kanit, maskeli)`: elle maskelenmiş sürümü kabul eder: `maskeleme-elle/<kanıt yolu>`'na
  kopyalanır, `maskeleme-elle.json`'a (kanıtın sha256'sıyla) yazılır, rapordaki kayıt
  `elle_maskelendi` olur ve kopya `evidence-maskeli/`'ye konur (yeniden `bidr maskele` gerekmez; sonraki
  çalıştırmalar kanıt değişmedikçe aynı sürümü kullanır). Yüklenen dosyada metin desenine uyan kişisel
  veri kalmışsa reddedilir (`zorla` ile kabul). Ön işlemede (kaynak raporu) maskeli kopyadaki dosyanın
  yerine konur; kayıt kaynağın sha256'sıyla tutulduğundan sonraki kanıt maskelemesine de taşınır.
- `ciz(ws, dosya, sayfa, kutu, kim)`: kullanıcı bölgesi (gerçek redaksiyon, kalıcı; şablon belleğine öneri
  örneği). `karar(ws, id, "sil")` yalnız kullanıcı bölgesini siler.
- `sayfa(ws, dosya, n, dpi, out)`: sayfanın PNG'si (maskesiz ya da `maskeli`) ve sayfa boyutları.

Rapor: `<ws>/maskeleme-raporu.json` (kanıt modu, `bidr file` sonrası) yoksa `<ws>/maskeleme-kaynak-raporu.json`
(`bidr maskele --kaynak … -w WS`, ön işleme). Kararlar `<ws>/maskeleme-kararlari.jsonl`'dadır ve bölge
kimliği belgenin sha256'sıyla başladığından iki modda (ve aynı içerikli kopyalarda) aynı belgeye uygulanır.
Kutular dışarıya (JSON, `ciz` girdisi) görüntülenen sayfanın PDF puanında (sol üst köken) verilir.
"""
from __future__ import annotations

import json
import os
import shutil
import unicodedata
from datetime import datetime
from pathlib import Path

from . import bolge as BG
from .run import ELLE, ELLE_DIR, ELLE_KAYIT, REPORT, bekliyor, elle_kayit, yaz_rapor


class IncelemeError(RuntimeError):
    pass


KAYNAK_RAPOR = "maskeleme-kaynak-raporu.json"


def _rapor_yolu(ws: Path) -> Path:
    p = Path(ws) / REPORT
    if p.is_file():
        return p
    k = Path(ws) / KAYNAK_RAPOR
    return k if k.is_file() else p


def _rapor(ws: Path) -> dict:
    p = _rapor_yolu(ws)
    if not p.is_file():
        raise IncelemeError(f"maskeleme raporu yok: {p} (önce bidr maskele -w {ws} ya da "
                            f"bidr maskele --kaynak KLASÖR --out KOPYA -w {ws})")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except ValueError as e:
        raise IncelemeError(f"maskeleme raporu okunamadı: {e}") from None


def _kaynak_modu(rap: dict) -> bool:
    return rap.get("mod") == "kaynak"


def _durum(rec: dict) -> str:
    d = rec.get("durum")
    if d == "tamam":
        return "tamam"
    if d == ELLE:
        return "elle_maskeli"
    return "karar_bekliyor"


def _gorunen(kutu, sayfa_bilgi: dict | None):
    """Bölge kutusu (döndürülmemiş sayfa) → görüntülenen sayfa (matris; birim değilse)."""
    if not sayfa_bilgi or not sayfa_bilgi.get("donus"):
        return [round(float(v), 2) for v in kutu]
    a, b, c, d, e, f = sayfa_bilgi["matris"]
    xs, ys = [], []
    for x, y in ((kutu[0], kutu[1]), (kutu[2], kutu[3]), (kutu[0], kutu[3]), (kutu[2], kutu[1])):
        xs.append(a * x + c * y + e)
        ys.append(b * x + d * y + f)
    return [round(min(xs), 2), round(min(ys), 2), round(max(xs), 2), round(max(ys), 2)]


def _ic_kutu(kutu, sayfa_bilgi: dict | None):
    """Görüntülenen sayfa kutusu → döndürülmemiş sayfa (`_gorunen`'in tersi)."""
    if not sayfa_bilgi or not sayfa_bilgi.get("donus"):
        return [round(float(v), 2) for v in kutu]
    a, b, c, d, e, f = sayfa_bilgi["matris"]
    det = a * d - b * c
    ia, ib, ic, id_ = d / det, -b / det, -c / det, a / det
    ie, if_ = -(e * ia + f * ic), -(e * ib + f * id_)
    return _gorunen(kutu, {"donus": 1, "matris": [ia, ib, ic, id_, ie, if_]})


def _sayfa_bilgi(rec: dict, n: int) -> dict | None:
    for s in rec.get("sayfalar") or []:
        if isinstance(s, dict) and int(s.get("no") or 0) == int(n):
            return s
    return None


def bekleyenler(ws: Path) -> dict:
    """→ {"bolgeler": onay bekleyenler, "karar_verilmis", "bolgesiz", "dosya": sayı,
    "tum_bolgeler": bütün bölgeler (kapatılanlar, bırakılanlar, henüz uygulanmamış kullanıcı çizimleri dahil),
    "dosyalar": dosya başına {dosya, belge_kimligi, durum (tamam | karar_bekliyor | elle_maskeli),
    bidr_durum, neden, sayfa_sayisi, sayfalar [{no, genislik, yukseklik}] (pt)}, "rapor", "mod"}.
    Bölge alanları: id, dosya, belge_kimligi, sayfa, kutu (görüntülenen sayfa, pt), tur, karar, neden, kaynak,
    guven, kapali, kim, zaman."""
    ws = Path(ws).expanduser().resolve()
    rap = _rapor(ws)
    kararlar = BG.kararlar_yukle(ws)
    bolgeler, verilmis, bolgesiz, tum, dosyalar = [], [], [], [], []
    for r in rap.get("dosyalar") or []:
        sha = r.get("sha256") or ""
        onay = BG.onay_bekleyen(r.get("bolgeler"))

        def item(b, r=r, sha=sha):
            x = {"dosya": r["dosya"], "belge_kimligi": sha,
                 **{k: b.get(k) for k in ("id", "sayfa", "tur", "karar", "neden", "kaynak", "guven")},
                 "kutu": _gorunen(b["kutu"], _sayfa_bilgi(r, b.get("sayfa") or 1)),
                 "kapali": bool(b.get("kapali", b.get("karar") == BG.KAPATILDI))}
            ins = b.get("insan") or {}
            x["kim"], x["zaman"] = ins.get("kim"), ins.get("zaman")
            return x
        for b in onay:
            it = item(b)
            if b["id"] in kararlar:
                it["karar"] = kararlar[b["id"]]["karar"]
                verilmis.append(it)
            else:
                bolgeler.append(it)
        ids = set()
        for b in r.get("bolgeler") or []:
            tum.append(item(b))
            ids.add(b.get("id"))
        if sha:                                   # henüz maskelemeye uygulanmamış kullanıcı çizimleri
            for i, d in sorted(BG.dosya_kararlari(kararlar, sha[:8]).items()):
                if d.get("kaynak") == BG.KULLANICI and i not in ids and d.get("kutu"):
                    b = BG.yeni(int(d.get("sayfa") or 1), d["kutu"], BG.KULLANICI,
                                BG.KAPATILDI if d["karar"] == "kapat" else BG.BIRAKILDI,
                                "kullanıcı çizimi (sonraki maskelemede uygulanır)", BG.KULLANICI, 1.0)
                    b["id"], b["insan"] = i, {"kim": d.get("kim"), "zaman": d.get("zaman")}
                    x = item(b)
                    x["uygulandi"] = False
                    tum.append(x)
        sayfalar = [{"no": s.get("no"), "genislik": s.get("genislik"), "yukseklik": s.get("yukseklik")}
                    for s in r.get("sayfalar") or [] if isinstance(s, dict)]
        d = {"dosya": r["dosya"], "belge_kimligi": sha, "durum": _durum(r), "bidr_durum": r.get("durum"),
             "neden": r.get("neden")}
        if sayfalar:
            d["sayfa_sayisi"], d["sayfalar"] = len(sayfalar), sayfalar
        dosyalar.append(d)
        if bekliyor(r) and not onay:
            bolgesiz.append({"dosya": r["dosya"], "durum": r.get("durum"), "neden": r.get("neden")})
    return {"bolgeler": bolgeler, "karar_verilmis": verilmis, "bolgesiz": bolgesiz,
            "dosya": len({x["dosya"] for x in bolgeler + bolgesiz}), "tum_bolgeler": tum, "dosyalar": dosyalar,
            "rapor": str(_rapor_yolu(ws)), "mod": "kaynak" if _kaynak_modu(rap) else "kanit"}


def _bul(rap: dict, bolge_id: str) -> tuple[dict, dict] | None:
    for r in rap.get("dosyalar") or []:
        for b in r.get("bolgeler") or []:
            if b.get("id") == bolge_id:
                return r, b
    return None


def karar(ws: Path, bolge_id: str, karar_: str, kim: str | None = None) -> dict:
    ws = Path(ws).expanduser().resolve()
    if karar_ not in ("kapat", "birak", "sil"):
        raise IncelemeError("karar 'kapat', 'birak' ya da 'sil' olmalı")
    kk = BG.kararlar_yukle(ws)
    if karar_ == "sil":
        d = kk.get(bolge_id)
        if d is None or d.get("kaynak") != BG.KULLANICI:
            raise IncelemeError(f"silinecek kullanıcı bölgesi yok: {bolge_id} (yalnız `ciz` ile çizilen bölge silinir)")
        out = BG.satir_yaz(ws, {"id": bolge_id, "karar": "sil", "kim": kim or os.environ.get("USER") or "?",
                                "zaman": datetime.now().astimezone().isoformat(timespec="seconds")})
        try:
            from .sablon import SablonBellegi
            sb = SablonBellegi.calisma_alani(ws)
            if sb.unut(bolge_id):
                sb.kaydet()
        except Exception:                            # noqa: BLE001 — şablon belleği isteğe bağlı
            pass
        return out
    if bolge_id in kk and kk[bolge_id].get("kaynak") == BG.KULLANICI:     # kullanıcı bölgesini aç/kapat
        d = dict(kk[bolge_id], karar=karar_, kim=kim or os.environ.get("USER") or "?",
                 zaman=datetime.now().astimezone().isoformat(timespec="seconds"))
        return BG.satir_yaz(ws, d)
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
    rec, src = _dosya_bul(ws, rap, kanit)
    if src is None:
        raise IncelemeError(f"dosyanın özgünü bulunamadı (kap üyesi olabilir): {rec['dosya']}")
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
    if _kaynak_modu(rap):
        return _yukle_kaynak(ws, rap, rec, src, m, kim, uyari)
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


# ---------------------------------------------------------------- dosya bulma, ön işleme yüklemesi

def _dosya_bul(ws: Path, rap: dict, ad) -> tuple[dict, Path | None]:
    """Rapordaki dosya kaydı ve özgün dosyanın yolu. `ad`: rapordaki `dosya` (kanıt/kaynak klasörüne göreli),
    klasördeki mutlak yol ya da belge kimliği (sha256 ya da en az 8 hanelik öneki)."""
    from bidr.ingest import containers as C
    kaynak = _kaynak_modu(rap)
    base = Path(rap.get("kaynak_klasor") if kaynak else (rap.get("kanit_klasoru") or Path(ws) / "evidence"))
    recs = [r for r in rap.get("dosyalar") or [] if r.get("dosya")]
    s = str(ad)
    rec = next((r for r in recs if _nfc(r["dosya"]) == _nfc(s)), None)
    if rec is None and len(s) >= 8 and all(c in "0123456789abcdef" for c in s.lower()):
        hits = [r for r in recs if (r.get("sha256") or "").startswith(s.lower())]
        rec = hits[0] if hits else None
    if rec is None:
        k = Path(s).expanduser()
        if k.is_absolute() or ((Path.cwd() / k).exists() and not (base / k).exists()):
            try:
                rel = k.resolve().relative_to(base.resolve()).as_posix()
            except ValueError:
                raise IncelemeError(f"dosya {'kaynak' if kaynak else 'kanıt'} klasöründe değil: {k} ({base})") from None
            rec = next((r for r in recs if _nfc(r["dosya"]) == _nfc(rel)), None)
    if rec is None:
        raise IncelemeError(f"maskeleme raporunda yok: {s}")
    if C.SEP in rec["dosya"]:
        return rec, None
    src = base / rec["dosya"]
    return rec, (src if src.is_file() else None)


def _maskeli_yol(ws: Path, rap: dict, rec: dict) -> Path | None:
    if _kaynak_modu(rap):
        p = Path(rap["maskeli_klasor"]) / (rec.get("hedef") or rec["dosya"])
        return p if p.is_file() else None
    for p in ([ws / rec["kopya"]] if rec.get("kopya") else []) + \
            [Path(rap.get("maskeli_klasor") or ws / "evidence-maskeli") / (rec.get("maskeli") or rec["dosya"])]:
        if p.is_file():
            return p
    return None


def _yukle_kaynak(ws: Path, rap: dict, rec: dict, src: Path, m: Path, kim, uyari) -> dict:
    """Ön işleme: elle maskelenmiş sürüm maskeli kopya ağacındaki dosyanın yerine konur ve kaynağın sha256'sıyla
    kaydedilir (sonraki `--kaynak` ve kanıt maskelemeleri aynı içerikli belgede bu sürümü kullanır)."""
    from .onbellek import sha256_file
    sha = rec.get("sha256") or sha256_file(src)
    ad = "kaynak/" + rec["dosya"]
    hedef = ws / ELLE_DIR / Path(ad).with_suffix(m.suffix or Path(rec["dosya"]).suffix)
    hedef.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(m, hedef)
    zaman = datetime.now().astimezone().isoformat(timespec="seconds")
    kayit = elle_kayit(ws)
    kayit[ad] = {"dosya": hedef.relative_to(ws).as_posix(), "kaynak_sha": sha, "sha256": sha256_file(hedef),
                 "kim": kim or os.environ.get("USER") or "?", "zaman": zaman}
    (ws / ELLE_KAYIT).write_text(json.dumps(kayit, ensure_ascii=False, indent=1), encoding="utf-8")
    out = None
    if rec.get("hedef") and rap.get("maskeli_klasor"):
        out = Path(rap["maskeli_klasor"]) / rec["hedef"]
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(hedef, out)
    keep = {k_: rec[k_] for k_ in ("dosya", "hedef", "bicim", "sha256", "bolgeler", "bolge_ozet", "sayfalar") if k_ in rec}
    rec.clear()
    rec.update(keep, durum=ELLE, elle_bakilmali=False, neden="elle maskelendi (bidr maskele yukle)",
               elle_yukleme={"kim": kayit[ad]["kim"], "zaman": zaman, "sha256": kayit[ad]["sha256"]}, uyarilar=uyari)
    rap["elle_bakilmali"] = [y for y in rap.get("elle_bakilmali") or [] if _nfc(y.get("dosya", "")) != _nfc(keep["dosya"])]
    yaz_rapor(_rapor_yolu(ws), rap)
    if rap.get("rapor") and Path(rap["rapor"]).is_file():
        yaz_rapor(Path(rap["rapor"]), {k_: v for k_, v in rap.items() if k_ != "rapor"})
    return {"dosya": keep["dosya"], "elle": hedef.relative_to(ws).as_posix(), "maskeli": str(out or hedef),
            "uyarilar": uyari}


# ---------------------------------------------------------------- kullanıcı çizimi

def ciz(ws: Path, ad, sayfa_no: int, kutu, kim: str | None = None) -> dict:
    """Kullanıcı bölgesi: `kutu` görüntülenen sayfada PDF puanı (sol üst köken). Karar dosyasına `kapat`
    kararıyla yazılır; sonraki her maskelemede gerçek redaksiyon olarak uygulanır (yeniden taramada
    kaybolmaz). Şablon belleğine öneri örneği olarak da öğretilir (aynı formdan başka belgede
    `onay_bekliyor`). → bölge kaydı (id dahil)."""
    from .formats import kind_of
    from .onbellek import sha256_file
    ws = Path(ws).expanduser().resolve()
    rap = _rapor(ws)
    rec, src = _dosya_bul(ws, rap, ad)
    if src is None:
        raise IncelemeError(f"dosyanın özgünü bulunamadı (kap üyesi olabilir): {rec['dosya']}")
    kind = kind_of(src)
    if kind not in ("pdf", "gorsel"):
        raise IncelemeError(f"bu biçimde çizimle maskeleme yok ({src.suffix}): elle maskeleyip `bidr maskele yukle` "
                            "kullanın")
    try:
        k = [float(v) for v in (kutu.split(",") if isinstance(kutu, str) else kutu)]
    except ValueError:
        raise IncelemeError("--kutu x0,y0,x1,y1 (sayı) olmalı") from None
    if len(k) != 4:
        raise IncelemeError("--kutu dört sayı olmalı: x0,y0,x1,y1")
    k = [min(k[0], k[2]), min(k[1], k[3]), max(k[0], k[2]), max(k[1], k[3])]
    bilgi = sayfa_bilgileri(src, kind)
    if not 1 <= int(sayfa_no) <= len(bilgi):
        raise IncelemeError(f"sayfa yok: {sayfa_no} (1-{len(bilgi)})")
    sb = bilgi[int(sayfa_no) - 1]
    k = [max(0.0, k[0]), max(0.0, k[1]), min(sb["genislik"], k[2]), min(sb["yukseklik"], k[3])]
    if k[2] - k[0] < 1 or k[3] - k[1] < 1:
        raise IncelemeError("kutu sayfanın dışında ya da çok küçük")
    ic = _ic_kutu(k, sb)
    sha = rec.get("sha256") or sha256_file(src)
    bid = BG.kullanici_id(ws, sha[:8], int(sayfa_no))
    d = {"id": bid, "karar": "kapat", "kim": kim or os.environ.get("USER") or "?",
         "zaman": datetime.now().astimezone().isoformat(timespec="seconds"), "kutu": ic, "tur": BG.KULLANICI,
         "kaynak": BG.KULLANICI, "sayfa": int(sayfa_no), "dosya": rec["dosya"], "sha256": sha}
    BG.satir_yaz(ws, d)
    uyari = _sablona_ogret(ws, src, kind, int(sayfa_no), ic, bid)
    out = {"id": bid, "dosya": rec["dosya"], "belge_kimligi": sha, "sayfa": int(sayfa_no), "kutu": k,
           "tur": BG.KULLANICI, "karar": BG.KAPATILDI, "neden": f"kullanıcı çizimi ({d['kim']})",
           "kaynak": BG.KULLANICI, "guven": 1.0, "kapali": True, "kim": d["kim"], "zaman": d["zaman"],
           "uygulandi": False}
    if uyari:
        out["uyari"] = uyari
    return out


def _sablona_ogret(ws: Path, src: Path, kind: str, sayfa_no: int, kutu_pt, bid: str) -> str | None:
    """Kullanıcı çizimini form şablon belleğine öneri örneği olarak öğret (OCR + numpy gerekir; yoksa uyarı).
    Düzlem maskeleme hattınınki: PDF sayfası 300 dpi, görsel OCR görünümü."""
    try:
        from . import alan as AL
        from . import raster
        from .ocr import ocr_available, ocr_words
        from .sablon import SablonBellegi, parmak_izi
        if AL.np is None or not ocr_available():
            return "şablon belleğine öğretilmedi (OCR ya da numpy yok)"
        if kind == "pdf":
            from .formats import _fitz
            fitz = _fitz()
            doc = fitz.open(str(src))
            try:
                page = doc[sayfa_no - 1]
                img = raster.render(page, 300)
                f = 300 / 72.0
                px = [v * f for v in (fitz.Rect(*kutu_pt) * page.rotation_matrix)]
            finally:
                doc.close()
        else:
            im = raster._open_image(src)
            img, f = raster._ocr_view(im)
            sc = raster.image_scale(im)
            px = [v / sc * f for v in kutu_pt]
        words = ocr_words(img)
        yapi = AL.Yapi(img, AL._page_h(words, img.size[1]), words)
        sb = SablonBellegi.calisma_alani(ws)
        if sb.ogren(parmak_izi(words, img.size[0], img.size[1], yapi), [px], kaynak=bid, oneri=True) is None:
            return "şablon belleğine öğretilmedi (sayfada yeterli basılı çapa yok)"
        sb.kaydet()
    except Exception as e:                           # noqa: BLE001 — öğrenme isteğe bağlı; çizim yine geçerli
        return f"şablon belleğine öğretilemedi ({type(e).__name__})"
    return None


# ---------------------------------------------------------------- sayfa görüntüsü

def sayfa_bilgileri(path: Path, kind: str) -> list[dict]:
    """Görüntülenen sayfa boyutları (pt) ve döndürme matrisi."""
    if kind == "pdf":
        from .formats import _fitz, sayfa_bilgisi
        fitz = _fitz()
        if fitz is None:
            raise IncelemeError("PyMuPDF kurulu değil (pip install 'bidr[maske]')")
        doc = fitz.open(str(path))
        try:
            return [sayfa_bilgisi(pg) for pg in doc]
        finally:
            doc.close()
    from .raster import _open_image, image_scale
    im = _open_image(path)
    sc = image_scale(im)
    return [{"no": 1, "genislik": round(im.width * sc, 2), "yukseklik": round(im.height * sc, 2), "donus": 0,
             "matris": [1, 0, 0, 1, 0, 0]}]


def sayfa(ws: Path, ad, sayfa_no: int, dpi: int, out: Path | None, *, maskeli: bool = False) -> dict:
    """Belgenin `sayfa_no`. sayfasının PNG'si (ölçek dpi/72; kutular pt × dpi/72). Word/Excel/eski biçim
    LibreOffice ile PDF'e çevrilir. `maskeli`: maskeli kopyanın (ya da elle maskelenmiş sürümün) sayfası.
    → {dosya, belge_kimligi, sayfa, sayfa_sayisi, genislik, yukseklik, sayfalar, dpi, png}."""
    import tempfile
    from .formats import _fitz, kind_of
    ws = Path(ws).expanduser().resolve()
    rap = _rapor(ws)
    rec, src = _dosya_bul(ws, rap, ad)
    if maskeli:
        src = _maskeli_yol(ws, rap, rec)
        if src is None:
            raise IncelemeError(f"maskeli kopya yok: {rec['dosya']}")
    if src is None:
        raise IncelemeError(f"dosyanın özgünü bulunamadı (kap üyesi olabilir): {rec['dosya']}")
    dpi = max(20, min(int(dpi), 600))
    with tempfile.TemporaryDirectory(prefix="bidr-sayfa-") as td:
        kind = kind_of(src)
        if kind not in ("pdf", "gorsel"):
            from .eski import ConvertError, _soffice_pdf, soffice_path
            if not soffice_path():
                raise IncelemeError(f"{src.suffix} sayfa görüntüsü için LibreOffice (soffice) gerekli")
            try:
                src = _soffice_pdf(src, Path(td), src.suffix.lower())
            except ConvertError as e:
                raise IncelemeError(f"PDF'e çevrilemedi: {e}") from None
            kind = "pdf"
        bilgi = sayfa_bilgileri(src, kind)
        n = int(sayfa_no)
        if not 1 <= n <= len(bilgi):
            raise IncelemeError(f"sayfa yok: {n} (1-{len(bilgi)})")
        if out is not None:
            out = Path(out).expanduser()
            out.parent.mkdir(parents=True, exist_ok=True)
            if kind == "pdf":
                fitz = _fitz()
                doc = fitz.open(str(src))
                try:
                    doc[n - 1].get_pixmap(dpi=dpi).save(str(out))
                finally:
                    doc.close()
            else:
                from PIL import Image
                from .raster import _open_image
                im = _open_image(src).convert("RGB")
                b = bilgi[0]
                im = im.resize((max(1, round(b["genislik"] * dpi / 72)), max(1, round(b["yukseklik"] * dpi / 72))),
                               Image.LANCZOS)
                im.save(str(out), format="PNG")
    b = bilgi[n - 1]
    return {"dosya": rec["dosya"], "belge_kimligi": rec.get("sha256") or "", "sayfa": n, "sayfa_sayisi": len(bilgi),
            "genislik": b["genislik"], "yukseklik": b["yukseklik"], "boyut": [b["genislik"], b["yukseklik"]],
            "sayfalar": [{"no": x["no"], "genislik": x["genislik"], "yukseklik": x["yukseklik"]} for x in bilgi],
            "dpi": dpi, "maskeli": maskeli, "png": str(out) if out is not None else None}
