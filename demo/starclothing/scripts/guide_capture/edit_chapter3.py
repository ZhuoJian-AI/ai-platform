import io, re
P = '/root/ai_infra/demo/starclothing/服装企业AI底座POC指南.html'
with io.open(P, encoding='utf-8') as f:
    t = f.read()

REMOVES = [
    '''  <h4>管理员管理（仅超管）</h4>
  <p>新建管理员：用户名 + 显示名 + 角色 + 初始密码（首次登录强制改密）；用户名非邮箱，同组织内不可同名、不同组织可同名，平台级账号全局唯一。可编辑显示名/角色、重置密码、停用/启用、删除（不可删除自己）。组织管理员登录地址为 <code>{域名}/{组织 slug}/login</code>。</p>
  <img class="realshot" src="shots/mgmt/org-admins.png" alt="管理员管理页">
  <div class="cap">图 3-3　管理员管理（仅超管可见）</div>
''',
    '''  <h4>联系方式</h4>
  <p>维护组织对外联系信息与二维码图片（管理员鉴权上传），在组织门户登录页等对外位置展示。</p>
  <img class="realshot" src="shots/mgmt/org-contact.png" alt="联系方式页">
  <div class="cap">图 3-4　联系方式</div>
''',
    '''  <h4>智能体配置 / 测试广场 / Judge 模板（二期，菜单暂隐藏）</h4>
  <p>智能体配置：系统提示词 + 模型（真实 id 或 default 走默认路由）+ 绑定工作空间/RAG/判官/技能 + 记忆 + 推理参数。测试广场：选智能体发消息流式回复、右侧执行轨迹展示各步骤、运行历史看状态/Token/耗时。Judge 模板：可复用评分模板（定义评分维度与权重，可被多智能体引用）。此三项为二期内容，菜单暂隐藏。</p>
''',
]
for blk in REMOVES:
    assert blk in t, 'block not found:\n' + blk[:60]
    t = t.replace(blk, '', 1)

# renumber chapter-3 figure captions sequentially (图 3-N　) in document order
counter = [0]
def renum(m):
    counter[0] += 1
    return '图 3-%d　' % counter[0]
t = re.sub(r'图 3-\d+　', renum, t)

with io.open(P, 'w', encoding='utf-8') as f:
    f.write(t)
print('removed 3 blocks; renumbered', counter[0], 'chapter-3 figures')
