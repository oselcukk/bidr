"""`bidr decide` ve `bidr compare-labels`."""
from __future__ import annotations


def _common(args):
    return dict(profile=args.profile or None, only_labeled=args.only_labeled, limit=args.limit,
                k=args.k, max_aday=args.max_aday)


def _stats(st: dict, stage: str | None = None) -> str:
    """Belge sayaçları. Kaba aşamada kaba seçimin sonucu, ince aşamada ince kararın
    sonucu gösterilir (kaba kayıtta ince sayaçları tanımsızdır, 0 değil)."""
    kk = st["kaba_karar"]
    s = (f"ok={st['ok']} (kaba={st['kaba']} ince={st['ince']}) atlandi={st['atlandi']} hata={st['hata']}"
         + (f" bekliyor={st['bekliyor']}" if st.get("bekliyor") else "")
         + (f" devralan={st['devralan']}" if st.get("devralan") else "")
         + (f" yeniden={st['yeniden']}" if st.get("yeniden") else ""))
    s += (f"; kaba karar: olcut_var={kk.get('olcut_var', 0)} olcut_yok={kk.get('olcut_yok', 0)} "
          f"kanit_degil={kk.get('kanit_degil', 0)}")
    if stage != "coarse":
        s += (f"; ince karar (ince aşamadaki {st['ince']} belge): olcut_var={st['olcut_var']} "
              f"olcut_yok={st['olcut_yok']} kanit_degil={st['kanit_degil']}; "
              f"eşleşme kabul={st['kabul_eslesme']} red={st['reddedilen_eslesme']}"
              + (f" od2_tavanı={st['od_tavan']}" if st.get("od_tavan") else "")
              + (f"; başka birim={st['baska_birim']}" if st.get("baska_birim") else "")
              + (f"; birim aitliği doğrulanmalı={st['birim_belirsiz']}" if st.get("birim_belirsiz") else ""))
    return s


def _only_ids(args, ws):
    """--only / --from-file → doc_id listesi (None: süzgeç yok)."""
    import re
    raw: list[str] = []
    if getattr(args, "only", None):
        raw += [x for x in re.split(r"[,\s]+", args.only) if x]
    if getattr(args, "from_file", None):
        from pathlib import Path
        for ln in Path(args.from_file).read_text(encoding="utf-8").splitlines():
            raw += [x for x in re.split(r"[,\s]+", ln.split("#", 1)[0]) if x]
    if not raw and not getattr(args, "only", None) and not getattr(args, "from_file", None):
        return None, []
    from .run import resolve_ids
    ids, errs = resolve_ids(ws, raw)
    if not ids and not errs:
        errs = ["boş belge listesi"]
    return ids, errs


def _decide(args) -> int:
    from bidr.pipeline.gate import check_gate

    stage = "karar_ince" if getattr(args, "stage", None) == "fine" else "karar_kaba"
    if (rc := check_gate(args.workspace, stage)) is not None:
        return rc
    from bidr.common import Workspace

    from . import run as R

    ws = Workspace(args.workspace)
    if not ws.text_dir.exists():
        print(f"text/ yok: {ws.text_dir}")
        return 2
    if args.action == "prepare":
        only, errs = _only_ids(args, ws)
        if errs:
            print("belge kimliği hatası: " + "; ".join(errs))
            return 2
        st = R.prepare(ws.root, args.stage, redo=args.redo, only=only, yes=args.yes, **_common(args))
        print(f"{st['paket']} paket ({st['yeni']} yeni/değişen), bekleyen {st['bekleyen']} → {st['klasor']}")
        print(f"atlandi={st['atlandi']} zaten_tamam={st['zaten_tamam']} kaba_yok={st['kaba_yok']} "
              f"aday_yok={st['aday_yok']}"
              + (f" seçmeli={st['secmeli']}" if only is not None else "")
              + (f"; mükerrer metin: {st['mukerrer']} belge temsilciyi bekliyor, {st['devralindi']} devraldı"
                 + (f", {st['ayrildi']} ayrıldı (kendisi paketlendi)" if st["ayrildi"] else "")
                 if st["mukerrer"] or st["devralindi"] else ""))
        if st.get("girdi_degisti"):
            print(f"belgeye özgü girdisi (aday listesi/ölçüt blokları/metin payı/belge bilgisi/birim) "
                  f"değişen {st['girdi_degisti']} belge yeniden paketlendi (onay gerekmez).")
        if st.get("kural_eski"):
            print(f"istem sürümü eski: {st['kural_eski']} belgede yalnız ortak kural metni değişti; kayıtlar "
                  f"geçerli. Toptan yeniden işleme isteğe bağlı ve pahalı: aynı komut --yes ile.")
        if st["onay_gerekli"]:
            from collections import Counter
            why = Counter(w for w in st["eski"].values() if w != "kural_degisti")
            print(f"ONAY GEREKLİ: yeniden işlenecek {sum(why.values())} belge "
                  f"({', '.join(f'{k}={v}' for k, v in sorted(why.items()))}) — işlenmiş kararları "
                  f"görevin eski sürümü ya da eski istemiyle. Yeniden işlemek pahalı: ~{st['eski_cagri']} "
                  f"model cevabı, ~{st['eski_token']} istem token'ı. Kullanıcı onaylarsa aynı komutu "
                  f"--yes ile çalıştır; onaylanmazsa eski kararlar kullanılmaya devam eder.")
        print(f"Ajan: {st['klasor']}/README.md")
        return 0
    if args.action == "apply":
        from bidr.pipeline.paralel import apply_oncesi
        apply_oncesi(ws.root, f"work/{args.stage}")   # parça dışı yazılmış/ezilmiş cevap reddedilir
        st = R.apply(ws.root, args.stage, model=args.model)
        if st.get("paket_degil"):
            print(f"paket olmayan dosya atlandı: {', '.join(st['paket_degil'])}")
        print(f"işlenen={st['islenen']} değişmeyen={st['degismedi']} bekleyen={len(st['bekleyen'])} "
              f"geçersiz={len(st['gecersiz'])} alıntısı tutmayan belge={len(st['alinti_tutmayan'])} "
              f"eski sürüm paketi={len(st['eski_surum'])}"
              + (f" devralan={st['devralindi']}" if st["devralindi"] else ""))
        for did, errs in st["gecersiz"].items():
            print(f"  geçersiz {did}: {'; '.join(errs)}")
        for did, ka in st.get("kanit_adi_red", {}).items():
            print(f"  kanıt adı reddedildi {did} ({', '.join(ka['red'])}): {ka['oneri']} → ad kuraldan; "
                  f"`bidr name prepare --only {did}`")
        if st["baska_birim"]:
            print(f"  başka birime ait (kanıt sayılmadı, gerekçe decisions.jsonl `ince.gerekce`): "
                  + ", ".join(st["baska_birim"]))
        if st["birim_belirsiz"]:
            print(f"  birim aitliği doğrulanmalı (kabul edildi; review.xlsx/gaps.md'de işaretli): "
                  + ", ".join(st["birim_belirsiz"]))
        if st["ayrildi"]:
            print(f"  {len(st['ayrildi'])} mükerrer belge temsilcinin kararını devralamadı (alıntı kendi "
                  f"metninde tutmuyor): yeniden prepare ile kendisi paketlenir")
        print(_stats(st["durum"], args.stage))
        return 1 if st["gecersiz"] else 0
    out, st = R.run(ws.root, log=(lambda m: None) if args.quiet else print, **_common(args))
    print(f"{st['belge']} belge → {out}")
    print(_stats(st))
    return 0


def _compare(args) -> int:
    from bidr.pipeline.gate import check_gate

    if (rc := check_gate(args.workspace, "hakem")) is not None:
        return rc
    from bidr.common import Workspace

    from .compare import FILES, consensus, run

    ws = Workspace(args.workspace)
    if args.apply:
        out, st = consensus(ws.root)
        print(f"{st['belge']} belge → {out}; tamam={st['tamam']} açık soru={st['acik_soru']}; "
              f"eklenen={st['eklenen']} kaldırılan={st['kaldirilan']} od değişen={st['od_degisen']}")
        if st["gecersiz_cevap"]:
            print("geçersiz cevap: " + ", ".join(st["gecersiz_cevap"]))
        return 0
    if not (ws.root / args.decisions).exists():
        print(f"{args.decisions} yok; önce `bidr decide`")
        return 2
    _, st = run(ws.root, decisions=args.decisions)
    print(f"{st['belge']} etiketli belge karşılaştırıldı ({st['atlanan']} atlandı); "
          f"{st['soru']} hakem sorusu {st['tur']} → {FILES['compare']}, {FILES['review_md']}, "
          f"{FILES['review_jsonl']}" + (f"; md'den toplanan cevap: {st['toplanan_cevap']}"
                                        if st["toplanan_cevap"] else ""))
    return 0


def _sel(p, stage: bool):
    p.add_argument("--workspace", "-w", required=True)
    if stage:
        p.add_argument("--stage", choices=("coarse", "fine"), required=True)
    p.add_argument("--profile", default="akademik_bolum",
                   help="birim profili (vars. akademik_bolum; boş dize = 46 ölçütün hepsi)")
    p.add_argument("--only-labeled", action="store_true", help="yalnız geçmiş etiketi olan belgeler")
    p.add_argument("--limit", type=int, help="en çok N belge")
    p.add_argument("--k", type=int, default=5, help="candidates.jsonl'den alınan ilk k aday (vars. 5)")
    p.add_argument("--max-aday", type=int, default=6, help="ince karara giden en çok aday (vars. 6)")


def register(sub):
    p = sub.add_parser("decide", help="model kararı (kaba seçim + rubrikli ince karar, alıntı denetimli) → decisions.jsonl")
    act = p.add_subparsers(dest="action", required=True)
    a = act.add_parser("prepare", help="ajan modu: iş paketleri work/<aşama>/<doc_id>.json")
    _sel(a, True)
    a.add_argument("--redo", action="store_true",
                   help="işlenmiş belgeleri de yeniden paketle (istem aynıysa var olan cevap korunur)")
    a.add_argument("--only", metavar="DOC_ID[,…]",
                   help="yalnız bu belgeleri (işlenmiş olsalar da) yeniden paketle; ötekiler korunur. "
                        "Tam doc_id ya da en az 6 haneli tek anlamlı önek")
    a.add_argument("--from-file", metavar="DOSYA",
                   help="--only gibi; kimlikler dosyadan (virgül/boşluk/satır ayrılmış, # sonrası yorum)")
    a.add_argument("--yes", action="store_true",
                   help="görev sürümü ya da istem değişmiş işlenmiş belgeleri yeniden işlemeyi onayla "
                        "(önce --yes olmadan çalıştırıp özeti kullanıcıya göster)")
    a.set_defaults(func=_decide)
    a = act.add_parser("apply", help="ajan modu: <doc_id>.out.json cevaplarını doğrula ve işle")
    a.add_argument("--workspace", "-w", required=True)
    a.add_argument("--stage", choices=("coarse", "fine"), required=True)
    a.add_argument("--model", default="ajan:belirtilmemis",
                   help="cevapları üreten ajan/model (kayda geçer; ör. claude-code:opus)")
    a.set_defaults(func=_decide)
    a = act.add_parser("run", help="sağlayıcı modu: bidr.llm.run_task ile kaba + ince")
    _sel(a, False)
    a.add_argument("--quiet", "-q", action="store_true")
    a.set_defaults(func=_decide)

    q = sub.add_parser("compare-labels", help="model kararı ↔ geçmiş etiket; hakem kuyruğu; --apply ile uzlaşı")
    q.add_argument("--workspace", "-w", required=True)
    q.add_argument("--decisions", default="decisions.jsonl")
    q.add_argument("--apply", action="store_true",
                   help="hakem cevaplarından (label-review.md / label-answers.jsonl) consensus-labels.jsonl yaz")
    q.set_defaults(func=_compare)
