"""Kanıt adının kaynağı ve öncelik sırası: insan > model parça adı > model belge adı > kural.

- `kanit-adlari.jsonl` (satır = `{doc_id, ad, kaynak: insan|model, …}`; `(doc_id, kaynak)`
  başına tek kayıt). Model kayıtlarını `bidr name apply` çalışma alanına, insan kayıtlarını
  `bidr audit apply` inceleme klasörüne (`--out`; vars. çalışma alanı) yazar.
- `decisions.jsonl` ince kararındaki `ince.kanit_adi` (classify_fine v7; denetimden geçmişse).
- Kural: `bidr.file.naming.evidence_name` (identify `baslik`'ı, yoksa tür etiketi).

Model kaynakları arasında `kanit-adlari.jsonl` önce gelir (adlandırma görevi ayrı ve sonra
çalışır). Her ad yeniden denetlenir (kişi/unvan/e-posta): tutmayan kaynak atlanır, uyarı verilir.
Belge metni verilmişse model adının belgede dayanağı da denetlenir (`ground.grounding`): adın
resmî türü/birimi/niteliği/sayısı metinde yoksa ya da kabul edilmiş alıntı derlemenin başka bir
parçasından geliyorsa ad kullanılır ama "doğrulanmalı" uyarısı verilir ve `dogrulanmali[doc_id]`
kaydedilir (dosyalama yuva işaretine çevirir: `slot_flags`). İnsan adı denetlenmez.

Derleme belgede (`name_evidence` v3) model kaydı yuva başına parça adı taşıyabilir
(`parca_adlari: {yuva: ad}`, apply'da derleme saptanmış ve aynı parça tek ad olacak biçimde
düzeltilmiş). Dosyalama kalemin (ölçüt × belge) yuvalarından ilkinin parça adını kullanır
(`item_name`; kaynak `model_parca`); insan adı varsa parça adı kullanılmaz. Parça adlı yuvanın
dayanağı parça adıyla denetlenir.
"""
from __future__ import annotations

import json
from pathlib import Path

from bidr.common import read_jsonl, write_jsonl

from .check import check_name
from .ground import grounding, slot_issues

NAMES = "kanit-adlari.jsonl"
KAYNAKLAR = ("insan", "model")


def load_names(*dirs: Path | str | None) -> dict[str, dict[str, dict]]:
    """doc_id → {kaynak → kayıt}. Sonraki klasör aynı (doc_id, kaynak) için öncekini ezer."""
    out: dict[str, dict[str, dict]] = {}
    seen: set[Path] = set()
    for d in dirs:
        if not d:
            continue
        p = (Path(d).expanduser().resolve() / NAMES)
        if p in seen or not p.exists():
            continue
        seen.add(p)
        for r in read_jsonl(p):
            if r.get("doc_id") and r.get("kaynak") in KAYNAKLAR and r.get("ad"):
                out.setdefault(r["doc_id"], {})[r["kaynak"]] = r
    return out


def upsert(path: Path, recs: list[dict]) -> int:
    """`(doc_id, kaynak)` anahtarıyla ekle/güncelle; dosya doc_id sırasıyla yeniden yazılır."""
    path = Path(path)
    cur = {(r["doc_id"], r["kaynak"]): r for r in read_jsonl(path)} if path.exists() else {}
    n = 0
    for r in recs:
        k = (r["doc_id"], r["kaynak"])
        if cur.get(k) != r:
            n += 1
        cur[k] = r
    path.parent.mkdir(parents=True, exist_ok=True)
    write_jsonl(path, [cur[k] for k in sorted(cur)])
    return n


def part_grounding(g: dict, text: str, quotes: dict[str, str], parts: dict[str, str]) -> dict:
    """Belge adının dayanağına (`grounding`, parça adlı yuvalar hariç) parça adlı yuvaların
    dayanağını ekler: parça adı alıntının çevresinde tutmuyorsa yuva `parca_uyumsuz`."""
    bad = [y for y, ad in parts.items() if y in quotes and slot_issues(ad, text, {y: quotes[y]})]
    if not bad:
        return g
    p = sorted({*g["parca_uyumsuz"], *bad})
    return {**g, "dogrulanmali": True, "parca_uyumsuz": p}


def decision_name(rec: dict | None) -> str | None:
    ka = ((rec or {}).get("ince") or {}).get("kanit_adi")
    if isinstance(ka, dict) and ka.get("durum") == "kabul" and ka.get("ad"):
        return ka["ad"]
    return None


class Resolver:
    """Belge → (ad, kaynak, uyarılar). `aliases`: aynı metnin kopyaları (insan adı kopyanın
    satırında düzeltilmiş olabilir)."""

    def __init__(self, names: dict[str, dict[str, dict]], decisions: dict[str, dict],
                 docs: dict[str, dict], labels: dict[str, str] | None = None, text_of=None):
        self.names, self.decisions, self.docs, self.labels = names, decisions, docs, labels or {}
        self.text_of = text_of                  # doc_id → belge metni ("" yoksa); None: denetim yok
        self.dogrulanmali: dict[str, dict] = {}

    @classmethod
    def load(cls, ws_root: Path, *extra_dirs, docs: dict | None = None,
             decisions: dict | None = None, labels: dict | None = None) -> "Resolver":
        ws_root = Path(ws_root)
        if docs is None:
            p = ws_root / "documents.jsonl"
            docs = {r["doc_id"]: r for r in read_jsonl(p) if r.get("doc_id")} if p.exists() else {}
        if decisions is None:
            p = ws_root / "decisions.jsonl"
            decisions = {r["doc_id"]: r for r in read_jsonl(p) if r.get("doc_id")} if p.exists() else {}
        from bidr.common import Workspace
        ws = Workspace(ws_root)

        def text_of(did: str) -> str:
            p = ws.text_path(did)
            return p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""
        return cls(load_names(ws_root, *extra_dirs), decisions, docs, labels, text_of=text_of)

    def candidates(self, did: str, aliases: list[str] | tuple = ()) -> list[tuple[str, str]]:
        ids = [did, *[a for a in aliases if a != did]]
        out = []
        for x in ids:
            r = (self.names.get(x) or {}).get("insan")
            if r:
                out.append((r["ad"], "insan"))
        r = (self.names.get(did) or {}).get("model")
        if r:
            out.append((r["ad"], "model"))
        d = decision_name(self.decisions.get(did))
        if d:
            out.append((d, "model"))
        return out

    def resolve(self, did: str, aliases: list[str] | tuple = ()) -> tuple[str, str, list[str]]:
        from bidr.file.naming import evidence_name, safe_name
        uy: list[str] = []
        for ad, src in self.candidates(did, aliases):
            ok, errs = check_name(ad)
            if ok:
                if src == "model":
                    uy += self._ground(did, ok)
                return safe_name(ok), src, uy
            uy.append(f"{did}: {src} kanıt adı reddedildi ({', '.join(errs)}): {json.dumps(ad, ensure_ascii=False)}")
        d = self.docs.get(did) or {}
        ad, u = evidence_name({**d, "doc_id": did}, self.labels.get(d.get("doc_type")))
        return ad, "kural", uy + u

    def quotes(self, did: str) -> dict[str, str]:
        rec = self.decisions.get(did) or {}
        return {m["yuva"]: m.get("alinti") or "" for m in rec.get("eslesmeler") or []
                if m.get("kabul") and m.get("yuva")}

    def parts(self, did: str, aliases: list[str] | tuple = ()) -> dict[str, str]:
        """Belgenin geçerli parça adları ({model yuvası: ad}). Yalnız belge adı insan değilse ve
        model kaydı (`kanit-adlari.jsonl`) belge adı olarak kabul edilebiliyorsa."""
        if any((self.names.get(x) or {}).get("insan") for x in [did, *aliases]):
            return {}
        rec = (self.names.get(did) or {}).get("model") or {}
        if not rec or not check_name(rec.get("ad"))[0]:
            return {}
        from bidr.file.naming import safe_name
        out = {}
        for y, ad in (rec.get("parca_adlari") or {}).items():
            ok, _ = check_name(ad)
            if ok:
                out[y] = safe_name(ok)
        return out

    def item_name(self, did: str, yuvalar: list[str], base: tuple[str, str],
                  aliases: list[str] | tuple = ()) -> tuple[str, str]:
        """Kalemin (ölçüt × belge) adı: yuvalarından (model yuvası, eşleşme sırasıyla) ilkinin
        parça adı (`model_parca`), yoksa belge adı `base` (`resolve`'un (ad, kaynak)'ı)."""
        if base[1] != "model":
            return base
        pa = self.parts(did, aliases)
        y = next((y for y in yuvalar if y in pa), None)
        return (pa[y], "model_parca") if y else base

    def item_flags(self, did: str, yuvalar: list[str], aliases: list[str] | tuple = ()) -> list[str]:
        """Kalemin işaretleri: yuvalarının `slot_flags`'i; yuvaları farklı adlara (parça adı /
        belge adı) düşüyorsa `parca_adi_coklu` (tek dosya, tek ad: ad yuvaların bir kısmını anlatır)."""
        out = [f for y in yuvalar for f in self.slot_flags(did, y)]
        pa = self.parts(did, aliases)
        if pa and len({pa.get(y, "") for y in yuvalar}) > 1:
            out.append("parca_adi_coklu")
        return list(dict.fromkeys(out))

    def _ground(self, did: str, ad: str) -> list[str]:
        if self.text_of is None:
            return []
        text = self.text_of(did) or ""
        q = self.quotes(did)
        pa = self.parts(did)
        g = grounding(ad, text, {y: x for y, x in q.items() if y not in pa})
        g = part_grounding(g, text, q, pa)
        if not g["dogrulanmali"]:
            self.dogrulanmali.pop(did, None)
            return []
        self.dogrulanmali[did] = {"ad": ad, **g}
        why = g["belge"] + ([f"parca_uyumsuz: {', '.join(g['parca_uyumsuz'])}"] if g["parca_uyumsuz"] else [])
        return [f"{did}: model kanıt adı doğrulanmalı ({'; '.join(why)}): {json.dumps(ad, ensure_ascii=False)}"]

    def slot_flags(self, did: str, yuva: str) -> list[str]:
        """Dosyalama için yuva işareti: `ad_dogrulanmali` (belge düzeyi) ya da `ad_parca_uyumsuz`."""
        g = self.dogrulanmali.get(did)
        if not g:
            return []
        out = ["ad_dogrulanmali"] if g["belge"] else []
        return out + (["ad_parca_uyumsuz"] if yuva in g["parca_uyumsuz"] else [])
