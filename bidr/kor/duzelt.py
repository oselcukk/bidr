"""`bidr duzelt prepare`: kör denetimin metin bulgularını ve bölümün kabul ettiği OD kararlarını
düzeltme notu olarak yazım (`work/write/<ölçüt>.json`) ve yön (`work/yonler/<alan>.json`) paketlerine
koyar. Paketin geri kalanı olağan yazım paketidir: yazım kuralları, kod denetimi (yasak ifade, atıf, OD
aşımı) ve ardından bağımsız doğrulama (`bidr verify`) aynen işler; hat write → verify → yonler →
render → denetle sırasıyla yeniden koşar (`bidr next` gösterir).

Not, metin kaydına `duzeltme: {denetim, tur, bulgular}` izi olarak geçer; iz bu denetimin bulgusunu
"düzeltildi" sayar.
Düzeltme yeni bir denemedir: yazım + doğrulama yeniden yazım sayacı (`tur`) her denetim düzeltmesinde
sıfırdan başlar (önceki rapor turlarında sınırı dolmuş metin hemen insan kararına düşmez). Bölümün
rapordan çıkardığı (`cikar`) metin düzeltmeye girmez (`KD.excluded`). Bölümün olduğu gibi kabul ettiği
metne (`verify|write karar … kabul`, aynı içerik) düşen metin bulgusu kendiliğinden girmez: bölüm kararı
bekleyen öneri olur (`KD.kabul_metni_ids`); kabul edilirse not olarak girer (küçük tur), ret edilirse metin
aynen kalır. Metin sonradan başka nedenle değiştiyse kabul eskimiştir, olağan düzeltme sürer. Not `bidr write prepare` / `bidr yonler prepare` her çalıştığında da eklenir
(bidr/kor/run.py `duzeltme`): metin başka bir nedenle yeniden yazılsa da not kaybolmaz. İkinci denetim
turu ölçümdür: bulguları paketlere girmez.
"""
from __future__ import annotations

from pathlib import Path

from bidr.common import Workspace
from bidr.write import run as W

from . import run as KD


def targets(ws: Workspace) -> tuple[list[str], list[str]]:
    """(notu bekleyen ölçütler, notu bekleyen alanlar)."""
    js = KD.load(ws)
    if not js or int(js.get("tur") or 1) >= 2:
        return [], []
    keys: set[str] = set()
    for f in js.get("bulgular") or []:
        if f["sinif"] == "metin" and KD.target(f):
            keys.add(KD.target(f))
        elif f["sinif"] == "od" and f.get("olcut"):
            keys.add(f["olcut"])
    crit, areas = [], []
    for k in sorted(keys):
        t = KD._record(ws, k)
        if not t or not KD.notes(ws, k, js, t):
            continue
        (areas.append(k[len(KD.YON):]) if KD.is_yon(k) else crit.append(k))
    return crit, areas


def prepare(ws_root: Path, *, backend: W.Backend | None = None) -> dict:
    ws = Workspace(Path(ws_root))
    js = KD.load(ws)
    if not js:
        raise KD.DenetimHatasi(f"{KD.OUT_JSON} yok: önce kör denetim (`bidr denetim prepare|apply`)")
    st: dict = {"tur": js.get("tur"), "olcut": [], "alan": []}
    if int(js.get("tur") or 1) >= 2:
        st["olcum"] = True
        return st
    crit, areas = targets(ws)
    if crit:
        sp = W.source_paths(ws.root)
        r = W.prepare(ws.root, only=crit, index=sp["index"], audit=sp["audit"], onceki=sp["onceki"],
                      notes=sp["notes"], backend=backend)
        st["olcut"] = r.get("duzeltme") or []
        st["write"] = {k: r.get(k) for k in ("paket", "yeni", "bekleyen", "klasor")}
    if areas:
        from bidr.write import yonler as Y
        r = Y.prepare(ws.root, only=areas, backend=backend)
        st["alan"] = r.get("duzeltme") or []
        st["yonler"] = {k: r.get(k) for k in ("paket", "yeni", "bekleyen", "klasor")}
    return st
