import io
P = '/root/ai_infra/demo/starclothing/服装企业AI底座POC指南.html'
with io.open(P, encoding='utf-8') as f:
    lines = f.readlines()

# (start_1based, end_1based_inclusive, img_file, alt, caption_text)
blocks = [
    (249, 277, 'shots/pd1.png', 'PD-1 终端任务执行结果',
     '图 2-1　PD-1 终端任务执行结果（dev-lead 视图：全流程汇总 + 逾期推送 + 缺陷规避要点）'),
    (302, 328, 'shots/pd2.png', 'PD-2 终端任务执行结果',
     '图 2-2　PD-2 终端任务执行结果（fabric-dev 视图：选用建议 + 交期异动预警）'),
    (352, 377, 'shots/pd3.png', 'PD-3 终端任务执行结果',
     '图 2-3　PD-3 终端任务执行结果（qc-lead 视图：评审必查项 + 闭环待办 + RAG 命中）'),
    (402, 428, 'shots/sc1.png', 'SC-1 终端任务执行结果',
     '图 2-4　SC-1 终端任务执行结果（supply-lead 视图：校验结果 + 闭环回写）'),
    (452, 481, 'shots/sc2.png', 'SC-2 终端任务执行结果',
     '图 2-5　SC-2 终端任务执行结果（prod-lead 视图：排程表 + 产线负载瓶颈）'),
    (506, 531, 'shots/sc3.png', 'SC-3 终端任务执行结果',
     '图 2-6　SC-3 终端任务执行结果（finance-lead 视图：三系统跨表对账 + 差异闭环）'),
    (556, 578, 'shots/sc4.png', 'SC-4 终端任务执行结果',
     '图 2-7　SC-4 终端任务执行结果（merch-lead 视图：多供应商比价 + 成本台账建议）'),
]

# replace from last to first so earlier indices stay valid
for start, end, img, alt, cap in sorted(blocks, key=lambda b: -b[0]):
    # sanity: first line of block must contain class="shot avoid-break"
    assert 'shot avoid-break' in lines[start-1], (start, lines[start-1])
    assert lines[end-1].strip() == '</div>', (end, lines[end-1])
    assert 'class="cap"' in lines[end-2] and '图' in lines[end-2], (end, lines[end-2])
    new = [
        '  <img class="realshot" src="%s" alt="%s">\n' % (img, alt),
        '  <div class="cap">%s</div>\n' % cap,
    ]
    lines[start-1:end] = new

with io.open(P, 'w', encoding='utf-8') as f:
    f.writelines(lines)
print('replaced', len(blocks), 'terminal shot blocks with real screenshots')
