"""İsteğe bağlı kişisel veri modülü (K8/K26): yayın kopyası maskeleme (`bidr maskele`) ve
model öncesi maskeleme (`privacy.mask_before_model`). Ana akışı beklemez; bkz. docs/PRIVACY.md."""
from .detect import KINDS, PLACEHOLDERS, Finding, MaskRules, detect, iban_valid, mask_text, tc_valid

__all__ = ["KINDS", "PLACEHOLDERS", "Finding", "MaskRules", "detect", "iban_valid", "mask_text", "tc_valid"]
