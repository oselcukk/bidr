# audit: ölçüt OD'si, eksik kanıt raporu, inceleme tablosu

`bidr audit -w WS [--profile P] [--out DIR]` · `bidr audit apply -w WS [--out DIR]`

Belirleyici aşama (model yok). Girdi: `decisions.jsonl` (yalnız ince aşamada **kabul
edilmiş** eşleşmeler: alıntısı kodla doğrulanmış), `documents.jsonl` (tür, dönem içi,
çalışma adı), ölçütler ve yuva etiketleri (`slot-tags-yokak-2025.yaml`). Çalışma alanını
yalnız okur; çıktılar `--out` klasörüne (varsayılan çalışma alanı):

| Dosya | İçerik |
|---|---|
| `review.xlsx` | Sayfa 1 "Eşleşmeler": satır = kabul edilmiş eşleşme; sayfa 2 "Ölçüt özeti"; "Açıklama"; gizli `_meta` |
| `gaps.md` | OD dağılımı, öncelikli eksikler, kurum geneli uyarıları, ölçüt ölçüt zincir ve boş yuvalar |
| `audit-olcutler.json` | Ölçüt özetlerinin makine okunur hali (render aşaması için) |
| `review-decisions.jsonl` | `apply`: kullanıcı kararları (satır başına bir kayıt) |
| `slot-tags-oneri.yaml` | `apply`: yuva etiketi onay/düzeltme ÖNERİLERİ; etiket dosyasını değiştirmez |

## OD bir ölçüt özelliğidir

Belge OD taşımaz; her eşleşme ölçütün PUKÖ zincirinde bir **halkayı** kanıtlar. Halkalar ve
düzeyler (rubrik 2-5 ile, `slots.STAGE_OD` ile aynı):

| Düzey | Gereken halkalar |
|---|---|
| OD2 | planla (P) |
| OD3 | + uygula (U) |
| OD4 | + kontrol_et (K) **ve** onlem_al (Ö) — ikisi birden |
| OD5 | + ozgun (Z) |

Önerilen OD = 2'den başlayarak **kesintisiz** sağlanan en yüksek düzey; hiçbiri yoksa OD1.
Zincir eksikse düşük düzey: P+U+K (Ö yok) → OD3; P+U+Z (K/Ö yok) → OD3.

Bir düzey şu durumda sağlanır: o düzeyin her halkası kanıtlı ya da ölçütte o halkaya ait
yuva yok (**yuvasız**), ve o düzeyde ya da üstünde en az bir halka kanıtlı. Böylece:

- A.1.2 gibi plan/uygulama yuvası olmayan ölçütte K+Ö → OD4 (alt halkalar aranmaz);
- B.2.3 gibi kontrol/önlem yuvası olmayan ölçütte P+U → OD3; OD4 kendiliğinden gelmez,
  gaps.md "şablonda yuvası yok; ölçüt açıklamasına uygun belge gerekir" der.

Tek yumuşatma: plan halkası eksik ama U/K/Ö var → OD2 (uygulama planın örtük kanıtı) ve
"plan belgesi yok" notu; OD3 için yine plan belgesi gerekir.

## Halkayı ne sayar (eşleşme → sayılan aşama)

1. **Kod OD'si esas:** decide `od_kabul`'u düşürdüyse (aşama yuva etiketine uymuyor ya da
   model daha düşük OD dedi) aşama da düşer: OD3 → uygula, OD2 → planla, OD4 → kontrol_et
   (temkinli; önlem açık kanıt ister).
2. **Kurum geneli düzenleme** (`yonetmelik`, `yonerge`, `senato_karari` türleri,
   `rules.KURUM_GENELI_TURLER`): kanıt ilkesi `kurum_geneli_duzenleme` gereği yalnız planla.
   Daha yüksek aşama denmişse planla'ya iner, `uygulama_kaniti_eksik` işaretlenir; ölçütte
   bu belgeler dışında uygulama kanıtı yoksa gaps.md'de ayrı listelenir.
3. **Dönem dışı belge** (`documents.jsonl` `donem_ici: false`): planla sayılır (düzenleme
   yıllar boyu geçerlidir), daha üst aşama sayılmaz (`donem_disi`). Bilinmeyen dönem sayılır.
4. **Düşük güven** (`guven: dusuk`): önerilen OD'ye katılmaz; ayrıca "OD (düşük güven
   dahil)" hesaplanır ve fark varsa not düşülür. Bu, OD'yi doğrulanmamış eşleşmeyle şişirmemek
   içindir.
5. **İnsan kararı** (`review-decisions.jsonl`): `ret` sayılmaz; `duzelt` kullanıcının
   ölçüt/yuva/aşamasını kullanır (kurum geneli ve dönem sınırları uygulanmaz: karar kullanıcının).

## Eksikler (gaps.md)

Her ölçüt için bir üst düzeye çıkmak için eksik halkalar, o halkaya etiketli yuvaların
metinleri ("OD4 için şu tür belge gerekiyor") ve boş yuvalar (hiç sayılan eşleşmesi olmayan
kanıt yuvaları; dipnotlar hariç). Öncelik sırası:

1. kanıt var ama OD ≤ 2 (uygulama ya da plan halkası eksik, kurum geneli-yalnız dahil):
   en ucuz yükseltme, hakemin ilk soracağı;
2. hiç kanıt yok (OD1);
3. OD3: kontrol/önlem eksik;
4. OD4: özgün eksik.

Grup içinde boş yuva sayısı çok olan önce.

## review.xlsx

"Eşleşmeler" sütunları: satır kimliği (`<doc_id>|<yuva>`), belge çalışma adı, tür, dönem içi,
ölçüt, yuva ve metni, model aşaması, sayılan aşama, sayılan OD, yuva etiketi (aşama → OD) ve
durumu (öneri/onaylı), vurgu, güven, işaretler, alıntı, gerekçe; kullanıcı sütunları
(mavi): **KARAR** (kabul/ret/duzelt), düzelt: ölçüt/yuva/aşama, yuva etiketi kararı
(onayla/duzelt) ve yeni aşama(lar), NOT.

Vurgular: OD4/OD5'e yükselten satırın OD/etiket hücreleri turuncu; yükselten etiket hâlâ
öneri ise koyu turuncu ve "ÖNERİ etiket" yazar. Düşük güven sarı. Sayılmayan satırlar gri.
Sütunlar başlık adıyla okunur; kullanıcı sütun ekleyip sırayı değiştirebilir.

`bidr audit` yeniden çalıştırılınca işlenmiş kararlar (`review-decisions.jsonl`) tabloya geri
yazılır; tabloda olup işlenmemiş kararlar da kaybolmaz (yeni tabloya taşınır, eski tablo
`review.onceki.xlsx`).

## apply

Tabloyu okur, her satırın kararını doğrular (geçersiz karar: çıkış 1, satır kayda girmez),
`review-decisions.jsonl`'i yazar, `gaps.md` ve `audit-olcutler.json`'u kararlarla yeniden
hesaplar (tabloyu yeniden yazmaz). Yuva etiketi kararları `slot-tags-oneri.yaml`'a toplanır:
yuva, mevcut etiket, önerilen aşama/OD (`durum: onayli`), kaynak satırlar; aynı yuvaya
çelişen öneriler `celiskiler`'e. Paket verisi (`bidr/data/criteria/`) değişmez; öneriyi
işlemek kullanıcı onayıyla ayrı bir adımdır.

## Tamamlanma şartı (`audit_tamam`)

review.xlsx var ve güncel `decisions.jsonl`'den üretilmiş (`_meta.kararlar_sha`); her satırın
geçerli kararı var; tablodaki her karar `review-decisions.jsonl`'de birebir. Aşama
`onay: insan`: kararı ajan vermez.
