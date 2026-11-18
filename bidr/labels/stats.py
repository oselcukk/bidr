"""`bidr labels stats` ve `labels-report.md` üretimi."""
from __future__ import annotations

from collections import Counter, defaultdict

from .parse import ALAN, ALT, ANA, DUZEY_SIRASI

DUZEYLER = (ALT, ANA, ALAN)


def _olcut_anahtari(o: str):
    return [p if not p.isdigit() else int(p) for p in o.split(".")]


def istatistik(rows: list[dict]) -> dict:
    birim: dict[str, dict] = {}
    for r in rows:
        for b in r["birimler"]:
            s = birim.setdefault(b, {
                "dosya": 0, "kanit_adayi": 0, "etiketli": 0, "indirilmemis": 0, "rapor_dosyasi": 0,
                "etiket_disi": 0, "od_li_etiket": 0, "od_li_belge": 0,
                "olcut": Counter(), "etiket_duzey": Counter(), "belge_en_ince": Counter(),
                "kaynak": Counter(),
            })
            s["dosya"] += 1
            if r["durum"] == "indirilmemis":
                s["indirilmemis"] += 1
            if r["rapor_dosyasi"]:
                s["rapor_dosyasi"] += 1
            if r["etiket_disi"]:
                s["etiket_disi"] += 1
            if not r["rapor_dosyasi"] and not r["etiket_disi"]:
                s["kanit_adayi"] += 1
            # birim görünümü: yalnız bu birimin yollarından / raporundan gelen kanıtlar
            etk = []
            for e in r["etiketler"]:
                kn = [k for k in e["kanitlar"] if k.get("birim", b) == b]
                if kn:
                    etk.append((e, kn))
            if not etk:
                continue
            s["etiketli"] += 1
            s["belge_en_ince"][max((e["duzey"] for e, _ in etk), key=DUZEY_SIRASI.get)] += 1
            od_var = False
            for e, kn in etk:
                s["olcut"][e["olcut"]] += 1
                s["etiket_duzey"][e["duzey"]] += 1
                for k in {k["kaynak"] for k in kn}:
                    s["kaynak"][k] += 1
                if any(k.get("od") for k in kn):
                    s["od_li_etiket"] += 1
                    od_var = True
            if od_var:
                s["od_li_belge"] += 1
    return birim


def _oran(a: int, b: int) -> str:
    return f"{100 * a / b:.0f}%" if b else "-"


def metin(rows: list[dict], ayrinti: bool = True) -> str:
    st = istatistik(rows)
    sat = []
    sat.append(f"Kayıt (benzersiz içerik ya da indirilmemiş dosya): {len(rows)}")
    sat.append("")
    sat.append(f"{'birim':<12} {'dosya':>5} {'kanıt':>5} {'etiketli':>8} {'oran':>5} "
               f"{'alt':>4} {'ana':>4} {'alan':>4} {'OD-etk':>6} {'OD-blg':>6} {'indir.yok':>9}")
    toplam = Counter()
    for b in sorted(st):
        s = st[b]
        sat.append(
            f"{b:<12} {s['dosya']:>5} {s['kanit_adayi']:>5} {s['etiketli']:>8} "
            f"{_oran(s['etiketli'], s['kanit_adayi']):>5} "
            f"{s['belge_en_ince'][ALT]:>4} {s['belge_en_ince'][ANA]:>4} {s['belge_en_ince'][ALAN]:>4} "
            f"{s['od_li_etiket']:>6} {s['od_li_belge']:>6} {s['indirilmemis']:>9}"
        )
        for a in ("dosya", "kanit_adayi", "etiketli", "od_li_etiket", "od_li_belge", "indirilmemis"):
            toplam[a] += s[a]
    sat.append("")
    sat.append("dosya: birimdeki kayıt; kanıt: rapor dosyası ve --etiketsiz dışı; oran = etiketli/kanıt;")
    sat.append("alt/ana/alan: belgenin en ince etiket düzeyi; OD-etk: OD'li etiket; OD-blg: en az bir OD'li etiketi olan belge.")
    if not ayrinti:
        return "\n".join(sat)
    for b in sorted(st):
        s = st[b]
        sat.append("")
        sat.append(f"== {b}")
        sat.append("etiket düzeyi: " + ", ".join(f"{d}={s['etiket_duzey'][d]}" for d in DUZEYLER))
        sat.append("etiket kaynağı: " + ", ".join(f"{k}={v}" for k, v in sorted(s["kaynak"].items())))
        sat.append("ölçüt başına kanıt (belge sayısı):")
        olc = sorted(s["olcut"].items(), key=lambda x: _olcut_anahtari(x[0]))
        satir = []
        for o, n in olc:
            satir.append(f"{o}:{n}")
            if len(satir) == 10:
                sat.append("  " + "  ".join(satir))
                satir = []
        if satir:
            sat.append("  " + "  ".join(satir))
    return "\n".join(sat)


def rapor_md(sonuc, kaynak: str, ws: str) -> str:
    rows = sonuc.kayitlar
    s = ["# Etiket çıkarımı raporu", "",
         f"- kaynak: `{kaynak}`", f"- çalışma klasörü: `{ws}`",
         f"- dosya: {len(sonuc.dosyalar)}, kayıt: {len(rows)}, etiketli kayıt: {sum(r['etiketli'] for r in rows)}",
         f"- rapor satırı: {sum(r['satir'] for r in sonuc.raporlar)}, dosyaya eşlenen: {sonuc.eslesen_satir}, "
         f"eşlenemeyen: {len(sonuc.eslesmeyen)}", ""]
    s += ["## Özet", "", "```", metin(rows, ayrinti=False), "```", ""]
    s += ["## Okunan raporlar", "", "| rapor | birim | durum | kanıt satırı | eşlenen |", "|---|---|---|---|---|"]
    for r in sonuc.raporlar:
        s.append(f"| {r['yol']} | {r['birim']} | {r['durum']} | {r['satir']} | {r['eslesen']} |")
    s.append("")

    yontem = Counter()
    for r in rows:
        for e in r["etiketler"]:
            for k in e["kanitlar"]:
                if k["kaynak"] == "rapor":
                    yontem[k["eslesme"]] += 1
    s += ["Eşleme yöntemi (dosya kopyası başına): " + ", ".join(f"{k}={v}" for k, v in sorted(yontem.items())), ""]

    s += ["## Rapor satırı ↔ dosya eşleşmeyenler", "",
          "neden: `ad_eslesmedi` (birimde benzer adlı dosya yok; çoğu web bağlantısı), "
          "`kod_tuttu_ad_tutmadi` (aynı kodlu dosya var ama adı benzemiyor), `belirsiz_cok_aday`, "
          "`birimde_dosya_yok`, `ad_bos`.", ""]
    by = defaultdict(list)
    for e in sonuc.eslesmeyen:
        by[(e.birim, e.rapor)].append(e)
    for (b, rp), es in sorted(by.items()):
        nedenler = Counter(e.neden for e in es)
        s.append(f"### {b} — {rp} ({len(es)}; " + ", ".join(f"{k}={v}" for k, v in nedenler.items()) + ")")
        s.append("")
        s.append("| bölüm | rapordaki satır | neden | en yakın dosya (benzerlik) |")
        s.append("|---|---|---|---|")
        for e in es:
            yak = f"{e.en_yakin} ({e.benzerlik})" if e.en_yakin and (e.neden.startswith("kod") or (e.benzerlik or 0) >= 0.5) else ""
            s.append(f"| {e.bolum} | {e.ham.replace('|', '/')} | {e.neden} | {yak.replace('|', '/')} |")
        s.append("")

    s += ["## Çözülemeyen / şüpheli biçimler", ""]
    sor = [(r, x) for r in rows for x in r["sorunlar"]]
    for r, x in sor:
        s.append(f"- {x['sorun']} ({x.get('kaynak', '')}): `{x.get('ham', x.get('ayrinti', ''))}` — {r['iz']['yollar'][0]['yol']}")
    cik = [(r, e) for r in rows for e in r["etiketler"]
           if any(k.get("bolum_cikarim") for k in e["kanitlar"])]
    if cik:
        s.append(f"- Rapor başlığı kodsuz (otomatik numara), bölüm sıradan çıkarıldı: {len(cik)} etiket "
                 "(`bolum_cikarim: true`).")
    celiski = [(r, e) for r in rows for e in r["etiketler"] if e["od_celiski"]]
    s += ["", f"### OD çelişkisi ({len(celiski)})", "", "Aynı belge ve ölçüt için kaynaklar farklı OD veriyor.", ""]
    for r, e in celiski:
        hamlar = "; ".join(f"{k['kaynak']}:{k.get('od')}" for k in e["kanitlar"] if k.get("od"))
        s.append(f"- {e['olcut']} {e['od']} — {r['iz']['yollar'][0]['yol']} ({hamlar})")
    ind = [r for r in rows if r["durum"] != "ok"]
    s += ["", f"## İndirilmemiş / okunamayan ({len(ind)})", "",
          "doc_id yok; etiket yalnız yol üzerinden. Okumak iCloud indirmesini tetikleyeceği için dokunulmadı.", ""]
    for r in ind:
        etk = ", ".join(e["olcut"] for e in r["etiketler"]) or "etiketsiz"
        s.append(f"- [{r['durum']}] {r['iz']['yollar'][0]['yol']} → {etk}")
    s.append("")
    return "\n".join(s)
