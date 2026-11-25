"""`bidr transcribe prepare|apply`.

Çıkış kodları: 0 tamam (apply'da cevapsız ya da eski sürüm paket hata sayılmaz; aşamanın bitip
bitmediğini `bidr next` söyler; elle bakılmalı işaretlenen belge de hata sayılmaz: karar verilmiştir,
ELLE-BAKILMALI.md) · 1 apply'da en az bir geçersiz ya da şüpheli cevap uygulanmadı, kenara alındı ve
yeniden okunacak (work/transcribe/GECERSIZ.md) · 2 eksik/yanlış argüman · 3 önkoşul aşaması bitmemiş."""
from __future__ import annotations


def _ids(s: str | None) -> list[str] | None:
    return [x.strip() for x in s.split(",") if x.strip()] if s else None


def _gate(ws, sid: str = "transcribe") -> int | None:
    """Aşama pipeline.yaml'a kayıtlıysa kapısını uygula; değilse (henüz kayıtsız) geç.
    `prepare --belirsiz` aşama `belirsiz_okuma`'nın kapısından geçer (önkoşul: ince karar)."""
    from bidr.pipeline.state import load_spec
    if not any(s.get("id") == sid for s in load_spec().get("asamalar", [])):
        return None
    from bidr.pipeline.gate import check_gate
    return check_gate(ws, sid)


def _cmd(args) -> int:
    belirsiz = args.action == "prepare" and args.belirsiz
    if (rc := _gate(args.workspace, "belirsiz_okuma" if belirsiz else "transcribe")) is not None:
        return rc
    from . import run as R

    if args.action == "prepare":
        only = _ids(args.only)
        if sum(map(bool, (only, args.all_low_quality, belirsiz))) != 1:
            print("seçim: --only DOC_ID,…, --all-low-quality ya da --belirsiz (yalnız biri)")
            return 2
        st = R.prepare(args.workspace, only=only, all_low_quality=args.all_low_quality,
                       source=args.source, dpi=args.dpi, max_pages=args.max_pages,
                       limit=args.limit, redo=args.redo, belirsiz=belirsiz)
        if belirsiz:
            s = st["secim"]
            print(f"belirsiz turu: ince kararda birimi belirsiz {s['belirsiz']} belge → aday {s['aday']}"
                  f" (elenen: OCR'lı değil {s['ocr_degil']}, biçim {s['bicim']}, >{args.max_pages} sayfa "
                  f"{s['cok_sayfa']}, zaten görsel okundu {s['okundu']}, insan birim kararı {s['insan_karari']}, "
                  f"önceden paketlenemedi {s['paketlenemedi']})")
        print(f"{st['paket']} paket ({st['yeni']} yeni/değişen), zaten_tamam={st['zaten_tamam']}, "
              f"bekleyen {st['bekleyen']} → {st['klasor']}"
              + (f" (yalnız talimat metni değişen {st['cevap_korundu']} paketin cevabı korundu)"
                 if st.get("cevap_korundu") else ""))
        for did, why in st["atlandi"].items():
            print(f"  atlandı {did}: {why}")
        print(f"Ajan: {st['klasor']}/README.md")
        return 0
    from bidr.pipeline.paralel import apply_oncesi
    apply_oncesi(args.workspace, "work/transcribe")   # parça dışı yazılmış/ezilmiş cevap reddedilir
    st = R.apply(args.workspace, model=args.model, accept_suspicious=args.kabul_supheli,
                 only=_ids(args.only))
    print(f"işlenen={st['islenen']} değişmedi={st['degismedi']} bekleyen={len(st['bekleyen'])} "
          f"geçersiz={len(st['gecersiz'])} şüpheli={len(st['supheli'])} eski sürüm={len(st['eski_surum'])}"
          + (f" metni aynı (karar korunur)={len(st['metin_ayni'])}" if st["metin_ayni"] else "")
          + (f" elle bakılmalı={len(st['elle_bakilmali'])}" if st["elle_bakilmali"] else "")
          + (f" metinsiz (hepsi [okunamadı] → bos)={len(st['normallestirilen'])}" if st["normallestirilen"] else ""))
    for did, c in sorted(st["tutarlilik"].items()):
        print(f"  {did}: {c['durum']} örtüşme={c['oran']} [okunamadı]={c['okunamadi']}")
    for did, errs in st["gecersiz"].items():
        print(f"  geçersiz {did}: {'; '.join(errs)}")
    for did, r in sorted(st["elle_bakilmali"].items()):
        print(f"  elle bakılmalı {did}: {r.get('neden')} ({r.get('deneme')} deneme; metni değişmedi) "
              "→ work/transcribe/ELLE-BAKILMALI.md")
    if st["degisen"]:
        g = st["gecersiz_kilinan"]
        print(f"metni değişen {len(st['degisen'])} belge: documents -{g['documents']}, candidates "
              f"-{g['candidates']}, decisions metin_degisti={g['decisions']}, karar paketi .eski={g['paket']}")
        print("Sonra: bidr identify, bidr candidates, bidr decide prepare/apply (bidr next sırayı verir)")
    return _exit(st)


def _exit(st: dict) -> int:
    """apply çıkış kodu: 0 = işlenen her cevap geçerli (cevapsız/eski sürüm paket hata sayılmaz;
    tamamlanmayı `bidr next` söyler); 1 = en az bir geçersiz ya da şüpheli cevap var
    (work/transcribe/GECERSIZ.md; şüpheli için görüntüye bakıp doğruysa `--kabul-supheli`)."""
    g, s = len(st["gecersiz"]), len(st["supheli"])
    if not (g or s):
        return 0
    print(f"çıkış 1: {g} geçersiz, {s} şüpheli cevap uygulanmadı → work/transcribe/GECERSIZ.md"
          + (" (cevap kenara alındı, paket yeniden okunacak)" if st.get("yeniden") else "")
          + (" (şüpheli: görüntüye bak; okuma doğruysa apply --kabul-supheli)" if s else ""))
    return 1


def register(sub):
    p = sub.add_parser("transcribe", help="ajan modu: düşük kaliteli belgeleri sayfa görüntüsünden yazıya geçir")
    act = p.add_subparsers(dest="action", required=True)
    a = act.add_parser("prepare", help="sayfa görüntüleri + iş paketi: work/transcribe/<doc_id>/")
    a.add_argument("--workspace", "-w", required=True)
    a.add_argument("--only", help="virgülle ayrılmış doc_id listesi")
    a.add_argument("--all-low-quality", action="store_true", help="inventory.csv'de low_quality=1 olanların hepsi")
    a.add_argument("--belirsiz", action="store_true",
                   help="aşama belirsiz_okuma: ince kararda birimi belirsiz kalan, metni OCR'lı (ya da düşük "
                        "kaliteli) ve görsel okumadan hiç geçmemiş belgeler (belge başına bir tur)")
    a.add_argument("--source", help="kaynak klasör (vars. config.yaml bidr.kaynak); salt okunur")
    a.add_argument("--dpi", type=int, default=200, help="PDF sayfa görüntüsü çözünürlüğü (vars. 200)")
    a.add_argument("--max-pages", type=int, default=40, help="bundan uzun belge atlanır (vars. 40)")
    a.add_argument("--limit", type=int)
    a.add_argument("--redo", action="store_true", help="yazıya geçirilmiş belgeleri de yeniden paketle")
    a.set_defaults(func=_cmd)
    a = act.add_parser("apply", help="<doc_id>.out.json cevaplarını doğrula ve belge metni yap")
    a.add_argument("--workspace", "-w", required=True)
    a.add_argument("--model", default="ajan:belirtilmemis", help="cevabı yazan ajan/model (kayda geçer)")
    a.add_argument("--only", help="yalnız bu doc_id'ler")
    a.add_argument("--kabul-supheli", action="store_true",
                   help="OCR'la örtüşmeyen (şüpheli) cevapları da uygula (kayıtta işaretli kalır)")
    a.set_defaults(func=_cmd)
