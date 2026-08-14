import io, re

P = '/root/ai_infra/demo/starclothing/服装企业AI底座POC指南.html'
with io.open(P, encoding='utf-8') as f:
    html = f.read()

NEW_CSS = r"""* { box-sizing: border-box; }
html { scroll-behavior: smooth; -webkit-text-size-adjust: 100%; }
body { font-family:"Noto Sans CJK SC","Noto Sans CJK","Microsoft YaHei","PingFang SC","Segoe UI",sans-serif;
  color:#1f2937; font-size:16px; line-height:1.85; margin:0; background:#eef1f6; -webkit-font-smoothing:antialiased; }
a { color:#1677ff; text-decoration:none; }
code, .mono { font-family:"Noto Sans Mono CJK","JetBrains Mono",Consolas,monospace; font-size:13.5px; background:#eef1f5; padding:1px 6px; border-radius:4px; color:#0f1f3d; }

/* sticky top nav */
.topnav { position:sticky; top:0; z-index:100; background:rgba(255,255,255,.92); backdrop-filter:blur(10px);
  border-bottom:1px solid #e6eaf2; display:flex; align-items:center; gap:18px; padding:10px 28px; }
.topnav .brand { font-weight:700; color:#0f1f3d; font-size:15px; white-space:nowrap; }
.topnav .brand span { color:#1677ff; }
.topnav .links { display:flex; gap:6px; flex-wrap:wrap; }
.topnav .links a { color:#475069; font-size:13.5px; padding:6px 12px; border-radius:6px; }
.topnav .links a:hover { background:#eef4ff; color:#1677ff; }
.topnav .right { margin-left:auto; font-size:12.5px; color:#9aa3b2; }

/* reading column = stacked cards */
section { max-width:900px; margin:0 auto 24px; padding:40px 36px; background:#fff; border-radius:8px;
  box-shadow:0 1px 3px rgba(15,31,61,.06); }
section.cover { max-width:100%; margin:0; border-radius:0; }

/* cover hero */
.cover { position:relative; overflow:hidden; color:#fff;
  background:linear-gradient(135deg,#0b1b3a 0%,#122a5e 45%,#1d4ed8 100%);
  padding:84px 48px 100px; min-height:62vh; display:flex; flex-direction:column; justify-content:center; }
.cover::before { content:""; position:absolute; right:-140px; top:-140px; width:380px; height:380px;
  background:radial-gradient(circle,rgba(99,179,237,.35) 0%,transparent 60%); border-radius:50%; }
.cover::after { content:""; position:absolute; left:-80px; bottom:-120px; width:300px; height:300px;
  background:radial-gradient(circle,rgba(45,212,191,.22) 0%,transparent 60%); border-radius:50%; }
.cover .brand { font-size:14px; letter-spacing:3px; opacity:.82; position:relative; }
.cover h1 { color:#fff; font-size:clamp(34px,6vw,56px); margin:20px 0 8px; letter-spacing:1px; line-height:1.15; position:relative; }
.cover .sub { font-size:clamp(16px,2.5vw,22px); opacity:.92; font-weight:300; position:relative; }
.cover .rule { width:120px; height:3px; background:#38bdf8; margin:20px 0; border-radius:2px; position:relative; }
.cover .tags { position:relative; }
.cover .meta { margin-top:auto; font-size:13px; opacity:.85; line-height:1.9; position:relative; }
.cover .tag { display:inline-block; border:1px solid rgba(255,255,255,.4); border-radius:20px; padding:4px 12px; margin:3px 6px 3px 0; font-size:12px; }

/* toc */
.toc { padding-top:48px; }
.toc h2 { border-bottom:3px solid #1677ff; padding-bottom:10px; margin-top:0; }
.toc ol { list-style:none; padding-left:0; counter-reset:toc; }
.toc > ol > li { margin:14px 0; padding-left:36px; position:relative; font-size:17px; }
.toc > ol > li::before { counter-increment:toc; content:counter(toc); position:absolute; left:0; top:3px;
  width:24px; height:24px; background:#1677ff; color:#fff; border-radius:50%; text-align:center; line-height:24px; font-size:12px; }
.toc > ol > li a { color:#0f1f3d; }
.toc > ol > li a:hover { color:#1677ff; text-decoration:underline; }
.toc .sub { padding-left:0; color:#6b7280; font-size:14px; margin-top:6px; }

/* headings */
h2.sec { font-size:28px; margin:6px 0 20px; padding:8px 0 8px 16px;
  border-left:6px solid #1677ff; background:linear-gradient(90deg,#eef4ff 0%,#fff 96%); border-radius:4px; }
h3.sub { font-size:21px; margin:40px 0 12px; color:#0f1f3d; padding-top:8px; }
h3.sub .n { color:#1677ff; }
h4 { font-size:16px; margin:20px 0 6px; color:#1e3a8a; }
.lead { color:#4b5563; }

/* components */
.card { border:1px solid #e6eaf2; border-radius:10px; padding:18px 20px; margin:16px 0; background:#fff; }
.card.tinted { background:#f8fbff; }
.pill { display:inline-block; font-size:12px; padding:3px 11px; border-radius:12px; margin-right:6px; font-weight:600; }
.pill.blue{background:#e0ecff;color:#1d4ed8;} .pill.green{background:#e6f7ec;color:#15803d;} .pill.gray{background:#eef1f5;color:#475069;}
table.data { width:100%; border-collapse:collapse; margin:16px 0; font-size:14px; background:#fff; overflow:hidden; }
table.data th { background:#0f1f3d; color:#fff; padding:11px 12px; text-align:left; font-weight:600; font-size:13px; }
table.data td { padding:10px 12px; border-bottom:1px solid #eceff4; vertical-align:top; }
table.data tr:nth-child(even) td { background:#f7f9fc; }
.callout { border-left:4px solid #1677ff; background:#f0f6ff; padding:14px 18px; border-radius:0 8px 8px 0; margin:18px 0; }
.callout.warn { border-left-color:#f59e0b; background:#fff8ec; }
.callout.key  { border-left-color:#10b981; background:#ecfdf5; }
.callout h5 { margin:0 0 6px; font-size:15px; color:#0f1f3d; }
.kv { display:flex; gap:12px; flex-wrap:wrap; margin:8px 0; }
.kv .row { font-size:14px; } .kv .row b { color:#0f1f3d; }

.prompt { background:#0b1b3a; color:#e8eefb; border-radius:10px; padding:16px 18px;
  font-family:"Noto Sans Mono CJK",Consolas,monospace; font-size:14px; line-height:1.7; white-space:pre-wrap; position:relative; margin-top:8px; }
.prompt .label { position:absolute; top:-11px; left:14px; background:#1677ff; color:#fff;
  font-family:"Noto Sans CJK SC",sans-serif; font-size:11px; padding:2px 10px; border-radius:10px; }

/* screenshots + panels */
.realshot { width:100%; border:1px solid #d8dee8; border-radius:10px; box-shadow:0 6px 22px rgba(15,31,61,.12); display:block; margin:10px 0 6px; }
.cap { font-size:12.5px; color:#6b7280; text-align:center; margin:0 0 20px; }
.shot { border:1px solid #d8dee8; border-radius:10px; overflow:hidden; margin:18px 0; box-shadow:0 6px 22px rgba(15,31,61,.10); background:#fff; }
.shot .bar { background:#eef1f6; height:34px; display:flex; align-items:center; padding:0 14px; gap:7px; border-bottom:1px solid #e1e6ee; }
.shot .dot { width:12px; height:12px; border-radius:50%; }
.shot .d1{background:#ff5f57;} .shot .d2{background:#febc2e;} .shot .d3{background:#28c840;}
.shot .url { flex:1; background:#fff; border-radius:10px; font-size:11px; color:#6b7280; padding:4px 12px; margin-left:8px; border:1px solid #e1e6ee; overflow:hidden; white-space:nowrap; text-overflow:ellipsis; }
.shot .cap { font-size:12.5px; color:#6b7280; padding:8px 14px; background:#fafbfc; border-top:1px solid #eef1f6; text-align:left; margin:0; }
.shot .topbar { background:#0f1f3d; color:#fff; display:flex; align-items:center; padding:11px 18px; gap:16px; }
.shot .topbar .logo { font-weight:700; font-size:13px; }
.shot .topbar .menu { font-size:12px; opacity:.85; }
.shot .topbar .menu b { color:#7dd3fc; }
.shot .layout { display:flex; }
.shot .side { width:150px; background:#f7f9fc; border-right:1px solid #eef1f6; padding:12px 10px; font-size:12px; color:#475069; flex-shrink:0; }
.shot .side .grp { font-size:10px; color:#9aa3b2; text-transform:uppercase; letter-spacing:1px; margin:10px 4px 4px; }
.shot .side .it { padding:6px 10px; border-radius:6px; margin-bottom:3px; }
.shot .side .it.on { background:#e0ecff; color:#1d4ed8; font-weight:600; }
.shot .main { flex:1; padding:14px 18px; min-width:0; }
.shot .crumb { font-size:12px; color:#9aa3b2; margin-bottom:10px; }
.sse { background:#0b1220; color:#cfe0ff; font-family:"Noto Sans Mono CJK",Consolas,monospace; font-size:13px; line-height:1.7; padding:14px 16px; border-radius:8px; white-space:pre-wrap; overflow-x:auto; }
.sse .ev { color:#7dd3fc; } .sse .ok{color:#34d399;} .sse .warn{color:#fbbf24;} .sse .bad{color:#f87171;} .sse .tk{color:#e8eefb;}
.sse table { width:100%; border-collapse:collapse; margin:8px 0; font-size:12.5px; }
.sse th { background:#1e2a44; color:#cbd5e1; padding:6px 8px; text-align:left; font-weight:600; }
.sse td { padding:5px 8px; border-bottom:1px solid #1e2a44; color:#dbe6ff; }
.antd-tbl { width:100%; border-collapse:collapse; font-size:13px; }
.antd-tbl th { background:#fafbfc; color:#1f2937; border:1px solid #eef1f6; padding:10px 12px; text-align:left; font-weight:600; }
.antd-tbl td { padding:9px 12px; border-bottom:1px solid #f0f2f5; }
.antd-tbl tr:nth-child(even) td { background:#f7f9fc; }
.tag { display:inline-block; font-size:11px; padding:2px 8px; border-radius:4px; border:1px solid; line-height:1.7; }
.tag.blue{color:#1677ff;border-color:#91caff;background:#e6f4ff;}
.tag.green{color:#389e0d;border-color:#b7eb8f;background:#f6ffed;}
.tag.amber{color:#d48806;border-color:#ffe58f;background:#fffbe6;}
.tag.red{color:#cf1322;border-color:#ffa39e;background:#fff1f0;}
.tag.gray{color:#595959;border-color:#d9d9d9;background:#fafafa;}
.tag.purple{color:#531dab;border-color:#d3adf7;background:#f9f0ff;}
.stat-row { display:flex; gap:12px; flex-wrap:wrap; margin:12px 0; }
.stat { flex:1; min-width:120px; background:#fff; border:1px solid #eef1f6; border-radius:10px; padding:14px 16px; }
.stat .v { font-size:24px; font-weight:700; }
.stat .t { font-size:12px; color:#6b7280; margin-top:4px; }
.stat.b{border-top:3px solid #1677ff;} .stat.r{border-top:3px solid #cf1322;}
.stat.g{border-top:3px solid #52c41a;} .stat.a{border-top:3px solid #fa8c16;} .stat.p{border-top:3px solid #722ed1;}
.grid2 { display:grid; grid-template-columns:1fr 1fr; gap:16px; }
.note { font-size:13px; color:#6b7280; }
.sample-note { font-size:12px; color:#9aa3b2; margin:4px 0 6px; }
ul.tight { margin:8px 0 12px; padding-left:22px; } ul.tight li { margin:5px 0; }
.footnote { font-size:12px; color:#9aa3b2; margin-top:12px; }
.flow { display:flex; align-items:center; gap:8px; flex-wrap:wrap; margin:14px 0; }
.flow .node { background:#e0ecff; color:#1d4ed8; border:1px solid #91caff; border-radius:8px; padding:7px 14px; font-size:13px; font-weight:600; }
.flow .node.dark { background:#0f1f3d; color:#fff; border-color:#0f1f3d; }
.flow .arr { color:#9aa3b2; font-size:16px; }

/* back to top */
.totop { position:fixed; right:24px; bottom:24px; width:46px; height:46px; border-radius:50%;
  background:#0f1f3d; color:#fff; border:none; font-size:20px; cursor:pointer; box-shadow:0 6px 18px rgba(0,0,0,.22);
  opacity:0; pointer-events:none; transition:opacity .25s; z-index:90; }
.totop.show { opacity:1; pointer-events:auto; }
.totop:hover { background:#1677ff; }

/* responsive */
@media (max-width:760px) {
  body { font-size:15px; }
  section { padding:24px 18px; margin-bottom:16px; }
  .cover { padding:56px 22px 64px; min-height:50vh; }
  .grid2 { grid-template-columns:1fr; }
  .shot .side { width:108px; font-size:11px; }
  .topnav { padding:8px 14px; gap:10px; flex-wrap:wrap; }
  .topnav .links a { font-size:12px; padding:4px 8px; }
  .topnav .right { display:none; }
  table.data { font-size:12.5px; }
  table.data th, table.data td { padding:8px 8px; }
}
@media print {
  .topnav, .totop { display:none; }
  body { background:#fff; font-size:11pt; }
  section { box-shadow:none; max-width:none; margin:0; border-radius:0; }
  .page-break { page-break-after:always; }
}"""

# 1) replace style block
html = re.sub(r'<style>.*?</style>', '<style>\n' + NEW_CSS + '\n</style>', html, count=1, flags=re.DOTALL)

# 2) insert sticky topnav after <body>
TOPNAV = '''<nav class="topnav">
  <div class="brand">ai<span>infra</span> · 服装企业 AI 底座 POC 指南</div>
  <div class="links">
    <a href="#top">首页</a>
    <a href="#toc">目录</a>
    <a href="#ch1">企业概况</a>
    <a href="#ch2">七大场景</a>
    <a href="#ch3">管理端</a>
    <a href="#appendix">附录</a>
  </div>
  <div class="right">星途服装 × ai_infra · 2026-07</div>
</nav>
'''
html = html.replace('<body>', '<body>\n' + TOPNAV, 1)

# 3) add ids to sections
html = html.replace('<section class="cover">', '<section class="cover" id="top">', 1)
html = html.replace('<section class="toc page-break">', '<section class="toc page-break" id="toc">', 1)
html = html.replace('<section>\n  <h2 class="sec">第一章', '<section id="ch1">\n  <h2 class="sec">第一章', 1)
html = html.replace('<section class="page-break">\n  <h2 class="sec">第二章', '<section class="page-break" id="ch2">\n  <h2 class="sec">第二章', 1)
html = html.replace('<section class="page-break">\n  <h2 class="sec">第三章', '<section class="page-break" id="ch3">\n  <h2 class="sec">第三章', 1)
html = html.replace('<section class="page-break">\n  <h2 class="sec">附录', '<section class="page-break" id="appendix">\n  <h2 class="sec">附录', 1)

# 4) make TOC main items clickable
toc_anchors = [
    ('服装企业基本情况与业务痛点', 'ch1'),
    ('七大场景的 AI 解决方案', 'ch2'),
    ('AI 底座管理端配置', 'ch3'),
    ('附录：地址与账号一览', 'appendix'),
]
for title, anchor in toc_anchors:
    html = html.replace('<li>' + title, '<li><a href="#' + anchor + '">' + title + '</a>', 1)

# 5) back-to-top button + script before </body>
TOTOP = '''<button class="totop" id="totop" onclick="window.scrollTo({top:0,behavior:'smooth'})" title="返回顶部">↑</button>
<script>
(function(){
  var b=document.getElementById('totop');
  function on(){ if(window.scrollY>400){b.classList.add('show')}else{b.classList.remove('show')} }
  window.addEventListener('scroll',on,{passive:true}); on();
})();
</script>
'''
html = html.replace('</body>', TOTOP + '</body>', 1)

with io.open(P, 'w', encoding='utf-8') as f:
    f.write(html)
print('web-optimized HTML written:', P)
print('len=', len(html))
