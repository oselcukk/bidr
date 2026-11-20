"""YÖKAK/BİDR ölçüt şeması: veri modeli ve yükleyici.

Veri: `data/criteria/yokak-2025.yaml` (üretici: `bidr.criteria.extract_docx`).
"""
from .loader import load_criteria, load_guide, load_ornek_uygulamalar, validate
from .model import Area, CriteriaSet, Criterion, EvidenceSlot, SubCriterion

__all__ = ["load_criteria", "load_guide", "load_ornek_uygulamalar", "validate",
           "Area", "CriteriaSet", "Criterion", "EvidenceSlot", "SubCriterion"]
