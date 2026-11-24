"""Tamamlanma denetimleri: `kor_denetim` ve `duzelt` (pipeline.yaml; salt okunur).

İkisi de isteğe bağlıdır: denetim istenmediyse (`bidr denetim prepare` hiç çalışmadıysa) `atlandi`;
varsayılan hat eskisi gibi biter. İstenince:
  kor_denetim  paketler → ajan (metni yazmamış, taze denetçi) → apply → kor-denetim.json;
  duzelt       metin bulgusu/kabul edilen OD → `bidr duzelt prepare` (hat write → verify → yonler → render →
               denetle'ye geri döner) → bölüm kararı bekleyen od/kanit bulgusu → insan (`bidr denetim karar`).
               Kabul edilen kanıt önerisi ikinci arama aşamasında işlenir (checks.ikinci_arama_tamam).
"""
from __future__ import annotations

from bidr.pipeline.checks import AJAN, INSAN, KOMUT, Check, Ctx

from . import run as KD


def kor_denetim_tamam(c: Ctx) -> Check:
    ws = c.ws
    prep, apply_ = c.fmt(c.stage["komut"][0]), c.fmt(c.stage["komut"][2])
    info, js = KD.tur_info(ws), KD.load(ws)
    if not info and not js:
        return Check(atlandi=True, neden="kör denetim istenmedi (isteğe bağlı; istemek için: "
                                         f"{prep})")
    if js and info and js.get("id") == info.get("id"):
        oz = js.get("ozet") or {}
        prog = {"tur": js.get("tur"), "ortalama": oz.get("ortalama"), "yon_ortalama": oz.get("yon_ortalama"),
                **{f"bulgu_{k}": n for k, n in (oz.get("bulgu") or {}).items()}}
        return Check(bitti=True, ilerleme=prog,
                     neden=f"tur {js.get('tur')}: ölçüt puanı ortalaması {oz.get('ortalama')}, yön hücreleri "
                           f"{oz.get('yon_ortalama')} (iç ölçüm; {KD.OUT_MD})")
    p = KD.pending(ws)
    prog = {"tur": (info or {}).get("tur"), "paket": len(p["paket"]), "cevapsiz": len(p["cevapsiz"]),
            "gecersiz": len(p["gecersiz"]), "eski": len(p["eski"])}
    if not p["paket"] or p["eski"]:
        return Check(kim=KOMUT, komutlar=[prep], ilerleme=prog,
                     neden=("denetim paketleri yok" if not p["paket"] else
                            f"{len(p['eski'])} paket eski (rapor paketten sonra değişti)") + ": prepare")
    if p["cevapsiz"] or p["gecersiz"]:
        parts = [x for x in (f"{len(p['cevapsiz'])} paket cevapsız" if p["cevapsiz"] else "",
                             f"{len(p['gecersiz'])} cevap geçersiz (work/kor_denetim/GECERSIZ.md)" if p["gecersiz"]
                             else "") if x]
        return Check(kim=AJAN, ilerleme=prog, bekleyen=sorted(p["cevapsiz"] | p["gecersiz"]),
                     komutlar=["(metni YAZMAMIŞ ve doğrulamamış, taze ve bağımsız bir denetçi ajan; model Opus) "
                               "work/kor_denetim/README.md'yi oku; cevapsız/geçersiz her <anahtar>.json için "
                               "<anahtar>.out.json yaz (ölçüt: puan, OD görüşü, D/K/U cümleleri, bulgular, "
                               "kullanılmayan belgeler; yon_X: hücre puanları ve madde bulguları; bütün alıntılar "
                               "birebir)", apply_],
                     neden=", ".join(parts) + ": model işi ajanda (kör denetim)")
    return Check(kim=KOMUT, komutlar=[apply_], ilerleme=prog, neden="denetim cevapları işlenmemiş: apply")


def duzelt_tamam(c: Ctx) -> Check:
    from .duzelt import targets
    ws = c.ws
    js = KD.load(ws)
    if not js:
        return Check(atlandi=True, neden="kör denetim yapılmadı: düzeltilecek bulgu yok")
    if int(js.get("tur") or 1) >= 2:
        return Check(bitti=True, neden=f"tur {js.get('tur')} ölçümdür (önce/sonra karşılaştırması): bulguları "
                                       "kendiliğinden düzeltilmez")
    st = KD.statuses(ws, js)
    count: dict[str, int] = {}
    for d, _ in st.values():
        count[d] = count.get(d, 0) + 1
    prog = {k: count.get(k, 0) for k in ("duzeltilecek", "duzeltildi", "karar_bekliyor", "kabul", "ret", "bilgi",
                                          "dogrulanamadi")}
    crit, areas = targets(ws)
    kb = KD.karar_bekleyen(ws, js)
    uy = []
    if count.get("dogrulanamadi"):
        uy.append(f"{count['dogrulanamadi']} bulgunun alıntısı raporda/belgede doğrulanamadı: işlenmedi "
                  f"({KD.OUT_MD} 'Doğrulanamayan bulgular')")
    if crit or areas:
        if kb:
            uy.append(f"{len(kb)} bulgu bölüm kararı bekliyor (OD/kanıt önerisi); düzeltmeden sonra sorulur")
        what = ", ".join(x for x in (f"{len(crit)} ölçüt metni ({', '.join(crit)})" if crit else "",
                                     f"{len(areas)} alanın yönleri ({', '.join(areas)})" if areas else "") if x)
        return Check(kim=KOMUT, komutlar=[c.fmt(c.stage["komut"][0])], ilerleme=prog, uyarilar=uy,
                     neden=f"denetim bulgularıyla düzeltilecek: {what}. prepare yazım/yön paketlerini düzeltme notuyla "
                           "açar; hat write → verify → yonler → render → denetle sırasıyla yeniden koşar (yazımı ve "
                           "doğrulamayı ayrı, taze ajanlara ver)")
    if kb:
        karar = c.fmt("bidr denetim karar -w {ws}")
        return Check(kim=INSAN, ilerleme=prog, uyarilar=uy, karar_bekleyen=kb,
                     komutlar=[f"(insan) {KD.OUT_MD} 'OD önerileri' ve 'Kullanılmamış belge önerileri' bölümlerini "
                               "kullanıcıya göster; karar bölümündür (ajan vermez)",
                               f"{karar} <bulgu_id> kabul [--not \"…\"]   # KULLANICI derse: OD değişikliği metne ve "
                               "rapora yansır / belge inceleme adayı olur",
                               f"{karar} <bulgu_id> ret [--not \"…\"]     # KULLANICI derse: rapor olduğu gibi kalır"],
                     neden=f"{len(kb)} denetim bulgusu bölüm kararı bekliyor: "
                           + ", ".join(f"{x['bulgu_id']} ({x['sinif']})" for x in kb[:8])
                           + (" …" if len(kb) > 8 else ""))
    return Check(bitti=True, ilerleme=prog, uyarilar=uy,
                 neden=f"{count.get('duzeltildi', 0)} metin bulgusu düzeltildi; {count.get('kabul', 0)} öneri kabul, "
                       f"{count.get('ret', 0)} ret")
