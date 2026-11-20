"""`bidr render -w WS [--sablon FR-0833.docx] [--out report.docx] [--birim "…"] [--yil 2026]`.

Şablon verilmezse config.yaml `rapor.sablon`. Kanıt bağlantıları `evidence-index.csv`'den
(`baglanti` sütunu), teslim moduna göre (config.yaml `rapor.teslim`, vars. `dekanlik`: kök klasör
bağlantısı girmez, web sayfası kanıtının özgün adresi görünür yazılır; `baglanti`: eski davranış);
bağlantısız kanıtlar gaps.md "bağlantı yok" bölümüne yazılır (dekanlik'te bilgi notu). Kapak
hazırlayanları config.yaml `rapor.hazirlayanlar`; ölçüt kapsamı profil + `rapor.kapsam`
(bidr/render/kapsam.py; kapsam kararı soruları gaps.md); alan maddeleri `yonler/<alan>.json`."""
from __future__ import annotations

import json
import sys
from pathlib import Path


def _run(args) -> int:
    from bidr.pipeline.gate import check_gate
    from bidr.write.sources import rapor_section

    from .run import (YONLER_DIR, Options, render, update_link_gaps, update_scope_gaps, workspace_inputs,
                      workspace_sha, workspace_teslim, write_manifest)

    ws = Path(args.workspace).expanduser().resolve()
    if (rc := check_gate(ws, "render")) is not None:
        return rc
    sablon = args.sablon or rapor_section(ws).get("sablon")
    if not sablon:
        print("HATA şablon yok: answers.yaml'a `sablon: <boş FR-0833 .docx tam yolu>` yazıp `bidr init "
              "--answers <answers.yaml>` yeniden çalıştırın (config.yaml rapor.sablon) ya da --sablon verin",
              file=sys.stderr)
        return 2
    sablon = Path(str(sablon)).expanduser()
    birim = args.birim
    if birim is None:
        from bidr.init.config import load_section
        birim = (load_section(ws) or {}).get("birim")
    index = Path(args.index).expanduser() if args.index else ws / "evidence-index.csv"
    out = Path(args.out).expanduser() if args.out else ws / "report.docx"
    texts = Path(args.texts).expanduser() if args.texts else ws / "texts"
    audit = Path(args.audit).expanduser() if args.audit else ws / "audit-olcutler.json"
    opts = Options(puan_isareti=args.puan_isareti, kanit_bicimi=args.kanit_bicimi,
                   eksik_notu=not args.eksik_notu_yok)
    if args.bos_ifade:
        opts.bos_ifade = args.bos_ifade
    if args.bos_kanit:
        opts.bos_kanit = args.bos_kanit
    if args.kapsam_disi is not None:
        opts.kapsam_disi = args.kapsam_disi
    kapsam, people, pre = workspace_inputs(ws)
    try:
        teslim = workspace_teslim(ws)
        res = render(sablon, out, texts_dir=texts, audit_path=audit,
                     birim=birim, yil=args.yil, opts=opts, index_path=index,
                     kapsam=kapsam, yonler_dir=ws / YONLER_DIR, hazirlayanlar=people, teslim=teslim,
                     evidence_dir=ws / "evidence")
    except (FileNotFoundError, ValueError) as e:
        print(f"HATA {e}", file=sys.stderr)
        return 2
    write_manifest(ws, res, workspace_sha(ws, sablon, texts, audit, index), sablon, texts_dir=texts,
                   audit_path=audit, index_path=index)
    update_link_gaps(ws, index, teslim)
    update_scope_gaps(ws, res.karar_gerekli)
    for u in pre + res.uyarilar:
        print(f"uyarı: {u}")
    if res.kapsam_disi:
        print(f"birimin doldurma sorumluluğunda olmayan {len(res.kapsam_disi)} ölçüt: kapsam ifadesiyle yazıldı")
    if res.karar_gerekli:
        print(f"uyarı: {len(res.karar_gerekli)} ölçütte kapsam kararı gerekli ({', '.join(res.karar_gerekli)}): "
              "soru gaps.md'de; KULLANICI karar verir (config.yaml rapor.kapsam)")
    if res.atifsiz_listelenen:
        n = sum(map(len, res.atifsiz_listelenen.values()))
        print(f"not: {n} kanıt metinde atıf almıyor ama kanıt klasöründe; numara sırası bozulmasın diye "
              f"listede ({', '.join(sorted(res.atifsiz_listelenen))}). Metne atıf eklemek için write "
              "yeniden; kanıtı çıkarmak için review.xlsx'te ret → audit apply → file")
    if res.baglantisiz and teslim == "baglanti":
        print(f"uyarı: {len(res.baglantisiz)} kanıtın bağlantısı yok (gaps.md 'Bağlantısı olmayan kanıtlar')")
    elif res.baglantisiz:
        print(f"bilgi: {len(res.baglantisiz)} kanıtın adı bağlantısız — teslim modu {teslim}: bağlantı gerekmez, "
              "kanıtlar dosya olarak teslim edilir (bidr teslim)")
    print(json.dumps(res.ozet(), ensure_ascii=False, indent=1))
    if res.taslak:
        print("Belge TASLAK damgalı:")
        for n in res.taslak_nedenleri:
            print(f"  - {n}")
    print(f"report: {res.out}")
    return 0


def register(sub):
    p = sub.add_parser("render", help="FR-0833 şablonunun Açıklamalar/Kanıtlar hücrelerini "
                                      "texts/<ölçüt>.json'dan doldurur (report.docx; model yok)")
    p.add_argument("--workspace", "-w", required=True)
    p.add_argument("--sablon", default=None,
                   help="boş FR-0833 şablonu (.docx; salt okunur; vars. config.yaml rapor.sablon)")
    p.add_argument("--index", default=None, help="evidence-index.csv (vars.: WS/evidence-index.csv)")
    p.add_argument("--out", default=None, help="çıktı (vars.: WS/report.docx)")
    p.add_argument("--birim", default=None, help="kapaktaki birim adı (vars.: config.yaml birim)")
    p.add_argument("--yil", default=None, help="kapaktaki yıl (verilmezse şablondaki kalır)")
    p.add_argument("--texts", default=None, help="metin klasörü (vars.: WS/texts)")
    p.add_argument("--audit", default=None, help="audit-olcutler.json (vars.: WS/audit-olcutler.json)")
    p.add_argument("--kapsam-disi", default=None,
                   help="birimin doldurmadığı (kapsam baska_birim) ölçütün Açıklamalar ifadesi; '' = hücre boş "
                        "(vars.: 'Bu ölçüt birimin doldurma sorumluluğunda değildir.')")
    p.add_argument("--puan-isareti", choices=["kalin", "golge", "yok"], default="kalin",
                   help="öz değerlendirme düzeyinin rubrikte işaretlenmesi (vars.: kalin, "
                        "Kimya 2025 raporu usulü; Matematik/Fizik/MBG işaretlememiş: yok)")
    p.add_argument("--kanit-bicimi", choices=["mat", "kilavuz"], default="mat",
                   help="Kanıtlar listesi: mat '1_OD3: ad' (vars.) | kilavuz '[1-OD3]. ad'")
    p.add_argument("--bos-ifade", default=None, help="metni olmayan ölçüt için Açıklamalar ifadesi")
    p.add_argument("--bos-kanit", default=None, help="metni olmayan ölçüt için Kanıtlar ifadesi")
    p.add_argument("--eksik-notu-yok", action="store_true",
                   help="metni olmayan ölçüte audit'in eksik kanıt notunu yazma")
    p.set_defaults(func=_run)
