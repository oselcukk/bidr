"""Kanıt ihtiyaç raporu (`bidr ihtiyac`): bir çalışma alanında neyin eksik olduğunu, hangi belgenin
raporu en çok güçlendireceğini ve geçen yılın iyi kanıtlarının bu yılki karşılığı olup olmadığını
mevcut çıktılardan (decisions, inceleme kararları, audit) kodla çıkarır. Model çağrısı yok.

Hatırlatma/öncelik aracıdır, kesin kontrol listesi değildir. Hat aşaması değildir: çalışma alanının
dosyalarını salt okur; çıktıları (`ihtiyac.xlsx`, `ihtiyac.md`, isteğe bağlı `report-ic.docx`)
`--out` klasörüne (varsayılan çalışma alanı) yazar. Ayrıntı: docs/IHTIYAC.md.
"""
