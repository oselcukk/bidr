"""`bidr denetle -w WS [--docx yol] [--sablon FR-0833.docx] [--kanit klasör] [--out denetim.json]`.

Üretilmiş raporu kılavuz biçim kurallarına göre denetler (salt okur; render'dan bağımsız).
Çıkış kodu: 0 kritik bulgu yok; 1 kritik bulgu var ("yayıma hazır değil"); 2 girdi hatası.
Şablon verilmezse config.yaml `rapor.sablon`, o da yoksa son render kaydındaki şablon
(`.bidr-render.json`) kullanılır. Kural değerleri config.yaml `rapor.denetim`. Rubrikte insan
onayı olmadan (kod önerisiyle) işaretlenen OD'ler `od_onay_bekliyor` uyarısı olur (render kaydı ya
da `audit-olcutler.json` `od_onayli`). TASLAK damgasının nedeni bu docx'i üreten render
kaydından okunur (`taslak_nedenleri`). Kanıt bağlantıları teslim moduna göre (config.yaml `rapor.teslim`,
vars. `dekanlik`): dekanlik'te bağlantısız kanıt bilgi düzeyindedir (rapor ve kanıtlar dekanlığa teslim
edilir; `bidr teslim`), baglanti'da uyarı; ikisinde de yayımı engellemez."""
from __future__ import annotations

import json
import sys
from pathlib import Path


def _sablon(ws: Path, arg: str | None, rapor: dict) -> Path | None:
    if arg:
        return Path(arg).expanduser()
    if rapor.get("sablon"):
        return Path(str(rapor["sablon"])).expanduser()
    man = ws / ".bidr-render.json"
    try:
        sab = json.loads(man.read_text(encoding="utf-8")).get("sablon") if man.exists() else None
    except (OSError, ValueError):
        sab = None
    return Path(sab) if sab else None


def _run(args) -> int:
    from bidr.write.sources import rapor_section

    from .rules import load_rules
    from .run import denetle, od_onay_bekleyenler, tablo, taslak_nedenleri, yaz

    from bidr.teslim.mod import teslim_modu

    ws = Path(args.workspace).expanduser().resolve()
    rapor = rapor_section(ws)
    try:
        mod = teslim_modu(ws)
    except ValueError as e:
        print(f"HATA {e}", file=sys.stderr)
        return 2
    docx_path = Path(args.docx).expanduser() if args.docx else ws / "report.docx"
    if not docx_path.exists():
        print(f"HATA rapor yok: {docx_path} (önce bidr render ya da --docx)", file=sys.stderr)
        return 2
    rules = load_rules(rapor.get("denetim") if isinstance(rapor.get("denetim"), dict) else None,
                       paragraf_sonrasi_nk=args.paragraf_sonrasi)
    kanit = Path(args.kanit).expanduser() if args.kanit else ws / "evidence"
    index = Path(args.index).expanduser() if args.index else ws / "evidence-index.csv"
    try:
        res = denetle(docx_path, rules=rules, sablon=_sablon(ws, args.sablon, rapor),
                      kanit_klasoru=kanit if (args.kanit or kanit.is_dir()) else None,
                      index_path=index, od_bekleyen=od_onay_bekleyenler(ws, docx_path)[0],
                      taslak_nedenleri=taslak_nedenleri(ws, docx_path), teslim_modu=mod)
    except Exception as e:  # bozuk docx vb.
        print(f"HATA denetlenemedi: {e}", file=sys.stderr)
        return 2
    out = yaz(res, Path(args.out).expanduser() if args.out else ws / "denetim.json")
    print(tablo(res, satir_siniri=args.satir))
    b = res.bilgi.get("baglanti") or {}
    if mod == "dekanlik" and b.get("baglantisiz"):
        print(f"\nbilgi: {b['baglantisiz']}/{b['kanit_satiri']} kanıt satırı bağlantısız — teslim modu dekanlik "
              "(kanıtlar dekanlığa dosya olarak teslim edilir: bidr teslim); yayımı engellemez")
    print(f"\ndenetim: {out}")
    return 1 if res.kritik else 0


def register(sub):
    p = sub.add_parser("denetle", help="üretilmiş raporu kılavuz biçim kurallarına göre denetler "
                                       "(denetim.json; kritik bulgu varsa çıkış 1)")
    p.add_argument("--workspace", "-w", required=True)
    p.add_argument("--docx", default=None, help="denetlenecek rapor (vars.: WS/report.docx)")
    p.add_argument("--sablon", default=None, help="boş FR-0833 şablonu (form alanı karşılaştırması)")
    p.add_argument("--kanit", default=None, help="kanıt klasörü (vars.: WS/evidence, varsa)")
    p.add_argument("--index", default=None, help="evidence-index.csv (vars.: WS/evidence-index.csv, varsa)")
    p.add_argument("--out", default=None, help="denetim.json yolu (vars.: WS/denetim.json)")
    p.add_argument("--paragraf-sonrasi", type=float, default=None,
                   help="paragraf sonrası aralık, nk (vars. 0,6: kılavuz değeri)")
    p.add_argument("--satir", type=int, default=12, help="tabloda her koddan gösterilecek en çok bulgu")
    p.set_defaults(func=_run)
