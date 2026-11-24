"""gaps.md: ölçüt ve yuva düzeyinde eksik kanıt raporu."""
from __future__ import annotations

from .rules import KISA, LINKS

GRUP = {1: "kanıt var ama uygulama/plan halkası eksik (OD ≤ 2)", 2: "hiç kanıt yok (OD1)",
        3: "OD3: izleme ve/veya iyileştirme kanıtı eksik", 4: "OD4: özgün uygulama kanıtı eksik",
        9: "OD5"}


def _eksik_lines(c: dict) -> list[str]:
    out = []
    for e in c["eksik"]:
        line = f"- **OD{c['sonraki_od']} için {e['halka']} ({KISA[e['halka']]})**: {e['gereken']}."
        if e["yuvasiz"]:
            line += " Şablonda bu halkaya ait yuva yok; ölçüt açıklamasına uygun belge gerekir."
        out.append(line)
        for y in e["yuvalar"][:4]:
            out.append(f"  - `{y['yuva']}` {y['metin']}")
    return out


def top_gaps(a, n: int = 10) -> list[dict]:
    from .run import priority_key
    return sorted((c for c in a.criteria if c["oncelik_grubu"] != 9), key=priority_key)[:n]


def gap_line(c: dict) -> str:
    halkalar = ", ".join(e["halka"] for e in c["eksik"]) or "—"
    extra = " (yalnız kurum/fakülte geneli belge)" if c["kurum_geneli_yalniz"] else ""
    return (f"{c['olcut']} {c['baslik']}: OD{c['od']}{extra}; OD{c['sonraki_od']} için eksik: {halkalar}; "
            f"boş yuva {c['yuva_toplam'] - c['yuva_dolu']}/{c['yuva_toplam']}")


def _donem_sections(a) -> list[str]:
    """Dönem kuralı bölümleri: döngü önerileri, geçmiş kanıtlar, doğrulanacak tarihler."""
    L: list[str] = []
    yil = f" (rapor yılı {a.donem})" if a.donem else ""
    dongu = [c for c in a.criteria if c.get("dongu")]
    oneri = [c for c in a.criteria if c.get("dongu_onerisi")]
    if dongu or oneri:
        L += ["", "## Gözden geçirme döngüleri", "",
              "Takvim yılı temelinde olmayan döngülerde (müfredat gözden geçirme, akreditasyon) döngünün "
              "son halkası olan önceki yıl olayı, bölümün döngüyü tanımlayan kararı varsa o ölçütte sayılır.", ""]
        for c in dongu:
            d = c["dongu"]
            L.append(f"- {c['olcut']} {c['baslik']}: döngü tanımlı (son {d['yil']} yıl) — `{d['belge']}`: "
                     f"\"{d['alinti'][:160]}\"" + (f"; sayılan önceki yıl halkası {len(d['acilan'])}" if d["acilan"] else ""))
        for c in oneri:
            L.append(f"- **{c['olcut']} {c['baslik']}: öneri.** {c['dongu_onerisi']}")
    gk = [(c, g) for c in a.criteria for g in c.get("gecmis_kanit") or []]
    if gk:
        L += ["", f"## Geçmiş kanıtlar (süreklilik){yil}", "",
              "Önceki yıllarda gerçekleşmiş olaylar: bu yılın hiçbir halkası sayılmadı (OD'ye katılmaz; yayımlanan "
              "listede ölçüt başına sınırlı). "
              "Sürecin yıllar içinde sistematik işlediğinin (OD5) ve \"bir önceki yıla göre ne değişti\" "
              "sorusunun kanıtıdır; açıklama metninde karşılaştırma için kullanın.", ""]
        for c, g in gk:
            L.append(f"- {c['olcut']} `{g['yuva']}` {KISA.get(g['asama'], '?')} {g['yil'] or '?'}: `{g['belge']}`")
    from .donem import DONEM_DISI, ETIKET
    ds = [(c, g) for c in a.criteria for g in c.get("donem_sonrasi") or []]
    if ds:
        L += ["", f"## Dönem sonrası ve yürürlükte olmayan sürümler (kanıt sayılmadı){yil}", "",
              "Rapor yılından sonra tarihli olay belgeleri, rapor yılından sonra yürürlüğe giren düzenlemeler ve "
              "aynı düzenlemenin rapor yılında yürürlükte olmayan sürümleri bu dönemin kanıtı değildir: OD'ye "
              "sayılmadı, yayımlanan kanıt listesine girmez. Tarih yanlışsa tabloda `duzelt` + aşama ile sayın.", ""]
        for c, g in ds:
            L.append(f"- {c['olcut']} `{g['yuva']}` {KISA.get(g['asama'], '?')} {g['yil'] or '?'}: `{g['belge']}` "
                     f"({ETIKET.get(g['isaret'], g['isaret'])})")
    rv = sorted({r["belge"] for r in a.rows if "revizyon_donem_sonrasi" in r["flags"] and r["sayilir"]})
    if rv:
        L += ["", "## Revizyon tarihi dönem sonrası olan düzenlemeler", "",
              "Belgenin tarihi rapor yılından sonraki bir revizyon/değişiklik tarihi; önceki sürümü dönemde "
              "yürürlükte olabilir. Sayıldı, ama dönemdeki sürüm aranmalı (kanıt olarak o sürüm konmalı).", ""]
        L += [f"- `{b}`" for b in rv]
    sv = sorted({r["belge"] for r in a.rows if "surum_dogrulanmali" in r["flags"] and not _hum(r)})
    if sv:
        L += ["", "## Sürümü doğrulanacak düzenlemeler", "",
              "Aynı düzenlemenin birden çok sürümü var ve rapor yılında hangisinin yürürlükte olduğu tarihlerden "
              "belirlenemedi (tarihsiz sürüm). Yürürlükteki sürümü `kabul`, ötekileri `ret` edin.", ""]
        L += [f"- `{b}`" for b in sv]
    td = [r for r in a.rows if "tarih_dogrulanmali" in r["flags"] and not _hum(r)]
    if td:
        L += ["", "## Tarihi doğrulanacak olay belgeleri", "",
              "Belgede rapor yılını gösteren güvenilir tarih bulunamadı (tarih yok, yalnız dosya adında ya da birden "
              "çok tarihten olayın tarihi ayrılamadı); olay belgesi olduğu için hiçbir aşaması sayılmadı "
              "(satır tabloda gri). Tarih rapor yılındaysa tabloda `duzelt` + aşama ile sayın.", ""]
        by: dict[str, list] = {}
        nt: dict[str, str] = {}
        for r in td:
            by.setdefault(r["belge"], []).append(f"{r['yuva']} {KISA.get(r['etkin_asama'], '?')}")
            if r.get("tarih_notu"):
                nt[r["belge"]] = r["tarih_notu"]
        for b, ys in by.items():
            L.append(f"- `{b}`: " + ", ".join(ys) + (f" — {nt[b]}" if b in nt else ""))
    gd = sorted({r["belge"] for r in a.rows if "guncellik_dogrulanmali" in r["flags"] and r["sayilir"]})
    if gd:
        L += ["", "## Güncelliği doğrulanacak belgeler", "",
              "Yapı belgesi (ya da usul tanımlayan eski karar) sayıldı, ama tarihi rapor yılında değil ya da yok: "
              "rapor yılında yürürlükte olduğu doğrulanmalı. Yürürlükten kalkmışsa satırı `ret` edin.", ""]
        L += [f"- `{b}`" for b in gd]
    return L


# Kod tarafı savunmaların işaretleri (bidr/audit/savunma.py) → gaps.md açıklaması
SAVUNMA = {
    "haric_tur": "öz-referans tür (BİDR'nin kendisi ya da taslağı): kanıt değil, sayılmadı",
    "bilgisiz_ekran": "bilgi içermeyen ekran/bağlantı sayfası: kanıt değil, sayılmadı",
    "yururlukten_kalkmis": "başka bir belgeyle yürürlükten kaldırılmış düzenleme: sayılmadı",
    "madde_baska_birim": "alıntı başka birimi konu alan maddeden (madde ilkesi): sayılmadı",
    "bos_form": "boş form/şablon: uygulama değil → planla",
    "gerceklesme_kaniti_yok": "duyuru/gelecek zamanlı ifade ya da gerçekleşmesi kanıtlanmamış faaliyet → planla",
    "faaliyet_asamasi_uyusmuyor": "faaliyet kaydındaki aşama daha düşük → o aşama",
    "etkinlik_gerceklesti": "gerçekleşme belgesi aynı ölçütte kabul edilmiş etkinliğin duyurusu/afişi (etkinlik dosyası) → uygula",
    "katilim_izleme_degil": "katılım/yapılma kaydı izleme değil → uygula",
    "niyet_onlem_degil": "öneri/niyet iyileştirme değil → kontrol_et",
    "bilgilendirme_onlem_degil": "kurula bilgi verilmesi iyileştirme değil → uygula",
    "surum_notu_onlem_degil": "sürüm notu (revize) iyileştirme değil → uygula",
    "onlem_izlemeye_dayanmiyor": "iyileştirme bir izleme sonucuna dayanmıyor → uygula",
    "ozgun_kanitsiz": "özgünlük kanıtı yetersiz (bağımsız kanıt ve birden çok dönem gerekir): sayılmadı",
    "fotograf_destekleyici": "fotoğraf tek başına uygulama sayılmaz (destekleyici): sayılmadı",
    "fotograf_mekan": "mekân/altyapı/ekipman fotoğrafı süreç uygulaması değil → planla",
    "madde_baska_fakulte": "alıntı fakülteye göre maddeli düzenlemede başka fakültenin maddesinden: sayılmadı",
    "birim_iliskisi_kod": "kod birim ilişkisini değiştirdi: metinde birimin sinyali yok (belirsiz ya da kurum/fakülte "
                          "geneli) ya da model belirsiz dedi ama metinde birimin sinyali var (kendi; doğrulanmalı)",
}


def _savunma_sections(a) -> list[str]:
    """Kod tarafı savunmalar (modelin bilinen yanlışları) ve gerçekleşmesi kanıtlanmamış faaliyetler."""
    L: list[str] = []
    fs = getattr(a, "faaliyetler", None) or []
    if fs:
        L += ["", "## Gerçekleşmesi kanıtlanmamış faaliyetler", "",
              "Faaliyet kaydında (faaliyetler.json) yalnız duyuru/plan belgesi var: gerçekleştiğine dair tutanak, "
              "katılım listesi ya da rapor yok. Bu belgelerden gelen uygulama (ve üstü) eşleşmeleri planla'ya "
              "indirildi; metinde \"düzenlenmiştir/gerçekleştirilmiştir\" yazılmaz.", ""]
        for k in fs:
            L.append(f"- {k.get('id')} {k.get('ad')} ({k.get('tarih') or 'tarih yok'}): "
                     + ", ".join(k.get("eksik") or []) or "-")
    by: dict[str, list[str]] = {}
    for r in a.rows:
        for fl in r["flags"]:
            if fl == "madde_baska_birim" and "madde_baska_fakulte" in r["flags"]:
                continue                          # aynı satır: fakülte nedeniyle gösterilir
            if fl in SAVUNMA and not _hum(r):
                by.setdefault(fl, []).append(f"{r['olcut']} `{r['belge']}`")
    if by:
        L += ["", "## Kodun düşürdüğü ya da saymadığı eşleşmeler", "",
              "Belge türü, alıntıdaki ifade, belge metni ve faaliyet kaydıyla yapılan belirleyici denetimler "
              "(docs/AUDIT.md \"Kod tarafı savunmalar\"). Yanlışsa satırı `kabul` (modelin aşaması) ya da `duzelt` "
              "edin: insan kararı bu denetimleri aşar.", ""]
        for fl, xs in by.items():
            xs = list(dict.fromkeys(xs))
            L.append(f"- **{SAVUNMA[fl]}** ({len(xs)}): " + "; ".join(xs[:8]) + (" …" if len(xs) > 8 else ""))
    return L


def _hum(r: dict) -> bool:
    return r["karar"] in ("ret", "duzelt")


def _birim_sections(a) -> list[str]:
    """Birim aitliği: doğrulanacak (belirsiz) ve başka birime ait sayılan belgeler."""
    L: list[str] = []
    b = getattr(a, "birim", None) or {}
    if b.get("belirsiz"):
        L += ["", "## Birim aitliği doğrulanmalı", "",
              "İnce karar belgenin bu birime ait olup olmadığını metinden anlayamadı (`birim_iliskisi: belirsiz`). "
              "İnsan onaylamadıkça eşleşmeleri OD'ye sayılmaz ve yayımlanan kanıt listesine girmez (inceleme "
              "yapılmadan devam edilse de). Birimin belgesiyse review.xlsx'te satırlarını `kabul` edin ya da birim "
              "sayfasında ilişkiyi seçin; değilse `ret`.", ""]
        for x in b["belirsiz"]:
            st = ("onay bekliyor: sayılmadı" if x.get("bekleyen")
                  else "incelemede onaylandı" if x.get("onaylanan") else "")
            L.append(f"- `{x['belge']}` ({x['eslesme']} eşleşme{'; ' + st if st else ''})"
                     + (f": {x['gerekce']}" if x["gerekce"] else ""))
    if b.get("baska_birim"):
        from .sheet import SHEET_UNIT
        L += ["", "## Başka birime ait sayılan belgeler (kanıt sayılmadı)", "",
              "İnce karar bu belgeleri başka bir bölüm/birimin belgesi saydı; eşleşmeleri reddedildi. Yanlışsa "
              f"review.xlsx \"{SHEET_UNIT}\" sayfasında `insan_birim_iliskisi` sütununu doldurup "
              "`bidr audit apply` çalıştırın: reddedilen eşleşmeler geri gelir; eşleşme kaydı yoksa belge "
              "`bidr decide prepare -w <çalışma alanı> --stage fine --only <doc_id>` ile yeniden karara gider "
              "(ilişki sabit).", ""]
        for x in b["baska_birim"]:
            L.append(f"- `{x['belge']}` (`{x['doc_id']}`)" + (" (insan onayladı)" if x.get("insan") else "")
                     + (f": {x['gerekce']}" if x["gerekce"] else ""))
    ins = [x for x in getattr(a, "birim_sayfa", None) or []
           if x["insan_birim_iliskisi"] and x["insan_birim_iliskisi"] not in ("baska_birim", "model")]
    if ins:
        L += ["", "## Birim ilişkisi komisyonca değiştirilen belgeler", "",
              "İnsan kararı modelinkinin önüne geçti; belgeler yukarıdaki listeden çıktı.", ""]
        for x in ins:
            L.append(f"- `{x['belge']}` (`{x['doc_id']}`): {x['model_iliskisi']} → {x['insan_birim_iliskisi']}; "
                     f"{x['durum']}")
    return L


def gaps_md(a) -> str:
    from .run import od_distribution
    L = [f"# Eksik kanıt raporu", "",
         f"Çalışma alanı: `{a.ws.root.name}` · profil: {a.profile} · kabul edilmiş eşleşme: "
         f"{len(a.rows)} (sayılan {sum(r['sayilir'] for r in a.rows)})", "",
         "Önerilen OD ölçütün PUKÖ zincirinden hesaplanır (belge OD'si değil): P→2, +U→3, "
         "+K **ve** Ö→4, +Z→5; zincir eksikse düşük düzey. Düşük güvenli eşleşme önerilen OD'ye katılmaz. "
         "Kurallar: `docs/AUDIT.md`.", ""]
    for u in a.uyarilar:
        L.append(f"> Uyarı: {u}")
    dist = od_distribution(a)
    L += ["## OD dağılımı", "", "| OD | ölçüt |", "|---|---|"]
    L += [f"| {k} | {v} |" for k, v in dist.items()]
    L += ["", "## Öncelikli eksikler", ""]
    for i, c in enumerate(top_gaps(a), 1):
        L.append(f"{i}. {gap_line(c)}")
    kg = [c for c in a.criteria if c["kurum_geneli_yalniz"]]
    if kg:
        L += ["", "## Kurum/fakülte geneli belgeyle eşleşen, uygulama kanıtı eksik ölçütler", ""]
        for c in kg:
            docs = sorted({r["belge"] for r in a.rows if r["olcut"] == c["olcut"] and "kurum_geneli" in r["flags"]})
            L.append(f"- {c['olcut']} {c['baslik']}: " + "; ".join(f"`{d}`" for d in docs[:4]))
    en = [c for c in a.criteria if (c.get("eksik_kanit_notu") or {}).get("durum") == "neredeyse_kanitsiz"]
    if en:
        L += ["", "## Neredeyse kanıtsız ölçütler (eksik kanıt notu)", "",
              "Eşleşme var ama bölümün bu döneme ait, kurum geneli olmayan sayılan kanıtı yok. Not komisyon içindir "
              "(`audit-olcutler.json` `eksik_kanit_notu`); rapor metnine yazılmaz.", ""]
        for c in en:
            L.append(f"- {c['olcut']} {c['baslik']}: {c['eksik_kanit_notu']['metin']}")
    L += _birim_sections(a)
    L += _savunma_sections(a)
    L += _donem_sections(a)
    L += ["", "## Ölçüt ölçüt", ""]
    for c in a.criteria:
        z = " ".join(f"{KISA[x]}:{c['zincir'][x]['durum']}" for x in LINKS)
        L.append(f"### {c['olcut']} {c['baslik']} — önerilen OD{c['od']}"
                 + (f" (düşük güven dahil OD{c['od_dusuk_dahil']})" if c["od_dusuk_dahil"] != c["od"] else ""))
        L.append("")
        L.append(f"Zincir: {z} · eşleşme {c['eslesme']} · belge {c['belge']} · "
                 f"dolu yuva {c['yuva_dolu']}/{c['yuva_toplam']}")
        for n in c["notlar"]:
            L.append(f"- Not: {n}")
        if c["sonraki_od"]:
            L += _eksik_lines(c)
        if c["bos_yuvalar"]:
            L.append("- Boş yuvalar:")
            for y in c["bos_yuvalar"]:
                L.append(f"  - `{y['yuva']}` [{y['etiket']}] {y['metin']}")
        L.append("")
    return "\n".join(L).rstrip() + "\n"


# -- işaretli bölümler ve "Kanıtla cevaplanmayan sorular" ----------------------------------------
# gaps.md'nin gövdesini audit yazar; öteki aşamalar kendi bölümlerini `<!-- bidr:<ad> -->` …
# `<!-- /bidr:<ad> -->` arasına yazar (ingest, kanıt seçimi, bağlantı yok, kapsam, …). Audit
# yeniden yazarken bütün bu bölümleri sırasıyla korur; yalnız kendi ürettiği soru bölümünü yeniler.

import json as _json
import re as _re
from pathlib import Path as _Path

SORU_FILE = "soru-kapsami.json"          # bidr.verify.run.SUMMARY (verify yazar; salt okunur)
SORU_BEGIN = "<!-- bidr:sorular -->"
SORU_END = "<!-- /bidr:sorular -->"
_BLOCK = _re.compile(r"<!-- bidr:([\w.-]+) -->.*?<!-- /bidr:\1 -->", _re.DOTALL)
DURUM = {"cevapsiz": "cevapsız", "uydurma_suphesi": "uydurma şüphesi"}


def marked_blocks(text: str, skip: tuple[str, ...] = ()) -> list[str]:
    """gaps.md'deki işaretli bölümler (belgedeki sırayla; adı `skip`'te olanlar hariç)."""
    return [m.group(0) + "\n" for m in _BLOCK.finditer(text or "") if m.group(1) not in skip]


def soru_block(ws_root) -> str | None:
    """`soru-kapsami.json` → "Kanıtla cevaplanmayan sorular" bölümü (işaretleyicilerle). Dosya yoksa
    (verify çalışmadı) ya da okunamazsa None. Kullanıcının rapordan çıkardığı (`cikar`) metin
    listelenmez."""
    p = _Path(ws_root) / SORU_FILE
    try:
        d = _json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(d, dict):
        return None
    olc = d.get("olcutler") or {}
    cikar = {c for c, e in olc.items() if isinstance(e, dict) and e.get("insan_karari") == "cikar"}
    acik = [q for q in d.get("kanitla_cevaplanmayan") or [] if q.get("olcut") not in cikar]
    den = [c for c in d.get("denetlenmedi") or [] if c not in cikar]
    L = [SORU_BEGIN, "## Kanıtla cevaplanmayan sorular", "",
         "FR-0833 her alt ölçüt açıklamasında beş soruyu ister (süreç, izleme, iyileştirme, kanıtlar, önceki "
         "yıla göre değişiklik). Doğrulayıcının kanıt atıflı bir cümleyle cevaplanmadığını bulduğu sorular "
         "(`soru-kapsami.json`): `cevapsız` kanıt yoksa doğrudur, kanıt varsa metne eklenmeli; `uydurma "
         "şüphesi` metni reddettirir.", ""]
    if acik:
        for q in acik:
            yer = f" ({', '.join(q.get('yerler') or [])})" if q.get("yerler") else ""
            ger = f": {q['gerekce']}" if q.get("gerekce") else ""
            L.append(f"- {q.get('olcut')} · {q.get('baslik') or q.get('soru')} — "
                     f"{DURUM.get(q.get('durum'), q.get('durum'))}{yer}{ger}")
    else:
        L.append("Denetlenen bütün metinlerde beş soru kanıtla cevaplandı.")
    L.append("")
    if den:
        L += ["### Soru kapsamı denetlenmeyen ölçütler", "",
              "Metin kod denetiminde reddedildi, yeniden doğrulamada ya da eski görevle doğrulandı; "
              "beş sorunun kapsamı bilinmiyor: " + ", ".join(den) + ".", ""]
    L.append(SORU_END)
    return "\n".join(L) + "\n"


def compose_gaps(body: str, old: str, ws_root) -> str:
    """Audit gövdesi + eski gaps.md'deki öteki aşamaların işaretli bölümleri + soru bölümü."""
    keep = marked_blocks(old, skip=("sorular",))
    sb = soru_block(ws_root)
    if sb:
        keep.append(sb)
    return body + ("\n" + "\n".join(keep) if keep else "")


def update_soru_gaps(gaps_path, ws_root) -> bool:
    """Yalnız soru bölümünü yeniler (verify sonrası çağrılabilir; gövdeye dokunmaz). Değiştiyse True."""
    gp = _Path(gaps_path)
    cur = gp.read_text(encoding="utf-8") if gp.exists() else ""
    sb = soru_block(ws_root) or ""
    m = _re.search(_re.escape(SORU_BEGIN) + r".*?" + _re.escape(SORU_END) + r"\n?", cur, _re.DOTALL)
    if m:
        new = cur[:m.start()] + sb + cur[m.end():]
    elif sb:
        new = (cur.rstrip() + "\n\n" if cur.strip() else "") + sb
    else:
        return False
    if new != cur:
        gp.write_text(new, encoding="utf-8")
        return True
    return False
