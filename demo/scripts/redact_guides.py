#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一次性脱敏脚本（pass-final）：从 git HEAD 原始指南出发，一次性产出"只做 POC 业务介绍、
不支持验证、不含任何访问凭证"的脱敏指南。

设计原则（与客户确认）：
  · 原指南只做 POC 业务介绍，不再支持验证——删除一切"终端访问方式 / §3.8 终端访问信息 /
    附录·访问信息指引"等访问与登录步骤内容；删除 nav、目录中对"附录 / 3.8"的引用。
  · 访问凭证（终端地址 / 归口用户名 / 统一密码）剥离到"一企业一个独立访问页"
    （starclothing-poc-access.html / agileac-poc-access.html），原指南不再以链接形式提及。
  · 保留：企业概况、七大场景方案描述（含截图、场景→选模型→选技能对照表）、管理端配置。
  · 场景叙述 / 图注 / 表格中一律不出现具体归口用户名（pill→删、图注→"归口用户视图"、
    对照表去"登录用户"列、部门行只留部门名、跨智能体交接叙述用角色名）。

输入：git HEAD 中的原始指南（未脱敏版）。脚本用 `git show HEAD:<path>` 读原文，
故可从干净检出复现。带 assert 校验：每条替换的实际命中数必须 == 期望数，不符即抛错不动文件；
末尾再断言无任何敏感 token（统一密码 / terminal/login / 各归口用户名）与 poc-access 引用残留。
"""
import subprocess

REPO = "/root/ai_infra"
STARCLOTHING = "demo/starclothing/服装企业AI底座POC指南.html"
AGILEAC = "demo/agileac/空调企业AI底座POC指南.html"

PW = "12345678"

# ── 星途服装：用户名脱敏（场景叙述/图注/对照表，保留的章节内） ──
SC_USER = [
    ("归口部门 / 用户", "归口部门", 1),
    (" · dev-lead", "", 1),
    (" · fabric-dev", "", 1),
    (" · qc-lead", "", 1),
    (" · supply-lead", "", 1),
    (" · prod-lead", "", 1),
    (" · finance-lead", "", 1),
    (" · merch-lead", "", 1),
    ('<span class="pill gray">dev-lead</span>', "", 1),
    ('<span class="pill gray">fabric-dev</span>', "", 1),
    ('<span class="pill gray">qc-lead</span>', "", 1),
    ('<span class="pill gray">supply-lead</span>', "", 1),
    ('<span class="pill gray">prod-lead</span>', "", 1),
    ('<span class="pill gray">finance-lead</span>', "", 1),
    ('<span class="pill gray">merch-lead</span>', "", 1),
    ("dev-lead 视图", "归口用户视图", 1),
    ("fabric-dev 视图", "归口用户视图", 1),
    ("qc-lead 视图", "归口用户视图", 1),
    ("supply-lead 视图", "归口用户视图", 1),
    ("prod-lead 视图", "归口用户视图", 1),
    ("finance-lead 视图", "归口用户视图", 1),
    ("merch-lead 视图", "归口用户视图", 1),
    # 客户自助验证对照表：去"登录用户"列 + 删用户名 td（supply-lead 处源文件历史缺 </code>，按原样匹配）
    ("<tr><th>场景</th><th>登录用户</th><th>选模型</th><th>选技能</th></tr>",
     "<tr><th>场景</th><th>选模型</th><th>选技能</th></tr>", 1),
    ("<td><code>dev-lead</code></td>", "", 1),
    ("<td><code>fabric-dev</code></td>", "", 1),
    ("<td><code>qc-lead</code></td>", "", 1),
    ("<td><code>supply-lead</td>", "", 1),
    ("<td><code>prod-lead</code></td>", "", 1),
    ("<td><code>finance-lead</code></td>", "", 1),
    ("<td><code>merch-lead</code></td>", "", 1),
    ("<td>开发部 dev-lead</td>", "<td>开发部</td>", 1),
    ("<td>设计部 fabric-dev</td>", "<td>设计部</td>", 1),
    ("<td>品控部 qc-lead</td>", "<td>品控部</td>", 1),
    ("<td>财务部 finance-lead</td>", "<td>财务部</td>", 1),
]

# ── 星途服装：访问 / 验证步骤整块删除（nav、目录、§2 终端访问方式、§3.8、附录） ──
SC_STRIP = [
    ('    <a href="#appendix">附录</a>\n', "", 1),
    ("3.7 分部门安全模型　3.8 终端访问信息</div></li>", "3.7 分部门安全模型</div></li>", 1),
    ('    <li><a href="#appendix">附录：地址与账号一览</a></li>\n', "", 1),
    # 第二章「终端访问方式」callout（含真实地址 + 密码 + 登录步骤）
    ('  <div class="callout key">\n'
     '    <h5>📖 终端访问方式（所有场景通用）</h5>\n'
     '    <div class="kv">\n'
     '      <div class="row"><b>地址：</b><code>https://infra.aievolve.org.cn/starclothing/terminal/login</code></div>\n'
     '      <div class="row"><b>密码：</b><code>12345678</code>（七个归口用户统一密码）</div>\n'
     '    </div>\n'
     '    <div class="row">登录后在「新建任务」中选 <code>glm</code> / <code>smart</code> / <code>balanced</code> 模型别名，粘贴本章各场景的提示词，用 <code>/starclothing-xxx-query</code> 选择技能后提交运行。</div>\n'
     '  </div>\n', "", 1),
    # §3.8 终端访问信息（含真实地址 + 账号 + 密码）
    ('  <h3 class="sub"><span class="n">3.8</span> 终端访问信息</h3>\n'
     '  <div class="callout">\n'
     '    <h5>🖥️ 业务终端（客户可登录自助验证 7 个场景）</h5>\n'
     '    <div class="kv">\n'
     '      <div class="row"><b>地址：</b><code>https://infra.aievolve.org.cn/starclothing/terminal/login</code></div>\n'
     '      <div class="row"><b>账号：</b>见第二章各场景归口用户（dev-lead / fabric-dev / qc-lead / supply-lead / prod-lead / finance-lead / merch-lead）</div>\n'
     '      <div class="row"><b>密码：</b><code>12345678</code></div>\n'
     '    </div>\n'
     '    <div class="row note">管理端（控制台）的访问信息由平台方在 POC 现场单独提供，本指南不对外披露。</div>\n'
     '  </div>\n', "", 1),
    # 附录节：去 id、删标题、删访问表、删验证步骤；仅保留结尾免责 footnote
    ('<section class="page-break" id="appendix">', '<section class="page-break">', 1),
    ('  <h2 class="sec">附录　地址与账号一览</h2>\n', "", 1),
    ('  <table class="data">\n'
     '    <tr><th>类别</th><th>项</th><th>值</th></tr>\n'
     '    <tr><td rowspan="3"><b>业务终端</b></td><td>登录地址</td><td><code>https://infra.aievolve.org.cn/starclothing/terminal/login</code></td></tr>\n'
     '    <tr><td>归口用户</td><td>dev-lead / fabric-dev / qc-lead / supply-lead / prod-lead / finance-lead / merch-lead</td></tr>\n'
     '    <tr><td>密码</td><td><code>12345678</code>（统一）</td></tr>\n'
     '    <tr><td><b>模型</b></td><td>终端任务选模型</td><td><code>glm</code> / <code>smart</code> / <code>balanced</code>（均路由到 glm-5.2）</td></tr>\n'
     '    <tr><td><b>业务系统</b></td><td>PLM/SCM/ERP/MES/CRM 五类模拟（mock）系统</td><td>按归口部门各复制一份、共 13 套（通过接口密钥区分不同客户/租户）</td></tr>\n'
     '    <tr><td><b>管理端</b></td><td>控制台访问</td><td>由平台方现场提供，不在本指南披露</td></tr>\n'
     '  </table>\n', "", 1),
    ('  <div class="callout key">\n'
     '    <h5>📌 POC 验证建议步骤</h5>\n'
     '    <ol style="margin:4px 0; padding-left:20px;">\n'
     '      <li>打开业务终端登录页，用任一归口用户登录（建议先 <code>dev-lead</code> 跑 PD-1）。</li>\n'
     '      <li>新建任务 → 模型选 <code>balanced</code> → 粘贴第二章对应提示词 → 在输入框敲 <code>/</code> 选择要用的技能 → 提交运行。</li>\n'
     '      <li>观察流式输出：会看到 <code>[tool_call]</code> 调用业务系统 → 结构化结果表 → <code>[final]</code> 生成 .docx 报告。</li>\n'
     '      <li>切换其他归口用户重复验证其余场景，体验"分部门只能看本部门资源"。</li>\n'
     '      <li>如需查看管理端配置（模型路由/智能体/工具/监控），联系平台方现场引导。</li>\n'
     '    </ol>\n'
     '  </div>\n', "", 1),
]

# ── 敏睿空调：用户名脱敏 ──
AG_USER = [
    ("归口部门 / 用户", "归口部门", 1),
    (" · rnd-translator", "", 1),
    (" · pm-product", "", 1),
    (" · mfg-planner", "", 1),
    (" · qal-engineer", "", 1),
    (" · scm-buyer", "", 1),
    (" · sal-ops", "", 2),
    (" · svc-engineer", "", 1),
    (" · mkt-specialist", "", 1),
    (" · fin-accountant", "", 1),
    (" · hr-recruiter", "", 1),
    ('<span class="pill gray">rnd-translator</span>', "", 1),
    ('<span class="pill gray">pm-product</span>', "", 1),
    ('<span class="pill gray">mfg-planner</span>', "", 1),
    ('<span class="pill gray">qal-engineer</span>', "", 1),
    ('<span class="pill gray">scm-buyer</span>', "", 1),
    ('<span class="pill gray">sal-ops</span>', "", 2),
    ('<span class="pill gray">svc-engineer</span>', "", 1),
    ('<span class="pill gray">mkt-specialist</span>', "", 1),
    ('<span class="pill gray">fin-accountant</span>', "", 1),
    ('<span class="pill gray">hr-recruiter</span>', "", 1),
    ("rnd-translator 视图", "归口用户视图", 1),
    ("pm-product 视图", "归口用户视图", 1),
    ("mfg-planner 视图", "归口用户视图", 1),
    ("qal-engineer 视图", "归口用户视图", 1),
    ("scm-buyer 视图", "归口用户视图", 1),
    ("sal-ops 视图", "归口用户视图", 2),
    ("svc-engineer 视图", "归口用户视图", 1),
    ("mkt-specialist 视图", "归口用户视图", 1),
    ("fin-accountant 视图", "归口用户视图", 1),
    ("hr-recruiter 视图", "归口用户视图", 1),
    # 场景叙述中的跨智能体交接 / 子任务用户名 → 角色名
    ("切 scm-logistics 验证 scope 隔离", "切物流岗用户验证 scope 隔离", 1),
    ("客诉转 svc-engineer 检测闭环", "客诉转售后工程师检测闭环", 1),
    ("（fin-receivable 子任务）", "（应收子任务）", 1),
    ("培训制度问答（hr-trainer）/ 薪酬报表（hr-compensation）",
     "培训制度问答（培训岗）/ 薪酬报表（薪酬岗）", 1),
    # 客户自助验证对照表：去"登录用户"列 + 删用户名 td
    ("<tr><th>场景</th><th>登录用户</th><th>选模型</th><th>选技能</th><th>绑定智能体</th></tr>",
     "<tr><th>场景</th><th>选模型</th><th>选技能</th><th>绑定智能体</th></tr>", 1),
    ("<td><code>rnd-translator</code></td>", "", 1),
    ("<td><code>pm-product</code></td>", "", 1),
    ("<td><code>mfg-planner</code></td>", "", 1),
    ("<td><code>qal-engineer</code></td>", "", 1),
    ("<td><code>scm-buyer</code></td>", "", 1),
    ("<td><code>sal-ops</code></td>", "", 2),
    ("<td><code>svc-engineer</code></td>", "", 1),
    ("<td><code>mkt-specialist</code></td>", "", 1),
    ("<td><code>fin-accountant</code></td>", "", 1),
    ("<td><code>hr-recruiter</code></td>", "", 1),
    ("<td>研发翻译员（rnd-translator）</td>", "<td>研发翻译员</td>", 1),
    ("<td>售后工程师（svc-engineer）</td>", "<td>售后工程师</td>", 1),
    ("<td>销售运营员（sal-ops）</td>", "<td>销售运营员</td>", 1),
    ("<td>排产计划员（mfg-planner）</td>", "<td>排产计划员</td>", 1),
]

# ── 敏睿空调：访问 / 验证步骤整块删除 + §3.2 内嵌密码删除 ──
AG_STRIP = [
    ('    <a href="#appendix">附录</a>\n', "", 1),
    ("3.7 分级 scope 安全模型　3.8 终端访问信息</div></li>", "3.7 分级 scope 安全模型</div></li>", 1),
    ('    <li><a href="#appendix">附录：地址与账号一览</a></li>\n', "", 1),
    # §3.2 用户管理描述里内嵌的统一密码 → 删（不链接）
    ("（统一密码 <code>12345678</code>）", "", 1),
    # 第二章「终端访问方式」callout
    ('  <div class="callout key">\n'
     '    <h5>📖 终端访问方式（所有场景通用）</h5>\n'
     '    <div class="kv">\n'
     '      <div class="row"><b>地址：</b><code>https://infra.aievolve.org.cn/agileac/terminal/login</code></div>\n'
     '      <div class="row"><b>密码：</b><code>12345678</code>（11 个归口用户统一密码）</div>\n'
     '    </div>\n'
     '    <div class="row">登录后在「新建任务」中模型选 <code>glm-5.2</code>，粘贴本章各场景的提示词，在输入框敲 <code>/</code> 选择要用的技能后提交运行。</div>\n'
     '  </div>\n', "", 1),
    # §3.8 终端访问信息
    ('  <h3 class="sub"><span class="n">3.8</span> 终端访问信息</h3>\n'
     '  <div class="callout">\n'
     '    <h5>🖥️ 业务终端（客户可登录自助验证 11 个场景）</h5>\n'
     '    <div class="kv">\n'
     '      <div class="row"><b>地址：</b><code>https://infra.aievolve.org.cn/agileac/terminal/login</code></div>\n'
     '      <div class="row"><b>账号：</b>见第二章各场景归口用户（rnd-translator / pm-product / mfg-planner / qal-engineer / scm-buyer / sal-ops / svc-engineer / mkt-specialist / fin-accountant / hr-recruiter 等）</div>\n'
     '      <div class="row"><b>密码：</b><code>12345678</code></div>\n'
     '    </div>\n'
     '    <div class="row note">管理端（控制台）的访问信息由平台方在 POC 现场单独提供，本指南不对外披露。</div>\n'
     '  </div>\n', "", 1),
    # 附录节
    ('<section class="page-break" id="appendix">', '<section class="page-break">', 1),
    ('  <h2 class="sec">附录　地址与账号一览</h2>\n', "", 1),
    ('  <table class="data">\n'
     '    <tr><th>类别</th><th>项</th><th>值</th></tr>\n'
     '    <tr><td rowspan="3"><b>业务终端</b></td><td>登录地址</td><td><code>https://infra.aievolve.org.cn/agileac/terminal/login</code></td></tr>\n'
     '    <tr><td>归口用户</td><td>rnd-translator / pm-product / mfg-planner / qal-engineer / scm-buyer / sal-ops / svc-engineer / mkt-specialist / fin-accountant / hr-recruiter / hr-trainer / hr-compensation / scm-logistics / sal-ecom / fin-receivable</td></tr>\n'
     '    <tr><td>密码</td><td><code>12345678</code>（统一）</td></tr>\n'
     '    <tr><td><b>模型</b></td><td>终端任务选模型</td><td><code>glm-5.2</code>（真实模型 id，终端下拉直接列）</td></tr>\n'
     '    <tr><td><b>业务系统</b></td><td>PLM/SCM/ERP/MES/CRM/HRM 六类模拟（mock）系统</td><td>6 套组织级共享（一把 mock API Key 全敏捷租户用），部门级技能绑端点子集</td></tr>\n'
     '    <tr><td><b>管理端</b></td><td>控制台访问</td><td>由平台方现场提供，不在本指南披露</td></tr>\n'
     '  </table>\n', "", 1),
    ('  <div class="callout key">\n'
     '    <h5>📌 POC 验证建议步骤</h5>\n'
     '    <ol style="margin:4px 0; padding-left:20px;">\n'
     '      <li>打开业务终端登录页，用任一归口用户登录（建议先 <code>svc-engineer</code> 跑 SVC-01，或 <code>sal-ops</code> 跑 SAL-02 报销问答）。</li>\n'
     '      <li>新建任务 → 模型选 <code>glm-5.2</code> → 粘贴第二章对应提示词 → 在输入框敲 <code>/</code> 选择要用的技能 → 提交运行。</li>\n'
     '      <li>观察流式输出：会看到 <code>[tool_call]</code> 调用业务系统 → 结构化结果表 → <code>[final]</code> 生成 .docx 报告。</li>\n'
     '      <li>切换其他归口用户重复验证其余场景，体验"分级 scope 只能看本部门资源"。</li>\n'
     '      <li>如需查看管理端配置（模型路由/智能体/工具/监控），联系平台方现场引导。</li>\n'
     '    </ol>\n'
     '  </div>\n', "", 1),
]

SENSITIVE_TOKENS = [
    PW, "terminal/login", "poc-access",
    "dev-lead", "fabric-dev", "qc-lead", "supply-lead", "prod-lead", "finance-lead", "merch-lead",
    "rnd-translator", "pm-product", "mfg-planner", "qal-engineer", "scm-buyer", "sal-ops",
    "svc-engineer", "mkt-specialist", "fin-accountant", "hr-recruiter", "hr-trainer",
    "hr-compensation", "scm-logistics", "sal-ecom", "fin-receivable",
]


def head_original(relpath):
    out = subprocess.check_output(
        ["git", "show", f"HEAD:{relpath}"], cwd=REPO
    )
    return out.decode("utf-8")


def apply(relpath, repls):
    s = head_original(relpath)
    for i, (old, new, exp) in enumerate(repls):
        cnt = s.count(old)
        assert cnt == exp, f"[{relpath}] rule #{i} expected {exp} got {cnt}: {old[:60]!r}"
        s = s.replace(old, new)
    bad = {t: s.count(t) for t in SENSITIVE_TOKENS if s.count(t)}
    assert not bad, f"[{relpath}] leftover sensitive: {bad}"
    abspath = f"{REPO}/{relpath}"
    with open(abspath, "w", encoding="utf-8") as f:
        f.write(s)
    print(f"OK  {relpath}  ({len(repls)} rules all hit, no sensitive/poc-access leftover)")


def main():
    apply(STARCLOTHING, SC_STRIP + SC_USER)
    apply(AGILEAC, AG_STRIP + AG_USER)


if __name__ == "__main__":
    main()
