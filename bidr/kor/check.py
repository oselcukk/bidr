"""Tamamlanma denetimleri: `kor_denetim` ve `duzelt` (pipeline.yaml; salt okunur).

İkisi de isteğe bağlıdır: denetim istenmediyse (`bidr denetim prepare` hiç çalışmadıysa) `atlandi`;
varsayılan hat eskisi gibi biter. İstenince:
  kor_denetim  paketler → ajan (metni yazmamış, taze denetçi) → apply → kor-denetim.json;
  duzelt       metin bulgusu/kabul edilen OD → `bidr duzelt prepare` (hat write → verify → yonler → render →
               denetle'ye geri döner). Metin düzeltmeleri bitince aşama biter: bölüm kararı bekleyen od/kanit
               önerileri hattı TUTMAZ, `oneri_bekleyen` ile bilgi olarak gösterilir (`bidr denetim karar` ne zaman
               verilirse). Sonradan kabul edilen OD bu aşamayı yeniden açar (küçük düzeltme turu: duzelt prepare →
               write → verify → render …); kabul edilen kanıt önerisi ikinci arama aşamasında işlenir
               (checks.ikinci_arama_tamam).
               Bölümün daha önce olduğu gibi kabul ettiği metne (verify/write karar `kabul`, aynı içerik) düşen metin
               bulgusu kendiliğinden düzeltilmez: "Kabul edilmiş metne öneri" olarak bölüm kararına gelir (hattı
               tutmaz); kabul → küçük düzeltme turu, ret → metin aynen kalır.
"""
from __future__ import annotations

from bidr.pipeline.checks import AJAN, KOMUT, Check, Ctx

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
    if kb:
        uy.append(f"{len(kb)} denetim önerisi (OD/kanıt/kabul edilmiş metne öneri) bölüm kararını bekliyor; hattı "
                  f"tutmaz, rapor tamamlandı sayılır ({KD.OUT_MD} 'OD önerileri', 'Kullanılmamış belge önerileri', "
                  "'Kabul edilmiş metne öneriler'; karar: "
                  + c.fmt("bidr denetim karar -w {ws}") + " <bulgu_id> kabul|ret — yalnız KULLANICI derse)")
    if crit or areas:
        what = ", ".join(x for x in (f"{len(crit)} ölçüt metni ({', '.join(crit)})" if crit else "",
                                     f"{len(areas)} alanın yönleri ({', '.join(areas)})" if areas else "") if x)
        return Check(kim=KOMUT, komutlar=[c.fmt(c.stage["komut"][0])], ilerleme=prog, uyarilar=uy,
                     oneri_bekleyen=kb,
                     neden=f"denetim bulgularıyla düzeltilecek: {what}. prepare yazım/yön paketlerini düzeltme notuyla "
                           "açar; hat write → verify → yonler → render → denetle sırasıyla yeniden koşar (yazımı ve "
                           "doğrulamayı ayrı, taze ajanlara ver)")
    return Check(bitti=True, ilerleme=prog, uyarilar=uy, oneri_bekleyen=kb,
                 neden=f"{count.get('duzeltildi', 0)} metin bulgusu düzeltildi; {count.get('kabul', 0)} öneri kabul, "
                       f"{count.get('ret', 0)} ret" + (f"; {len(kb)} öneri bölüm kararını bekliyor (hattı tutmaz)"
                                                       if kb else ""))
