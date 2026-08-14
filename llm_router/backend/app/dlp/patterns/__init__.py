"""DLP 内置模式库汇总。"""

from app.dlp.patterns.files import ALL_FILE_RULES
from app.dlp.patterns.financial import ALL_FINANCIAL_RULES
from app.dlp.patterns.medical import ALL_MEDICAL_RULES
from app.dlp.patterns.pii import ALL_PII_RULES

ALL_BUILTIN_RULES = (
    ALL_PII_RULES
    + ALL_FINANCIAL_RULES
    + ALL_MEDICAL_RULES
    + ALL_FILE_RULES
)
