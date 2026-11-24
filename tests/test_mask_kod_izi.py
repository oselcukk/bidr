"""Maskeleme önbelleğinin kod izi yalnız sonucu belirleyen koda bağlı: ilerleme göstergesi, belge dizgesi,
yorum, komut satırı, kaynak kip yönetimi değişince belgeler yeniden maskelenmez; sonuç kodu değişince
maskelenir. Sınıflandırma testle zorlanır (yeni modül ve dışarıdaki koda bağlanan sonuç kodu düşer)."""
from __future__ import annotations

import ast
from pathlib import Path

from bidr.mask import run as R

MASK = Path(R.__file__).parent


def _src(ad: str) -> str:
    return (MASK / f"{ad}.py").read_text(encoding="utf-8")


def test_kod_izi_kararli():
    a = R._kod_izi()
    R._kod_izi.cache_clear()
    assert R._kod_izi() == a and len(a) == 16


def test_ilerleme_belge_dizgesi_yorum_izi_degistirmez():
    s = _src("formats")
    iz = R.modul_izi("formats", s)
    # belge dizgesi, yorum, boş satır
    s2 = s.replace('"""Biçime göre maskeleme', '"""Biçime göre (değişti) maskeleme', 1)
    s2 = s2.replace("\nclass MaskError(RuntimeError):", "\n# yeni yorum\n\nclass MaskError(RuntimeError):", 1)
    assert s2 != s and R.modul_izi("formats", s2) == iz
    # ilerleme (suanki) çağrısı ve içe aktarımı eklemek/çıkarmak
    assert "suanki.sayfa(sn, doc.page_count)" in s
    s3 = s.replace("        suanki.sayfa(sn, doc.page_count)\n", "", 1)
    assert s3 != s and R.modul_izi("formats", s3) == iz
    s4 = s.replace("    for page in doc:\n", "    for page in doc:\n        suanki.asama('yeni')\n", 1)
    assert s4 != s and R.modul_izi("formats", s4) == iz


def test_sonuc_kodu_izi_degistirir():
    s = _src("formats")
    iz = R.modul_izi("formats", s)
    assert 'RAW_KINDS = ("tc_no", "iban", "eposta")' in s
    assert R.modul_izi("formats", s.replace('RAW_KINDS = ("tc_no", "iban", "eposta")',
                                           'RAW_KINDS = ("tc_no", "iban")')) != iz
    r = _src("run")
    iz = R.modul_izi("run", r)
    # run.py: klasör/rapor yönetimi (run, yaz_rapor) dışarıda; mask_and_check içeride
    r2 = r.replace("def yaz_rapor(p: Path, rapor: dict) -> None:\n",
                   "def yaz_rapor(p: Path, rapor: dict) -> None:\n    x = 1\n", 1)
    assert r2 != r and R.modul_izi("run", r2) == iz
    r3 = r.replace("    sha = sha or sha256_file(src)\n    kind = kind or kind_of(src) or \"\"\n",
                   "    sha = sha or sha256_file(src)\n    kind = kind or kind_of(src) or \"x\"\n", 1)
    assert r3 != r and R.modul_izi("run", r3) != iz


def test_her_modul_siniflandirilmis():
    mods = {p.stem for p in MASK.glob("*.py")}
    kod, disi = set(R._KOD_MODULLERI), set(R._KOD_DISI)
    assert not kod & disi
    assert mods == kod | disi, f"sınıflandırılmamış modül: {sorted(mods - kod - disi)}"


def _ic_aktarimlar(tree) -> set[str]:
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.level == 1:
            out |= {a.name for a in n.names} if not n.module else {n.module.split(".")[0]}
    return out


def test_sonuc_kodu_disaridaki_koda_baglanmaz():
    """Sonuç modülleri (ve run.py'nin sonuç fonksiyonları) yalnız sonuç modüllerini ya da yan etkili/depo
    modüllerini (`_YAN_MODULLER`, onbellek) içe aktarır; run.py'nin sonuç fonksiyonları dışarıda bırakılan
    run.py fonksiyonlarını çağırmaz."""
    kod = set(R._KOD_MODULLERI)
    izinli = kod | set(R._YAN_MODULLER) | {"onbellek"}
    for m in R._KOD_MODULLERI:
        tree = ast.parse(_src(m))
        if m == "run":
            govde = [n for n in tree.body if not (isinstance(n, ast.FunctionDef) and n.name in R._RUN_DISI)]
            tree = ast.Module(body=govde, type_ignores=[])
            cagri = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
            disi = R._RUN_DISI - {"_kod_izi", "modul_izi"}           # izin kendisi (anahtarda)
            assert not cagri & disi, cagri & disi
        disari = {x for x in _ic_aktarimlar(tree) if x in R._KOD_DISI and x not in izinli}
        assert not disari, (m, disari)
