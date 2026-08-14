"""DLP 内置模式库 — PII 个人信息。"""

# 中国身份证号 (18位)
CHINESE_ID_CARD = {
    "name": "中国身份证号",
    "rule_type": "regex",
    "pattern": r"[1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx]",
    "severity": "critical",
    "action": "block",
    "direction": "both",
}

# 护照号码 (通用格式)
PASSPORT_NUMBER = {
    "name": "护照号码",
    "rule_type": "regex",
    "pattern": r"\b[A-PR-WY][A-Z0-9]\d{6,9}\b|\b[EK]\d{8,9}\b|\b[GECP]\d{8}\b",
    "severity": "high",
    "action": "redact",
    "direction": "both",
}

# 手机号 (中国 + 国际)
PHONE_NUMBER = {
    "name": "手机号码",
    "rule_type": "regex",
    "pattern": r"(?:\+?86[-.\s]?)?1[3-9]\d{9}|\+?1[-.\s]?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}",
    "severity": "high",
    "action": "redact",
    "direction": "both",
}

# 电子邮箱
EMAIL_ADDRESS = {
    "name": "电子邮箱",
    "rule_type": "regex",
    "pattern": r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
    "severity": "medium",
    "action": "redact",
    "direction": "both",
}

ALL_PII_RULES = [CHINESE_ID_CARD, PASSPORT_NUMBER, PHONE_NUMBER, EMAIL_ADDRESS]
