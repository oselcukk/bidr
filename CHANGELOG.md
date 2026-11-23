# Değişiklikler

Her birleştirmede (main'e giren her değişiklik) buraya en üste bir satır eklenir: tarih, kısa
açıklama ve kullanıcıyı ilgilendiriyorsa ne yapması gerektiği. `bidr guncelle` güncellemeden sonra
bu dosyanın yeni satırlarını gösterir. Bu dosyadan önceki geçmiş için `git log`.

- 2026-11-23: `bidr guncel` / `bidr guncelle` eklendi; `bidr next` günde bir kez yeni sürümü
  hatırlatır (`BIDR_GUNCEL_DENETIM=0` kapatır). Ajanlar oturum başında `bidr guncel` çalıştırır.
