"""Model öncesi maskeleme (`privacy.mask_before_model`, varsayılan kapalı).

Açıksa iş paketlerine (ajan modu) ve hat modu istemlerine giren metinlerde, yayın kopyasıyla aynı
tespit kurallarıyla kişisel veri yer tutucuya çevrilir (`[TC_NO]`, `[OGRENCI_NO]`, `[EPOSTA]`,
`[TELEFON]`, `[IBAN]`, `[AD]`). Kapalıyken girdiler olduğu gibi döner.

Bu modül iş paketi hazırlayan kodu değiştirmez; çağrılabilir yardımcılar sunar:

    from bidr.mask.model import ModelMasker
    mm = ModelMasker.load(ws_root)          # config.yaml'ı bir kez okur
    inputs = mm.inputs(inputs)              # render_task / run_task'tan önce
    ok = verify_quote(quote, mm.text(doc_text))   # alıntı denetimi modelin gördüğü metne karşı
    # ya da Backend'e hazır sarmalayıcılar:
    Backend(render_task=mm.render(llm.render_task), verify_quote=mm.verify_quote(llm.verify_quote))

Alıntı denetimi: model maskeli metni gördüğünden alıntıları yer tutucu içerebilir; denetim aynı
kurallarla maskelenmiş metne karşı yapılmalıdır (`ModelMasker.text`; tespit belirleyicidir).
`ModelMasker.verify_quote` bunu yapar ve eşleşme aralığını özgün metne geri çevirir.

Yerel model genişletme noktası: `privacy.maskeleme.yerel_model` ileride ad/kişi tanıma için yerel
bir modeli tespitçi olarak bağlamak üzere ayrıldı (`bidr.mask.detect.register_detector`); bu
sürümde uygulanmaz, yalnız uyarı verir.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Callable, Iterable

from .detect import PLACEHOLDERS, MaskRules, detect, mask_text, read_ws_config


def mask_before_model_enabled(config: dict | None) -> bool:
    priv = (config or {}).get("privacy") if isinstance(config, dict) else None
    return bool(isinstance(priv, dict) and priv.get("mask_before_model", False))


def _walk(v: Any, rules: MaskRules, counts: Counter, skip: frozenset, key: str | None = None) -> Any:
    if key is not None and key in skip:
        return v
    if isinstance(v, str):
        new, c = mask_text(v, rules)
        counts.update(c)
        return new
    if isinstance(v, dict):
        return {k: _walk(x, rules, counts, skip, k) for k, x in v.items()}
    if isinstance(v, list):
        return [_walk(x, rules, counts, skip) for x in v]
    if isinstance(v, tuple):
        return tuple(_walk(x, rules, counts, skip) for x in v)
    return v


class ModelMasker:
    """Çalışma alanı ayarına göre model girdisini maskeler (kapalıysa kimlik işlevi)."""

    def __init__(self, enabled: bool, rules: MaskRules | None = None, skip_keys: Iterable[str] = ()):
        self.enabled = bool(enabled)
        self.rules = rules or MaskRules()
        self.skip_keys = frozenset(skip_keys)
        self.counts: Counter = Counter()       # bu nesneyle maskelenenlerin toplamı (değer tutulmaz)

    @classmethod
    def from_config(cls, config: dict | None, base: Path | None = None, **kw) -> "ModelMasker":
        on = mask_before_model_enabled(config)
        return cls(on, MaskRules.from_config(config, base) if on else None, **kw)

    @classmethod
    def load(cls, ws_root: Path, **kw) -> "ModelMasker":
        return cls.from_config(read_ws_config(Path(ws_root)), Path(ws_root), **kw)

    @property
    def warnings(self) -> list[str]:
        return self.rules.warnings if self.enabled else []

    def text(self, s: str) -> str:
        if not self.enabled or not s:
            return s
        new, c = mask_text(s, self.rules)
        self.counts.update(c)
        return new

    def text_with_map(self, s: str) -> tuple[str, list[tuple[int, int, int, int]]]:
        """Maskeli metin + yer tutucu kesimleri `(m_bas, m_son, o_bas, o_son)` (maskeli ↔ özgün)."""
        if not self.enabled or not s:
            return s, []
        parts, segs, pos, mpos = [], [], 0, 0
        for f in detect(s, self.rules):
            parts.append(s[pos:f.start])
            mpos += f.start - pos
            ph = PLACEHOLDERS.get(f.kind, f"[{f.kind.upper()}]")
            parts.append(ph)
            segs.append((mpos, mpos + len(ph), f.start, f.end))
            mpos += len(ph)
            pos = f.end
            self.counts[f.kind] += 1
        parts.append(s[pos:])
        return "".join(parts), segs

    @staticmethod
    def to_original(pos: int, segs, *, end: bool = False) -> int:
        """Maskeli metindeki konumu özgün metne çevirir (yer tutucunun içi → özgün değerin sınırı)."""
        shift = 0
        for mb, me, ob, oe in segs:
            if pos < mb or (pos == mb and not end):
                break
            if pos < me or (pos == me and end):
                return oe if end else ob
            shift = oe - me
        return pos + shift

    def render(self, render_fn: Callable) -> Callable:
        """`render_task(task, inputs, ...)` sarmalayıcı: girdiler maskelenerek istem üretilir."""
        if not self.enabled:
            return render_fn

        def wrapped(task, inputs, *a, **kw):
            return render_fn(task, self.inputs(inputs), *a, **kw)
        return wrapped

    def verify_quote(self, verify_fn: Callable) -> Callable:
        """`verify_quote(quote, text, ...)` sarmalayıcı: alıntı modelin gördüğü maskeli metne karşı
        denetlenir; dönen `span` özgün metnin konumuna çevrilir (sayfa kesimi vb. bozulmaz)."""
        if not self.enabled:
            return verify_fn

        def wrapped(quote, text, *a, **kw):
            mtext, segs = self.text_with_map(text)
            r = verify_fn(quote, mtext, *a, **kw)
            span = getattr(r, "span", None)
            if span and segs and hasattr(r, "_replace"):
                r = r._replace(span=(self.to_original(span[0], segs), self.to_original(span[1], segs, end=True)))
            return r
        return wrapped

    def inputs(self, inputs: dict) -> dict:
        """İstem girdilerindeki bütün dizeleri (iç içe dict/list dahil) maskeler; `skip_keys`
        (ör. belge kimliği, dosya yolu) olduğu gibi kalır. Girdi sözlüğü değiştirilmez."""
        if not self.enabled:
            return inputs
        return _walk(inputs, self.rules, self.counts, self.skip_keys)


def mask_model_inputs(inputs: dict, ws_root: Path | None = None, *, config: dict | None = None,
                      skip_keys: Iterable[str] = ()) -> tuple[dict, Counter]:
    """Tek çağrılık yardımcı: `privacy.mask_before_model` açıksa maskeli kopya, değilse aynı girdi.
    → (girdiler, tür sayıları)."""
    if config is None:
        config = read_ws_config(Path(ws_root)) if ws_root is not None else {}
    mm = ModelMasker.from_config(config, Path(ws_root) if ws_root is not None else None, skip_keys=skip_keys)
    out = mm.inputs(inputs)
    return out, mm.counts


__all__ = ["ModelMasker", "mask_before_model_enabled", "mask_model_inputs"]
