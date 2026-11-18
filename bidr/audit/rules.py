"""Ölçüt düzeyinde OD kuralları (model yok). Gerekçe ve örnekler: `docs/AUDIT.md`.

OD bir belgenin değil ölçütün özelliğidir. Her kabul edilmiş eşleşme ölçütün PUKÖ
zincirinde bir halkayı (aşama) kanıtlar; önerilen OD zincirin kesintisiz kurulduğu en
yüksek düzeydir:

    düzey 2  planla
    düzey 3  uygula
    düzey 4  kontrol_et VE onlem_al (ikisi birden)
    düzey 5  ozgun

Bir düzey, o düzeyin bütün halkaları ya kanıtlıysa ya da ölçütte o halkaya ait yuva
yoksa (`yuvasiz`) ve o düzeyde ya da üstünde en az bir halka kanıtlıysa sağlanır.
OD = 2'den başlayarak kesintisiz sağlanan en yüksek düzey; hiçbiri yoksa 1.
Tek yumuşatma (komisyon kararı, 2026-11-18): plan halkası eksik ama üst halkalar
varsa düzey 2 örtük sağlanır (uygulama tanımlı bir sürecin kanıtıdır), zincir
yukarı devam eder ve ölçüt "plan belgesi önerilir" diye işaretlenir.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from bidr.criteria.slots import STAGE_OD

LINKS = ("planla", "uygula", "kontrol_et", "onlem_al", "ozgun")
LEVELS = {2: ("planla",), 3: ("uygula",), 4: ("kontrol_et", "onlem_al"), 5: ("ozgun",)}
OD_STAGE = {2: "planla", 3: "uygula", 4: "kontrol_et", 5: "ozgun"}   # OD düşürülünce en temkinli aşama
KISA = {"planla": "P", "uygula": "U", "kontrol_et": "K", "onlem_al": "Ö", "ozgun": "Z"}

# Kurum (üniversite) geneli düzenleme türleri: kanıt ilkesi `kurum_geneli_duzenleme` gereği
# yalnız "planla" sayılır; bölümün uygulaması ayrı belge ister.
KURUM_GENELI_TURLER = frozenset({"yonetmelik", "yonerge", "senato_karari"})

# Eksik halka için "şu tür belge gerekiyor" metni (yuva metinleri ayrıca listelenir).
GEREKEN = {
    "planla": "tanımlı süreç/plan belgesi (bölüm ya da birim düzeyinde usul-esas, iş akışı, "
              "komisyon görev tanımı, politika metni)",
    "uygula": "bölümün dönem içindeki uygulama kanıtı (kurul/komisyon kararı, tutanak, liste, "
              "ilan, ders/öğrenci kaydı); kurum geneli yönetmelik/yönerge yetmez",
    "kontrol_et": "izleme/ölçme sonucu (anket sonucu, değerlendirme raporu, gösterge izleme tablosu, "
                  "toplantıda sonuçların görüşülmesi)",
    "onlem_al": "izleme sonucuna dayanan iyileştirme (sonuca atıf yapan karar, değişiklik, eylem planı)",
    "ozgun": "birime özgü, sürdürülebilir ve örnek gösterilebilir uygulama kanıtı",
}


def effective_stage(asama: str | None, od: int | None) -> str | None:
    """Kodun kabul ettiği OD (`od_kabul`) ile tutarlı aşama. decide OD'yi düşürdüyse
    aşama da düşer (ör. kontrol_et ama od 3 → uygula)."""
    if od is None:
        return None
    if asama in STAGE_OD and STAGE_OD[asama] == od:
        return asama
    return OD_STAGE.get(od)


@dataclass
class ChainResult:
    od: int
    duzeyler: dict[int, str]            # düzey → sağlandı | ortuk | eksik | yuvasiz_kanitsiz
    eksik: list[str]                    # sonraki düzey için eksik halkalar
    sonraki: int | None                 # bir üst düzey (5'te None)
    ortuk_plan: bool = False
    notlar: list[str] = field(default_factory=list)


def criterion_od(present: set[str], has_slot: set[str]) -> ChainResult:
    """`present`: kanıtlı halkalar; `has_slot`: ölçütte yuvası olan halkalar
    (belirsiz yuva her halkayı karşılayabilir: çağıran ekler)."""
    def ok_link(x: str) -> bool:
        return x in present or x not in has_slot

    def any_at_or_above(lv: int) -> bool:
        return any(x in present for L, xs in LEVELS.items() if L >= lv for x in xs)

    od, durum, ortuk = 1, {}, False
    for lv in (2, 3, 4, 5):
        links = LEVELS[lv]
        if all(ok_link(x) for x in links) and any_at_or_above(lv):
            durum[lv] = "saglandi"
        elif lv == 2 and any_at_or_above(3):
            durum[lv], ortuk = "ortuk", True    # plan belgesi yok: örtük sağlanır, zincir sürer
        else:
            durum[lv] = "eksik"
            break
        od = lv
    nxt = od + 1 if od < 5 else None
    eksik: list[str] = []
    if nxt:
        eksik = [x for x in LEVELS[nxt] if x not in present and x in has_slot]
        if not eksik and not any(x in has_slot for x in LEVELS[nxt]):
            eksik = list(LEVELS[nxt])     # yuva yok ama kanıt yine de gerekir
    return ChainResult(od, durum, eksik, nxt, ortuk)
