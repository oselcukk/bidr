# AGENTS.md

Bu repo, BİDR (Birim İç Değerlendirme Raporu) için kanıt hattıdır. Mimari:
`docs/ARCHITECTURE.md`.

## Kurallar (her ajan için)

- Dosya adı ve klasör adı belgenin ne olduğuna dair kanıt sayılmaz; içerik okunur.
- Kaynak klasör salt okunurdur. Hiçbir dosya taşınmaz, silinmez, değiştirilmez.
- Gerçek belge, kişi adı, e-posta repoya yazılmaz. Testler sentetik veriyle.
- Kaynakta olmayan şey yazılmaz; emin olunmayan alan boş bırakılır.
- Ara çıktılar `_tmp/` (git dışı) veya çalışma klasörüne.

## Geliştirme

```
uv venv && uv pip install -e '.[dev]'
.venv/bin/pytest -q
```

(Ajan modunda rapor üretim oyun kitabı v0.2'de eklenecek.)
