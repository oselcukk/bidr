"""`bidr init`: çalışma alanı kurulumu (etkileşimli ya da `--answers answers.yaml`).

Çıkış kodları: 0 tamam · 2 geçersiz cevap · 5 var olan kurulum farklı: kullanıcı onayı
gerekir (`--yes` yalnız kullanıcı açıkça kabul ettikten sonra).
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

APPROVAL_EXIT = 5


def template() -> str:
    from .config import available_institutions, available_profiles
    return f"""# bidr init cevapları. Ajan: soruları kullanıcının dilinde sor, cevabı buraya yaz;
# bilmediğin alanı uydurma, kullanıcıya sor. Sonra: bidr init --answers <bu dosya>
calisma_alani: ~/bidr-calisma/birim2025   # çalışma alanı: bidr reposunun ve kaynağın DIŞINDA
kaynak: ~/Belgeler/BIDR-2025              # birimin belge klasörü; salt okunur, hiçbir dosyası değişmez
birim: Örnek Bölümü                       # birimin adı
profil: akademik_bolum                    # birim profili: {', '.join(available_profiles())}
donem: 2025                               # rapor dönemi (değerlendirme yılı)
kurum: null                               # kurum profili: {', '.join(available_institutions()) or '-'}; null = hepsi
gecmis_etiket: false                      # kaynakta geçmiş yılın BİDR raporu ve etiketli kanıt klasörleri var mı
etiket_birim: null                        # (gecmis_etiket) labels --unit; null = birim
egitim: []                                # (isteğe bağlı) etiketli başka çalışma alanları, candidates --train
ajan: null                                # model işini yapan ajan, kayda geçer (ör. claude-code:sonnet)
fakulte: null                             # (isteğe bağlı) birimin fakültesi; null = kurum profilindeki kayıt
ders_kodlari: []                          # (isteğe bağlı) birimin ders kodu önekleri (ör. [MATH, MAT]); boş = kurum profili
hazirlayanlar: []                         # kapaktaki "Raporu Hazırlayanlar" (config.yaml rapor.hazirlayanlar);
                                          # her kişi: {{unvan: …, ad_soyad: …, eposta: …, gorev: …}}; boşsa rapor TASLAK
"""


QUESTIONS = [
    ("calisma_alani", "Çalışma alanı klasörü (repo ve kaynak dışında)", None),
    ("kaynak", "Birimin belge klasörü (salt okunur)", None),
    ("birim", "Birimin adı", None),
    ("profil", "Birim profili", "akademik_bolum"),
    ("donem", "Rapor dönemi (yıl)", None),
    ("kurum", "Kurum profili (boş = hepsi)", ""),
    ("gecmis_etiket", "Kaynakta geçmiş yılın raporu ve etiketli kanıt klasörleri var mı? (e/h)", "h"),
    ("ajan", "Model işini yapan ajanın adı (boş bırakılabilir)", ""),
    ("hazirlayanlar", "Raporu hazırlayanlar, her satıra bir kişi: unvan; ad soyad; e-posta; görev "
                      "(boş satır bitirir)", None),
]


def _ask_preparers(q: str) -> list[dict]:
    print(q + ":")
    out = []
    while True:
        v = input(f"  {len(out) + 1}. ").strip()
        if not v:
            return out
        parts = [x.strip() for x in v.split(";")] + ["", "", "", ""]
        out.append({"unvan": parts[0], "ad_soyad": parts[1], "eposta": parts[2], "gorev": parts[3]})


def _interactive(ws: str | None) -> dict:
    ans: dict = {}
    for k, q, d in QUESTIONS:
        if k == "calisma_alani" and ws:
            continue
        if k == "hazirlayanlar":
            ans[k] = _ask_preparers(q)
            continue
        v = input(f"{q}{f' [{d}]' if d else ''}: ").strip() or (d or "")
        if k == "gecmis_etiket":
            ans[k] = v.lower() in ("e", "evet", "y", "yes", "true", "1")
        elif v != "":
            ans[k] = int(v) if k == "donem" and v.isdigit() else v
    return ans


def _diff(old: dict, new: dict) -> list[str]:
    keys = [k for k in new if k != "surum"] + [k for k in old if k not in new]
    return [f"  {k}: {old.get(k)!r} → {new.get(k)!r}" for k in keys if old.get(k) != new.get(k)]


def _run(args) -> int:
    from . import agentfiles
    from .config import check_preparers, load_rapor, load_section, validate, write_rapor_key, write_section

    if args.sablon:
        print(template(), end="")
        return 0
    if args.answers:
        p = Path(args.answers).expanduser()
        if not p.exists():
            print(f"cevap dosyası yok: {p}", file=sys.stderr)
            return 2
        try:
            answers = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as e:
            print(f"cevap dosyası YAML değil: {e}", file=sys.stderr)
            return 2
    elif sys.stdin.isatty():
        answers = _interactive(args.workspace)
    else:
        print("cevap yok: --answers answers.yaml verin (şablon: bidr init --sablon)", file=sys.stderr)
        return 2
    wsarg = args.workspace or (answers.get("calisma_alani") if isinstance(answers, dict) else None)
    sec, errs = validate(answers, Path(wsarg) if wsarg else None)
    if errs:
        print("Geçersiz cevaplar:", file=sys.stderr)
        for e in errs:
            print(f"  - {e}", file=sys.stderr)
        return 2
    ws = Path(wsarg).expanduser().resolve()
    old = load_section(ws) if ws.exists() else None
    people = None
    if "hazirlayanlar" in answers:            # rapor: bölümüne gider; cevapta yoksa var olan liste korunur
        people = check_preparers(answers["hazirlayanlar"])[0] or []
    if old is not None:
        d = _diff(old, sec)
        prev = load_rapor(ws).get("hazirlayanlar") or []
        if people is not None and prev and prev != people:
            d.append(f"  rapor.hazirlayanlar: {len(prev)} kişi → {len(people)} kişi")
        if d and not args.yes:
            print(f"Bu çalışma alanı zaten kurulu ({ws}/config.yaml) ve cevaplar farklı:")
            print("\n".join(d))
            print("Kullanıcı bu değişikliği onaylarsa aynı komutu --yes ile yeniden çalıştırın. "
                  "(Kaynak değişirse önceki çıktılar eskir; bidr status bunu gösterir.)")
            return APPROVAL_EXIT
    ws.mkdir(parents=True, exist_ok=True)
    write_section(ws, sec)
    if people is not None:
        write_rapor_key(ws, "hazirlayanlar", people)
    notes = agentfiles.write_workspace_files(ws, sec, claude_hook=args.claude_hook)
    print(f"Kuruldu: {ws}/config.yaml ({sec['birim']} · {sec['donem']} · profil {sec['profil']})")
    n = len(load_rapor(ws).get("hazirlayanlar") or [])
    print(f"  raporu hazırlayanlar: {n} kişi" + ("" if n else " (boş: kapak yer tutucuları kalır, rapor TASLAK; "
                                                    "answers.yaml `hazirlayanlar` ile yeniden bidr init)"))
    for n in notes:
        print(f"  {n}")
    from bidr.pipeline.state import bidr_command
    print(f"Sıradaki adım: {bidr_command()} next -w {ws}")
    return 0


def register(sub):
    p = sub.add_parser("init", help="çalışma alanı kurulumu: config.yaml (bidr bölümü), AGENTS.md, skill'ler")
    p.add_argument("--workspace", "-w", help="çalışma alanı (verilmezse cevaplardaki calisma_alani)")
    p.add_argument("--answers", help="cevap dosyası (YAML); şablon: bidr init --sablon")
    p.add_argument("--sablon", action="store_true", help="cevap şablonunu yazdır ve çık")
    p.add_argument("--yes", action="store_true",
                   help="var olan farklı kurulumun üzerine yaz (yalnız kullanıcı onayından sonra)")
    p.add_argument("--claude-hook", action="store_true",
                   help="isteğe bağlı: .claude/settings.json'a oturum başı `bidr status --kisa` hook'u")
    p.set_defaults(func=_run)
