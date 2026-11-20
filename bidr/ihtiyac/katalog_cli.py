"""`bidr kurum-katalog cek|prepare|apply`: kurum belge kataloğu (yalnız adlar ve bağlantılar) ve
alt ölçüt eşlemesi. Çıktılar `--out` klasörüne (varsayılan çalışma alanı); çalışma alanı salt okunur.
`bidr ihtiyac` eşlemeyi (`kurum-katalog-esleme.json`) `--out`/çalışma alanından kendiliğinden okur."""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path


def _kurum(args) -> str:
    if args.kurum:
        return args.kurum
    if args.workspace:
        import yaml
        p = Path(args.workspace).expanduser() / "config.yaml"
        if p.exists():
            raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            k = (raw.get("bidr") or {}).get("kurum") or raw.get("kurum")
            if k:
                return str(k)
    raise ValueError("kurum bilinmiyor: --kurum ver ya da config.yaml'da `kurum` olan çalışma alanı (-w)")


def _out(args) -> Path:
    if args.out:
        return Path(args.out).expanduser().resolve()
    if args.workspace:
        return Path(args.workspace).expanduser().resolve()
    raise ValueError("--out ya da -w gerekli")


def _cek(args) -> int:
    from . import katalog as K
    kurum = args.kurum or (Path(args.profil).stem if args.profil else _kurum(args))
    raw, sayfalar = K.profil_sayfalari(kurum, Path(args.profil) if args.profil else None)
    if not sayfalar:
        print(f"HATA: kurum profilinde `katalog:` sayfası yok ({kurum})", file=sys.stderr)
        return 1
    kat = K.cek(sayfalar, kurum=kurum, log=print)
    p = K.yaz(kat, _out(args))
    n = Counter(o["tur"] for o in kat["ogeler"])
    print(f"katalog: {len(kat['ogeler'])} öğe (" + ", ".join(f"{K.TUR_AD.get(k, k)} {v}" for k, v in
                                                          n.most_common()) + f") → {p}")
    bad = [s for s in kat["sayfalar"] if s["durum"] != "ok" and s.get("etkin", True)]
    for s in bad:
        print(f"uyarı: {s['ad']} ({s['adres']}): {s['durum']}")
    return 1 if bad and not kat["ogeler"] else 0


def _prepare(args) -> int:
    from . import katalog as K
    from . import katalog_esle as E
    out = _out(args)
    kp = Path(args.katalog).expanduser() if args.katalog else out / K.FILE
    if not kp.exists():
        print(f"HATA: {kp} yok: önce `bidr kurum-katalog cek`", file=sys.stderr)
        return 2
    st = E.prepare(K.oku(kp), out, yeniden=args.yeniden)
    print(f"{st['oge']} öğe: {st['elenen']} ilgisiz alan (elendi), {st['paketlenen']} öğe modele "
          f"({st['paket']} paket, {st['yeni_paket']} yeni/değişen; bekleyen {st['bekleyen_paket']}); "
          f"korunan model eşlemesi {st['model_korunan']} → {st['dosya']}")
    if st["paketlenen"]:
        print(f"Ajan: {st['klasor']}/README.md")
    return 0


def _apply(args) -> int:
    from . import katalog_esle as E
    st = E.apply(_out(args), model=args.model)
    print(f"işlenen={st['islenen']} bekleyen={len(st['bekleyen'])} geçersiz={len(st['gecersiz'])} "
          f"ilgili={st['ilgili']} → {st['dosya']}")
    for k, errs in st["gecersiz"].items():
        print(f"  geçersiz {k}: {'; '.join(errs[:5])}")
    return 1 if st["gecersiz"] else 0


def _run(args) -> int:
    try:
        return {"cek": _cek, "prepare": _prepare, "apply": _apply}[args.eylem](args)
    except (FileNotFoundError, ValueError) as e:
        print(f"HATA: {e}", file=sys.stderr)
        return 2


def register(sub):
    p = sub.add_parser("kurum-katalog", help="kurum belge kataloğu: mevzuat/kalite sayfalarından belge adları ve "
                                             "bağlantıları (ek dosya indirilmez) ve alt ölçüt eşlemesi")
    act = p.add_subparsers(dest="eylem", required=True)
    for ad, yardim in (("cek", "kurum profilindeki `katalog:` sayfalarını indir → kurum-katalog.json"),
                       ("prepare", "kural eşlemesi + model iş paketleri (work/kurum-katalog/kk-NNN.json) → "
                                   "kurum-katalog-esleme.json"),
                       ("apply", "kk-NNN.out.json cevaplarını denetle, eşlemeye işle")):
        a = act.add_parser(ad, help=yardim)
        a.add_argument("--workspace", "-w", default=None, help="çalışma alanı (kurum adı config.yaml'dan)")
        a.add_argument("--out", default=None, help="çıktı klasörü (varsayılan çalışma alanı)")
        if ad == "cek":
            a.add_argument("--kurum", default=None, help="kurum profili adı (bidr/data/institutions/<ad>.yaml)")
            a.add_argument("--profil", default=None, help="kurum profili YAML yolu (--kurum yerine)")
        if ad == "prepare":
            a.add_argument("--katalog", default=None, help="kurum-katalog.json (varsayılan --out içinde)")
            a.add_argument("--yeniden", action="store_true", help="model eşlemelerini de yeniden paketle")
        if ad == "apply":
            a.add_argument("--model", default="ajan:belirtilmemis", help="cevabı yazan ajan/model (kayda geçer)")
        a.set_defaults(func=_run)
