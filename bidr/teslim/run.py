"""Teslim paketi (model yok): dekanlığa teslim edilecek tek klasör + zip.

    <out>/                      (vars. WS/BIDR-<dönem>-<Birim>/ (yapılandırma yoksa WS/teslim/); zip: aynı adla .zip)
      report.docx               dolu FR-0833 raporu (WS/report.docx'in kopyası)
      kanitlar/A/A.1/A.1.1/[1-OD3]. Ad.pdf
      kanitlar/.../[2-OD2]. Sayfa.html  +  [2-OD2]. Sayfa.pdf   (web kanıtının alınma tarihli PDF kopyası)
      kanit-dizini.xlsx / .csv  ölçüt, kanıt no, OD, ad, paketteki dosya, PDF kopyası, özgün bağlantı,
                                bağlantı kaynağı, alınma tarihi, durum
      EKSIK.txt                 yalnız eşleşmeyen satır ya da üretilemeyen PDF varsa

Eşleşme: raporun "Kanıtlar" listesindeki her satır (ölçüt, sıra no, OD) kanıt klasöründe
(`evidence/<A>/<A.1>/<A.1.1>/[n-ODk]. Ad.uzantı`) tam bir dosyayla eşleşmeli. Pakete yalnız listedeki
kanıtlar girer; listede olmayan dosya pakete alınmaz (uyarı). Eşleşmeyen satır, birden çok aday ya da
üretilemeyen web PDF'i paketi "eksik" yapar: paket yine yazılır, eksikler listelenir.

Kişisel veri maskeleme (`bidr maskele` çıktısı; yalnız okunur): `maskeleme-raporu.json` ve
`evidence-maskeli/` varsa kanıtın maskeli kopyası pakete girer (web kanıtının PDF'i de maskeli
HTML'den basılır). Maskeli kopya yoksa, eskiyse (kanıt dosyası rapordan sonra yeniden yazıldı) ya da
maskeleme başarısız / hata / desteklenmiyor ise özgün dosya girer: maskelenemedi diye hiçbir kanıt
paketten çıkarılmaz (kullanıcı kararı, 2026-11-20). Dizinin "Maskeleme" sütunu: `tamam` |
`eksik: elle bakılmalı` | `yapılmadı` (maskeleme çalıştırılmamış); elle bakılacak dosyalar paket
özetinde (`elle_bakilacak`) listelenir.

Kaynak ve çalışma alanı dosyalarına yalnız okumak için dokunulur; çıktı klasörü yalnız daha önce
bidr teslim'in yazdığı bir klasörse (işaret dosyası) silinip yeniden yazılır.
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import re
import shutil
import unicodedata
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from .mod import BAGLANTI, teslim_modu
from .web import BILINMIYOR, PdfHatasi, is_web, pdf_araci, web_pdf, web_url

SURUM = 1
MANIFEST = ".bidr-teslim.json"          # çalışma alanında (hat: teslim_tamam)
ISARET = ".bidr-teslim"                 # paket klasöründe (güvenli yeniden yazım); zip'e girmez
KANITLAR = "kanitlar"
RAPOR = "report.docx"
DIZIN = "kanit-dizini"
EKSIK = "EKSIK.txt"
SUTUNLAR = ["olcut", "kanit_no", "od", "ad", "dosya", "pdf_kopya", "ozgun_baglanti", "baglanti_kaynagi",
            "alinma_tarihi", "maskeleme", "isaretler", "durum"]
BASLIKLAR = ["Ölçüt", "Kanıt no", "OD", "Kanıt adı", "Paketteki dosya", "PDF kopyası", "Özgün bağlantı",
             "Bağlantı kaynağı", "Alınma tarihi", "Maskeleme", "İşaretler", "Durum"]
# bidr maskele çıktısı (bidr/mask/run.py; yalnız okunur)
MASKE_RAPOR, MASKE_KLASOR = "maskeleme-raporu.json", "evidence-maskeli"
MASKE_TAMAM, MASKE_ELLE, MASKE_YOK = "tamam", "eksik: elle bakılmalı", "yapılmadı"
RE_DOSYA = re.compile(r"^\[(\d+)-OD([1-5])\]\. (.+)\.([A-Za-z0-9]+)$")
RE_OLCUT = re.compile(r"^[A-D]\.\d+\.\d+$")


class TeslimError(RuntimeError):
    pass


@dataclass
class Sonuc:
    cikti: str
    zip: str | None
    tarih: str
    teslim_modu: str
    satirlar: list[dict] = field(default_factory=list)
    eksik: list[str] = field(default_factory=list)
    uyarilar: list[str] = field(default_factory=list)
    pdf_araci: str | None = None
    taslak: bool = False
    maskeleme: bool = False                                        # maskeleme raporu bulundu mu
    elle_bakilacak: list[dict] = field(default_factory=list)       # {dosya, neden}

    def ozet(self) -> dict:
        web = [r for r in self.satirlar if r["_web"]]
        return {"cikti": self.cikti, "zip": self.zip, "tarih": self.tarih, "teslim_modu": self.teslim_modu,
                "kanit": len(self.satirlar), "web": len(web), "web_pdf": sum(1 for r in web if r["pdf_kopya"]),
                "baglanti_bilinmiyor": sum(1 for r in web if r["ozgun_baglanti"] == BILINMIYOR),
                "eksik": self.eksik, "uyarilar": self.uyarilar, "pdf_araci": self.pdf_araci,
                "taslak": self.taslak,
                "maskeleme": {"rapor": self.maskeleme,
                              **{d: sum(1 for r in self.satirlar if r["maskeleme"] == d)
                                 for d in (MASKE_TAMAM, MASKE_ELLE, MASKE_YOK)}},
                "elle_bakilacak": self.elle_bakilacak}


def sha(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()[:16] if Path(p).exists() else ""


def _kanit_dosyalari(ev: Path) -> dict[tuple[str, int], list[tuple[int, Path]]]:
    """evidence/ → {(ölçüt, sıra): [(OD, dosya)]}; yalnız alt ölçüt klasöründeki kılavuz adlı dosyalar."""
    out: dict[tuple[str, int], list[tuple[int, Path]]] = {}
    for f in sorted(ev.rglob("*")):
        rel = f.relative_to(ev)
        if not f.is_file() or any(p.startswith(".") for p in rel.parts):
            continue
        m = RE_DOSYA.match(f.name)
        if not m or not RE_OLCUT.match(f.parent.name):
            continue
        out.setdefault((f.parent.name, int(m.group(1))), []).append((int(m.group(2)), f))
    return out


def _dizin(index: Path) -> dict[tuple[str, int], dict]:
    out: dict[tuple[str, int], dict] = {}
    if not index.exists():
        return out
    with open(index, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            m = re.match(r"^(\d+)_OD([1-5])$", (r.get("kanit_no") or "").strip())
            if m and r.get("olcut"):
                out.setdefault((r["olcut"].strip(), int(m.group(1))), r)
    return out


class Maske:
    """`bidr maskele` çıktısının okunur görünümü (rapor yoksa `var` False)."""

    def __init__(self, ws: Path, ev: Path):
        self.ev = ev
        self.rapor_yolu = ws / MASKE_RAPOR
        self.kayit: dict[str, dict] = {}
        self.klasor = ws / MASKE_KLASOR
        self.var = False
        try:
            js = json.loads(self.rapor_yolu.read_text(encoding="utf-8")) if self.rapor_yolu.exists() else None
        except (OSError, ValueError):
            js = None
        if isinstance(js, dict):
            self.var = True
            if js.get("maskeli_klasor"):
                self.klasor = Path(js["maskeli_klasor"])
            self.kayit = {unicodedata.normalize("NFC", str(r.get("dosya"))): r
                          for r in js.get("dosyalar") or [] if r.get("dosya")}
            self.zaman = self.rapor_yolu.stat().st_mtime

    def sec(self, f: Path) -> tuple[Path, str, str]:
        """(pakete girecek dosya, Maskeleme değeri, elle bakma nedeni)."""
        if not self.var:
            return f, MASKE_YOK, ""
        rel = f.relative_to(self.ev).as_posix()
        r = self.kayit.get(unicodedata.normalize("NFC", rel))
        if r is None:
            return f, MASKE_ELLE, "maskeleme raporunda yok (maskelemeden sonra dosyalandı mı? bidr maskele yeniden)"
        d = r.get("durum")
        if d != "tamam":
            return f, MASKE_ELLE, f"maskeleme {d or 'bilinmiyor'}: {r.get('neden') or ''}".strip()
        m = self.klasor / rel
        if not m.is_file():
            return f, MASKE_ELLE, "maskeli kopya bulunamadı"
        if f.stat().st_mtime > self.zaman:
            return f, MASKE_ELLE, "maskeli kopya eski (kanıt maskelemeden sonra yeniden dosyalandı; bidr maskele yeniden)"
        return m, MASKE_TAMAM, ""


def _tarih(s: str | None) -> dt.date:
    if not s:
        return dt.date.today()
    try:
        return dt.date.fromisoformat(str(s))
    except ValueError:
        raise TeslimError(f"tarih YYYY-AA-GG olmalı: {s}") from None


def _hazirla_cikti(out: Path, ws: Path, kaynak: Path | None) -> None:
    out = out.resolve()
    if out == ws or out in ws.parents:
        raise TeslimError(f"çıktı klasörü çalışma alanının kendisi ya da üstü olamaz: {out}")
    if kaynak is not None and (out == kaynak or kaynak in out.parents or out in kaynak.parents):
        raise TeslimError(f"çıktı klasörü kaynak klasörle iç içe olamaz: {out}")
    if out.exists():
        if not (out / ISARET).exists():
            if any(out.iterdir()):
                raise TeslimError(f"çıktı klasörü boş değil ve bidr teslim paketi değil: {out} "
                                  "(başka bir --out verin ya da klasörü boşaltın)")
        else:
            shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)
    (out / ISARET).write_text("bidr teslim paketi: bu klasör `bidr teslim` ile yeniden yazılır\n", encoding="utf-8")


def _kaynak(ws: Path) -> Path | None:
    from bidr.init.config import load_section
    k = (load_section(ws) or {}).get("kaynak")
    return Path(k).expanduser().resolve() if k else None


def paket_adi(ws: Path) -> str:
    """Varsayılan paket adı: `BIDR-<dönem>-<Birim>` (ör. BIDR-2025-Matematik-Bölümü); bilgi yoksa `teslim`."""
    try:
        from bidr.init.config import load_section
        sec = load_section(Path(ws)) or {}
    except Exception:  # noqa: BLE001 — ad için yapılandırma yoksa düz ad
        sec = {}
    birim = re.sub(r"[^\w]+", "-", str(sec.get("birim") or "")).strip("-")
    donem = sec.get("donem")
    if not birim or not donem:
        return "teslim"
    return f"BIDR-{donem}-{birim}"


def build(ws: Path, out: Path | None = None, *, docx_path: Path | None = None, tarih: str | None = None,
          zip_yap: bool = True, arac: str | object = "otomatik", canli: bool = False,
          taslak: bool = False) -> Sonuc:
    """Teslim paketini yazar. `arac`: "otomatik" | "chrome" | "weasyprint" ya da `bas(html, pdf, ag=)`
    yöntemi olan nesne. Web kanıtı varken araç yoksa PdfAraciYok (hiçbir şey yazılmadan)."""
    import docx

    from bidr.check.run import kanit_listeleri

    ws = Path(ws).expanduser().resolve()
    mod = teslim_modu(ws)
    rep = Path(docx_path).expanduser().resolve() if docx_path else ws / RAPOR
    ev, index = ws / "evidence", ws / "evidence-index.csv"
    if not rep.exists():
        raise TeslimError(f"rapor yok: {rep} (önce bidr render)")
    if not ev.is_dir():
        raise TeslimError(f"kanıt klasörü yok: {ev} (önce bidr file)")
    gun = _tarih(tarih)
    out = Path(out).expanduser().resolve() if out else ws / paket_adi(ws)

    listeler = kanit_listeleri(docx.Document(str(rep)))
    dosyalar = _kanit_dosyalari(ev)
    dizin = _dizin(index)
    res = Sonuc(str(out), None, gun.isoformat(), mod, taslak=taslak)
    maske = Maske(ws, ev)
    res.maskeleme = maske.var
    if not any(listeler.values()):
        res.eksik.append("raporda tanınan kanıt listesi satırı yok ('[1-OD3]. Ad' ya da '1_OD3: Ad')")

    # eşleşme (önce, araç gerekip gerekmediği bilinsin)
    plan: list[tuple[object, Path | None, str]] = []
    for olcut in sorted(listeler, key=_olcut_key):
        for k in listeler[olcut]:
            cand = dosyalar.get((olcut, k.no), [])
            same = [f for od, f in cand if od == k.od]
            if len(same) == 1:
                plan.append((k, same[0], ""))
            elif len(same) > 1:
                plan.append((k, None, "birden çok dosya: " + ", ".join(f.name for f in same)))
            elif cand:
                plan.append((k, None, f"OD uyuşmuyor: listede OD{k.od}, dosyada OD"
                                      + "/".join(str(od) for od, _ in cand)))
            else:
                plan.append((k, None, "kanıt klasöründe dosya yok"))
    listed = {(k.olcut, k.no) for k, _, _ in plan}
    for (olcut, n), lst in sorted(dosyalar.items(), key=lambda kv: (_olcut_key(kv[0][0]), kv[0][1])):
        if (olcut, n) not in listed:
            res.uyarilar.append(f"listede olmayan dosya pakete alınmadı: {olcut}/{lst[0][1].name}")

    pdf = None
    if any(f is not None and is_web(f) for _, f, _ in plan):
        pdf = pdf_araci(arac) if isinstance(arac, str) else arac       # PdfAraciYok: hiçbir şey yazılmaz
        res.pdf_araci = getattr(pdf, "ad", type(pdf).__name__)

    _hazirla_cikti(out, ws, _kaynak(ws))
    shutil.copyfile(rep, out / RAPOR)
    kok = out / KANITLAR
    damga_tarihi = gun.strftime("%d.%m.%Y")
    for k, f, neden in plan:
        r = dizin.get((k.olcut, k.no)) or {}
        no = f"{k.no}_OD{k.od}"
        ad = (r.get("ad") or "").strip() or _ad_sade(k.ad, k.baglanti)
        row = {"olcut": k.olcut, "kanit_no": no, "od": k.od, "ad": ad, "dosya": "", "pdf_kopya": "",
               "ozgun_baglanti": "", "baglanti_kaynagi": "", "alinma_tarihi": "", "maskeleme": "",
               "isaretler": (r.get("isaretler") or "").strip(), "durum": "tamam", "_web": False}
        res.satirlar.append(row)
        if f is None:
            row["durum"] = f"eksik: {neden}"
            res.eksik.append(f"{k.olcut} [{no}] {ad}: {neden}")
            continue
        # paketteki adlar NFC (Windows'ta ayrışık Türkçe karakter bozuk görünür)
        rel = Path(unicodedata.normalize("NFC", f.relative_to(ev).as_posix()))
        dst = kok / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        kaynak, row["maskeleme"], elle = maske.sec(f)    # maskelenemedi diye kanıt çıkarılmaz
        shutil.copyfile(kaynak, dst)
        row["dosya"] = f"{KANITLAR}/{rel.as_posix()}"
        if elle:
            res.elle_bakilacak.append({"dosya": row["dosya"], "neden": elle})
        url_dizin, src = (r.get("baglanti") or "").strip(), (r.get("baglanti_kaynagi") or "").strip()
        if not is_web(f):
            if url_dizin and (src != "klasor" or mod == BAGLANTI):
                row["ozgun_baglanti"], row["baglanti_kaynagi"] = url_dizin, src or "dizin"
            continue
        row["_web"] = True
        url, nereden = web_url(f, url_dizin, src)
        row["ozgun_baglanti"] = url or BILINMIYOR
        row["baglanti_kaynagi"] = nereden or ""
        pdf_dst = dst.with_suffix(".pdf")
        if pdf_dst.exists() or (f.with_suffix(".pdf")).exists():
            row["durum"] = "eksik: PDF kopyasının adı başka bir dosyayla çakışıyor"
            res.eksik.append(f"{k.olcut} [{no}] {ad}: PDF kopyası adı çakışıyor ({pdf_dst.name})")
            continue
        try:
            web_pdf(kaynak, pdf_dst, url=url, tarih=damga_tarihi, arac=pdf, canli=canli and kaynak == f)
        except PdfHatasi as e:
            row["durum"] = f"eksik: PDF kopyası üretilemedi ({e})"
            res.eksik.append(f"{k.olcut} [{no}] {ad}: PDF kopyası üretilemedi ({e})")
            continue
        row["pdf_kopya"] = f"{KANITLAR}/{pdf_dst.relative_to(kok).as_posix()}"
        row["alinma_tarihi"] = gun.isoformat()
        if not url:
            res.uyarilar.append(f"{k.olcut} [{no}] {ad}: web sayfasının özgün adresi bulunamadı "
                                f"(dizinde '{BILINMIYOR}'; biliniyorsa review.xlsx 'bağlantı' sütununa yazın)")

    _dizin_yaz(out, res.satirlar)
    if res.eksik or taslak:
        L = []
        if taslak:
            L += ["TASLAK PAKET", "", "Bu paket biçim denetimi (bidr denetle) geçmeden `--taslak` ile üretildi; "
                  "teslim edilmeden önce yeniden üretilmelidir.", ""]
        if res.eksik:
            L += ["EKSİK TESLİM PAKETİ", "", "Raporun kanıt listesindeki şu satırlar paketteki bir dosyayla "
                  "eşleşmedi ya da web kanıtının PDF kopyası üretilemedi:", ""]
            L += [f"- {e}" for e in res.eksik]
        (out / EKSIK).write_text("\n".join(L) + "\n", encoding="utf-8")
    if zip_yap:
        z = out.with_name(out.name + ".zip")
        _zip(out, z)
        res.zip = str(z)
    man = {"surum": SURUM, **res.ozet(), "report": str(rep), "report_sha": sha(rep), "index_sha": sha(index),
           "evidence_sha": sha(ev / ".bidr-evidence.json"), "maske_sha": sha(ws / MASKE_RAPOR)}
    (ws / MANIFEST).write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
    return res


def _ad_sade(ad: str, url: str | None) -> str:
    """Rapordaki satır adından görünür adres ekini çıkarır: "Ad (https://…)" → "Ad"."""
    if url and ad.endswith(f"({url})"):
        return ad[: -len(url) - 2].rstrip()
    return re.sub(r"\s*\(https?://[^)]*\)$", "", ad)


def _olcut_key(c: str) -> tuple:
    p = c.split(".")
    return (p[0], *[int(x) if x.isdigit() else 0 for x in p[1:]])


def _dizin_yaz(out: Path, satirlar: list[dict]) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font

    rows = [{k: r[k] for k in SUTUNLAR} for r in satirlar]
    with open(out / f"{DIZIN}.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(BASLIKLAR)
        for r in rows:
            w.writerow([r[k] for k in SUTUNLAR])
    wb = Workbook()
    ws = wb.active
    ws.title = "Kanıt dizini"
    ws.append(BASLIKLAR)
    for c in ws[1]:
        c.font = Font(bold=True)
    for r in rows:
        ws.append([r[k] for k in SUTUNLAR])
        url = r["ozgun_baglanti"]
        if url.startswith(("http://", "https://")):
            cell = ws.cell(row=ws.max_row, column=SUTUNLAR.index("ozgun_baglanti") + 1)
            cell.hyperlink = url
            cell.font = Font(color="0563C1", underline="single")
    widths = [9, 9, 5, 50, 60, 60, 50, 16, 13, 22, 30]
    for i, wdt in enumerate(widths, start=1):
        ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = wdt
    for row in ws.iter_rows(min_row=2):
        for c in row:
            c.alignment = Alignment(vertical="top", wrap_text=c.column in (4, 5, 6, 11))
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    wb.save(out / f"{DIZIN}.xlsx")


def _zip(out: Path, z: Path) -> None:
    tmp = z.with_suffix(".zip.tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(out.rglob("*")):
            rel = p.relative_to(out)
            if not p.is_file() or any(x.startswith(".") for x in rel.parts):
                continue
            ad = unicodedata.normalize("NFC", f"{out.name}/{rel.as_posix()}")
            zi = zipfile.ZipInfo(ad, (1980, 1, 1, 0, 0, 0))
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.flag_bits |= 0x800          # UTF-8 dosya adı (Türkçe karakter)
            zf.writestr(zi, p.read_bytes())
    tmp.replace(z)


# -- hat denetimi ----------------------------------------------------------------------------------

def load_manifest(ws: Path) -> dict | None:
    p = Path(ws) / MANIFEST
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
    except (OSError, ValueError):
        return None


def durum(c):
    """`teslim_tamam` (bidr/pipeline/checks.py): paket güncel ve eksiksiz mi."""
    from bidr.pipeline.checks import INSAN, KOMUT, Check
    ws = c.ws.root
    cmd = c.fmt(c.stage["komut"][0])
    try:
        mod = teslim_modu(ws)
    except ValueError as e:
        return Check(kim=INSAN, neden=str(e))
    m = load_manifest(ws)
    if not m:
        if mod == BAGLANTI:
            return Check(atlandi=True, neden="teslim modu baglanti: kanıtlar raporda bağlantıyla verilir; paket "
                                             "istenirse bidr teslim")
        return Check(kim=KOMUT, komutlar=[cmd], neden="teslim paketi üretilmedi (rapor ve kanıtlar dekanlığa "
                                                      "dosya olarak teslim edilecek)")
    rep = Path(m.get("report") or ws / RAPOR)
    if not Path(m.get("cikti") or "").is_dir() or (m.get("zip") and not Path(m["zip"]).exists()):
        return Check(kim=KOMUT, komutlar=[cmd], neden="teslim paketi klasörü ya da zip'i yok: yeniden üret")
    if (m.get("report_sha") != sha(rep) or m.get("index_sha") != sha(ws / "evidence-index.csv")
            or m.get("evidence_sha") != sha(ws / "evidence" / ".bidr-evidence.json")
            or m.get("teslim_modu") != mod or m.get("maske_sha", "") != sha(ws / MASKE_RAPOR)):
        return Check(kim=KOMUT, komutlar=[cmd], neden="teslim paketi eski: rapor, kanıt klasörü, maskeleme raporu "
                                                      "ya da teslim modu değişti")
    prog = {k: m.get(k) for k in ("kanit", "web", "web_pdf", "baglanti_bilinmiyor")}
    if m.get("taslak"):
        return Check(kim=KOMUT, komutlar=[cmd], ilerleme=prog,
                     neden="paket --taslak ile (denetim geçmeden) üretildi: denetim geçince yeniden üret")
    if m.get("eksik"):
        e = m["eksik"]
        return Check(kim=INSAN, komutlar=[cmd], ilerleme=prog,
                     neden=f"paket eksik ({len(e)}): " + "; ".join(e[:3]) + (" …" if len(e) > 3 else "")
                           + " — kaynağı düzelt (kanıt klasörü / PDF aracı) ve yeniden üret")
    uy = []
    if m.get("elle_bakilacak"):
        e = m["elle_bakilacak"]
        uy.append(f"{len(e)} kanıt maskelenmeden (özgün haliyle) pakette: elle bakılmalı (kanıt dizini 'Maskeleme'; "
                  f"{MANIFEST} elle_bakilacak): " + ", ".join(x["dosya"] for x in e[:3]) + (" …" if len(e) > 3 else ""))
    if (m.get("maskeleme") or {}).get("rapor") is False:
        uy.append("kişisel veri maskelemesi yapılmadı (kanıt dizini 'Maskeleme: yapılmadı'): bidr maskele")
    if m.get("baglanti_bilinmiyor"):
        uy.append(f"{m['baglanti_bilinmiyor']} web kanıtının özgün adresi bulunamadı (kanıt dizininde "
                  f"'{BILINMIYOR}'); biliniyorsa review.xlsx 'bağlantı' sütununa yazılır")
    return Check(bitti=True, ilerleme=prog, uyarilar=uy, neden=f"teslim paketi: {m['cikti']}"
                                                               + (f" + {m['zip']}" if m.get("zip") else ""))


def ozet_json(res: Sonuc) -> str:
    return json.dumps(res.ozet(), ensure_ascii=False, indent=1)
