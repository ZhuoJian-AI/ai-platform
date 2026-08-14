"""DLP 内置模式库 — 文件附件。

匹配请求中携带的办公文档附件。信号来源：
1. 文件名扩展名：.xls[xmb]? / .doc[x]? / .doc / .ppt[x]? / .ppt / .pdf
2. MIME 类型：application/vnd.ms-* 与 application/vnd.openxmlformats-officedocument.* 与 application/pdf

注：DLP 引擎只扫描纯文本，附件的二进制内容不会被扫描。代理层在
``_extract_text_from_messages`` 中会将 document/file 块的 ``media_type`` 与
``filename`` 投影到待扫描文本里，本规则才能命中真实附件。
默认动作 ``warn``（仅识别不拦截），管理员可在 DLP 规则页改为 ``block`` 强制拦截。
"""

# Excel 附件（文件名扩展名或 MIME 类型）
EXCEL_ATTACHMENT = {
    "name": "Excel附件",
    "rule_type": "regex",
    # 引擎以 IGNORECASE 编译，扩展名与 MIME 均大小写不敏感
    "pattern": r"\.xls[xmb]?\b|application/vnd\.(?:ms-excel|openxmlformats-officedocument\.spreadsheetml\.sheet)",
    "severity": "medium",
    "action": "warn",
    "direction": "request",
}

# Word 附件（文件名扩展名或 MIME 类型）
WORD_ATTACHMENT = {
    "name": "Word附件",
    "rule_type": "regex",
    "pattern": (
        r"\.doc[x]?\b|application/vnd\.(?:ms-word|openxmlformats-officedocument\.wordprocessingml\.document)"
    ),
    "severity": "medium",
    "action": "warn",
    "direction": "request",
}

# PowerPoint 附件（文件名扩展名或 MIME 类型）
PPT_ATTACHMENT = {
    "name": "PPT附件",
    "rule_type": "regex",
    "pattern": (
        r"\.ppt[x]?\b|application/vnd\.(?:ms-powerpoint|openxmlformats-officedocument\.presentationml\.presentation)"
    ),
    "severity": "medium",
    "action": "warn",
    "direction": "request",
}

# PDF 附件（文件名扩展名或 MIME 类型）
PDF_ATTACHMENT = {
    "name": "PDF附件",
    "rule_type": "regex",
    "pattern": r"\.pdf\b|application/pdf",
    "severity": "medium",
    "action": "warn",
    "direction": "request",
}

ALL_FILE_RULES = [EXCEL_ATTACHMENT, WORD_ATTACHMENT, PPT_ATTACHMENT, PDF_ATTACHMENT]
