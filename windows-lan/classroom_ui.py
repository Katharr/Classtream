"""Chinese classroom presentation layer for the pinned upstream 1.0.1 UI.

Only interface literals are translated; classroom names, messages, filenames,
protocol keys and persisted data retain their original values.
"""
import re


TEXT = {
    'PyStream': 'Classtream · 云课堂',
    'PyStream — Live Screen Share': '云课堂 · 屏幕共享',
    'No Session Link': '课堂尚未开始',
    'Ask your teacher for the current session link to join the stream.': '请等待老师创建课堂，然后刷新此页面。',
    'Session Expired': '课堂已更新',
    'This link is no longer valid. Ask your teacher for the new session link.': '老师已创建新的课堂，点击“重新进入”即可加入。',
    'Removed from Session': '你已离开课堂',
    'The host has removed you from this session.': '老师已将你移出本次课堂。如需继续上课，请联系老师。',
    'Host Disconnected': '老师暂时离线',
    "The host has ended the session. Click below to check if they've come back online.": '请等待老师重新上线，然后点击下方按钮继续观看。',
    'Retry Connection': '重新连接', '👑 Admin Login': '教师登录',
    'Username': '教师账号', 'Password': '密码', 'Enter password…': '请输入教师密码',
    'Login as Admin': '进入教师工作台',
    '🔗 New Session Created': '课堂已创建', 'Share this link with your students:': '把下方地址发给学生，即可加入课堂。',
    'Copy Link': '复制上课地址', 'Close': '关闭', 'Loading…': '正在准备课堂…',
    'Toggle sidebar (B)': '课堂面板（B）', 'Toggle chat (C)': '课堂讨论（C）',
    'ADMIN': '教师', 'LIVE': '课堂进行中', 'Viewers online': '当前在线人数（含教师）',
    'Monitors': '共享屏幕', 'Admin Controls': '课堂管理',
    'Your display name': '教师姓名', 'Display name…': '输入教师姓名', 'Save': '保存姓名',
    'Session': '课堂名称', 'Session name…': '例如：信息技术 · 第三课',
    'New Link': '创建新课堂', 'No active session': '尚未创建课堂',
    'Screen Access': '共享权限', '🔒 Private All Screens': '暂时隐藏所有屏幕',
    'Voice Chat': '语音交流', 'Microphone (Input)': '麦克风', 'Default Microphone': '默认麦克风',
    'Speakers (Output)': '扬声器', 'Default Speakers': '默认扬声器',
    '🔇 You have been muted by the admin': '老师已关闭你的麦克风',
    'Connect Voice': '连接语音', '🎙 Mute': '关闭麦克风',
    'Stream Quality': '画面设置', 'JPEG Quality': '画面清晰度',
    'Low bandwidth': '更流畅', 'Crisp': '更清晰', 'Options': '显示选项', 'Show cursor': '显示老师的鼠标',
    'Viewers Online': '课堂成员', 'No viewers yet': '等待同学加入',
    'Live Stats': '连接详情', 'FPS': '帧率', 'Viewers': '在线人数', 'Shortcuts': '键盘快捷键',
    'Pause / Resume': '暂停 / 继续', 'Fullscreen': '全屏观看', 'Screenshot': '保存截图',
    'Zoom In / Out': '放大 / 缩小', 'Reset Zoom': '还原大小', 'Sidebar': '课堂面板', 'Chat': '课堂讨论',
    'Push to Talk (hold)': '按住发言', 'Drag to resize sidebar': '拖动调整面板宽度',
    'Screen stream': '老师共享的屏幕', 'Screen is Private': '老师暂时隐藏了屏幕',
    'The host has made this screen private.': '老师恢复共享后，点击“重新查看”继续观看。',
    'Connecting to stream…': '正在连接老师的屏幕…', 'Drag to resize chat': '拖动调整讨论区宽度',
    'Group Chat': '课堂讨论', 'Cancel reply': '取消回复', 'Code Snippet': '分享代码',
    'Plain text': '纯文本', 'Paste or type code here…   Tab = 4 spaces  ·  Ctrl+Enter = send': '在这里输入或粘贴代码，按 Ctrl+Enter 发送',
    'Send Snippet': '发送代码', 'Emoji picker': '选择表情',
    'Attach file (.py .zip .mp4 .png …)': '发送文件（代码、图片、文档等，最大 50 MB）',
    'Share code snippet': '分享代码', 'Message everyone… (Shift+↵ for newline)': '向老师或同学提问…',
    'Send (Enter)': '发送消息（Enter）', 'Pause/Resume (Space)': '暂停或继续画面（空格）',
    'Pause': '暂停画面', 'Zoom In (+)': '放大画面（+）', 'Zoom Out (-)': '缩小画面（-）',
    'Zoom In': '放大', 'Zoom Out': '缩小', 'Reset zoom (0)': '还原画面大小（0）',
    'Save screenshot (S)': '保存截图（S）', 'Fullscreen (F)': '全屏观看（F）',
    'Push to Talk — hold V key or hold button': '按住 V 键或此按钮发言', 'Talk': '按住发言',
    '● Connected': '● 已连接',
}


def _swap(source, old, new):
    if source.count(old) != 1:
        raise RuntimeError('Unsupported classroom UI anchor: ' + old[:70])
    return source.replace(old, new, 1)


def _focus_layout(template):
    """Keep upstream bindings while giving the shared screen the whole stage."""
    def button(button_id):
        return re.search(rf'<button\b[^>]*\bid="{button_id}".*?</button>', template, re.S)[0]

    logo = re.search(r'<div id="logo".*?</div>', template, re.S)[0]
    logo = re.sub(r'</svg>.*?</div>', '</svg></div>', logo, flags=re.S)
    viewer = re.search(r'<div class="badge" id="viewer-badge".*?</div>', template, re.S)[0]
    viewer = viewer.replace('<div ', '<button type="button" ', 1).replace('</div>', '</button>')
    viewer = viewer.replace('title="当前在线人数（含教师）"',
                            'title="查看课堂成员" aria-controls="sidebar" aria-expanded="false"')
    chat = button('chat-toggle-btn').replace('icon-btn', 'btn').replace('课堂讨论</span>', '讨论</span>')
    sidebar_toggle = button('sidebar-toggle-btn').replace('id="sidebar-toggle-btn"',
                                                         'id="sidebar-toggle-btn" hidden')
    identity = button('identity-btn')
    # Replace only the topbar region, leaving every upstream binding target once.
    start = template.index('<div id="topbar">')
    end = template.index('<!-- ═', start)
    template = template[:start] + f'''<header id="topbar">
  {logo}
  <div class="classroom-heading"><button id="classroom-menu-btn" class="icon-btn" aria-expanded="false" aria-controls="classroom-menu" aria-label="课堂菜单">
    <span id="classroom-title">正在准备课堂…</span><span aria-hidden="true">⌄</span>
  </button></div>
  <span id="session-name" hidden>正在准备课堂…</span>
  <span id="host-topbar-badge" hidden>教师</span><span id="live-badge" hidden></span>
  <div class="classroom-top-actions">
    {viewer}
    <button id="classroom-invite-btn" class="icon-btn teacher-only" aria-label="复制学生上课地址"><span aria-hidden="true">↗</span><span>邀请学生</span></button>
    <button id="classroom-settings-btn" class="icon-btn" aria-controls="sidebar" aria-expanded="false" aria-label="课堂设置"><span aria-hidden="true">⚙</span><span>设置</span></button>
    <span id="classroom-student-identity"></span>
  </div>
  {sidebar_toggle}
</header>
<div id="classroom-menu" class="classroom-popover" role="region" aria-label="课堂菜单" hidden>
  <div class="classroom-menu-heading">当前课堂</div><div id="classroom-menu-name"></div>
  <button id="classroom-room-btn" class="icon-btn teacher-only">课堂管理</button>
  <button id="classroom-new-btn" class="icon-btn teacher-only">创建新课堂</button>
  <button id="classroom-menu-members" class="icon-btn">查看课堂成员</button>
  {identity}
</div>
''' + template[end:]
    template = _swap(template, '<aside id="sidebar" aria-label="课堂面板">', '''<aside id="sidebar" class="collapsed" data-panel="settings" aria-label="课堂设置" inert>
    <div class="classroom-drawer-heading"><h2 id="classroom-drawer-title">课堂设置</h2><button id="classroom-sidebar-close" class="icon-btn" aria-label="关闭课堂面板">×</button></div>''')
    template = template.replace('<details class="advanced-settings teacher-only"><summary>更多设置</summary>',
                                '<div class="advanced-settings">')
    template = re.sub(r'</details>(\s*</aside>)', r'</div>\1', template, count=1)
    template = template.replace('class="s-section" id="host-panel"', 'class="s-section teacher-only" id="host-panel"')
    template = template.replace('<div class="s-section"><div class="s-label">教师信息',
                                '<div class="s-section teacher-only"><div class="s-label">教师信息')
    template = template.replace('<div class="s-section">\n      <div class="s-label">显示选项',
                                '<div class="s-section teacher-only">\n      <div class="s-label">显示选项')
    template = _swap(template, '    <!-- Viewer list -->\n    <div class="s-section">',
                     '''    <!-- Viewer list -->
    <div class="s-section sidebar-members">
      <button id="classroom-member-manage" class="host-btn teacher-only">发言权限管理</button>''')
    template = re.sub(r'      <header class="stage-heading">.*?</header>', '', template, count=1, flags=re.S)
    template = re.sub(r'<footer class="stage-footer">.*?</footer>',
                      '<footer class="stage-footer"><span id="stage-status" role="status">正在连接</span></footer>',
                      template, count=1, flags=re.S)
    template = _swap(template, '<div class="chat-header">',
                     '<div class="chat-header"><button id="classroom-chat-close" class="icon-btn" aria-label="关闭课堂讨论">×</button>')
    # Keep all three zoom actions visible together in the dock.
    zoom = '\n'.join(button(name) for name in ('btn-zoom-in', 'btn-zoom-out', 'btn-zoom-reset'))
    for name in ('btn-zoom-in', 'btn-zoom-out', 'btn-zoom-reset'):
        template = template.replace(button(name), '')
    zoom = zoom.replace('>1:1</button>', '>适应窗口</button>')
    template = _swap(template, '</div><!-- /bottombar -->', f'''
  <div class="classroom-zoom-controls" role="group" aria-label="画面缩放">{zoom}</div>
  {chat}
  <button id="classroom-more-btn" class="btn" aria-controls="sidebar" aria-expanded="false">更多</button>
</div><!-- /bottombar -->''')
    conn = re.search(r'<span id="conn-state".*?</span>', template, re.S)[0]
    template = template.replace(conn, '')
    template = _swap(template, '<span id="stage-status" role="status">正在连接</span>',
                     '<span id="stage-status" role="status">正在连接</span>' + conn)
    fps = re.search(r'<div id="fps-bar">.*?</div>', template, re.S)[0]
    template = template.replace(fps, '')
    template = _swap(template, '<div class="advanced-settings">',
                     '<div class="advanced-settings">' + fps.replace('<div id="fps-bar">', '<div id="fps-bar" hidden>'))
    template = template.replace('</svg>全屏观看', '</svg><span>全屏</span>')
    template = template.replace('</svg>保存截图', '</svg><span>截图</span>')
    return template


def render_template(template):
    """Retain upstream IDs and behavior, regroup controls around classroom tasks."""
    template = template.replace('lang="en"', 'lang="zh-CN"')
    template = re.sub(r'<div id="name-modal".*?(?=<!-- ═)', '', template, flags=re.S)
    # Run after the transport adapter has replaced the image with a canvas.
    template = re.sub(r'>([^<>]+)<', lambda m: '>' + (
        m[1].replace(m[1].strip(), TEXT[m[1].strip()]) if m[1].strip() in TEXT else m[1]) + '<', template)
    template = re.sub(r'(title|placeholder|alt|aria-label)="([^"]*)"',
                      lambda m: m[1] + '="' + TEXT.get(m[2], m[2]) + '"', template)
    template = _swap(template, '</head>', '''<link rel="stylesheet" href="/classroom-ui/classroom.css">
<script>document.documentElement.dataset.role=new URLSearchParams(location.search).has('host')?'teacher':'student';</script>
</head>''')
    template = _swap(template, '<div id="sidebar">', '<aside id="sidebar" aria-label="课堂面板">')
    template = _swap(template, '</div><!-- /sidebar -->', '</aside><!-- /sidebar -->')
    # Put creating/sharing a classroom first for teachers.
    start = template.index('    <!-- Monitors -->')
    end = template.index('    <!-- Screen access control')
    sections = template[start:end]
    split = sections.index('    <!-- Admin host panel')
    template = template[:start] + sections[split:] + sections[:split] + template[end:]
    # Keep upstream binding targets inert while removing duplicate sharing panels.
    template = template.replace('<div id="monitor-list">', '<div id="monitor-list" hidden>')
    template = template.replace('    <!-- Monitors -->\n    <div class="s-section">',
                                '    <!-- Monitors -->\n    <div class="s-section" hidden>')
    template = template.replace('id="screen-access-panel"', 'id="screen-access-panel" hidden')
    start = template.index('      <!-- Display name -->')
    end = template.index('      <!-- Session link generation -->')
    profile = template[start:end]
    template = template[:start] + template[end:]
    template = template.replace('<div class="s-section">\n      <div class="s-label">画面设置',
                                '<div class="s-section teacher-only">\n      <div class="s-label">画面设置')
    # Preserve quality/cursor/stats IDs while removing the controls from the student flow.
    start = template.index('    <!-- Stream quality -->')
    end = template.index('    <!-- Viewer list -->')
    settings = template[start:end]
    template = template[:start] + template[end:]
    start = template.index('    <!-- Live stats -->')
    end = template.index('  </aside>')
    advanced = template[start:end]
    template = template[:start] + '''<details class="advanced-settings teacher-only"><summary>更多设置</summary><div class="s-section"><div class="s-label">教师信息</div>''' + profile + '</div>' + settings + advanced + '</details>\n' + template[end:]
    template = _swap(template, '<div id="screen-area">', '''<section id="stage" aria-label="课堂画面">
      <header class="stage-heading"><div><div class="eyebrow">课堂画面</div><h1>老师的屏幕</h1></div><span id="stage-status">正在连接</span></header>
      <div id="screen-area">''')
    template = _swap(template, '    <!-- Drag handle between screen and chat panel -->', '''      <footer class="stage-footer"><span>跟随老师的演示，问题随时在讨论区提出</span><span>画面太小？试试全屏观看</span></footer>
    </section>
    <!-- Drag handle between screen and chat panel -->''')
    template = template.replace('<div class="chat-footer-hint">**bold** &nbsp;*italic*&nbsp; `code`&nbsp; ~~strike~~&nbsp; [text](url)</div>',
                                '<div class="chat-footer-hint">Enter 发送 · Shift+Enter 换行</div>')
    template = template.replace('**md**', '排版').replace('FPS: ', '帧率：').replace('Quality: ', '清晰度：')
    for overlay, label in [('no-session-overlay', '刷新课堂'), ('session-expired-overlay', '重新进入')]:
        pattern = rf'(<div id="{overlay}".*?</p>)'
        template = re.sub(pattern, lambda m: m[1] + f'<button class="rejoin-btn" onclick="location.href=\'/class\'">{label}</button>', template, count=1, flags=re.S)
    template = _swap(template, '    <span id="chat-unread-badge">', '    <span>课堂讨论</span><span id="chat-unread-badge">')
    template = _swap(template, '  <div id="logo">', '  <div id="logo" aria-label="云课堂">')
    template = _swap(template, '  <div class="badge" id="live-badge">', '  <button id="identity-btn" class="identity-btn" title="课堂昵称">课堂昵称</button>\n  <div class="badge" id="live-badge">')
    template = template.replace('<span id="viewer-count">0</span>', '<span id="viewer-count">0</span><span>人在线</span>')
    template = template.replace('id="conn-state" style="color:var(--green)">● 已连接', 'id="conn-state" style="color:var(--text-dim)">● 正在连接')
    fullscreen = re.search(r'  <button class="btn" id="btn-fullscreen".*?</button>', template, re.S)[0]
    template = template.replace(fullscreen, '')
    template = re.sub(r'(<button class="btn" id="btn-pause".*?</button>)',
                      lambda m: m[1] + '\n' + fullscreen, template, count=1, flags=re.S)
    template = _focus_layout(template)
    template = _swap(template, '<script type="module" src="/static/js/main.js"></script>',
                     '<script type="module" src="/static/js/main.js"></script>\n<script type="module" src="/classroom-ui/classroom.js"></script>\n<script type="module" src="/classroom-ui/screen-pan.js"></script>')
    return template


LITERALS = {
    'Resume': '继续观看', 'Pause': '暂停画面', 'Python Live Session': '我的课堂',
    'No active session': '尚未创建课堂', '✓ Copied!': '✓ 已复制', 'Copy Link': '复制上课地址', 'Copy': '复制',
    'Apply': '确认选择', 'No students connected yet': '等待同学加入',
    'Wrong password': '密码不正确，请重新输入', 'Server error — check console': '连接失败，请检查网络后重试',
    '● Connected': '● 已连接', '● Disconnected': '● 连接已断开',
    'Connecting…': '正在连接老师的屏幕…', 'Reconnecting…': '连接中断，正在自动重连…',
    'Check Access': '重新查看', 'Check': '重新查看', 'Grid': '全部', 'You': '我',
    'Remove from session': '移出课堂', 'React': '添加表情', 'Reply': '回复',
    'Copy text': '复制文字', 'Delete': '删除消息', 'Upload failed': '文件发送失败，请重试',
    'Smileys': '表情', 'Gestures': '手势', 'Hearts': '爱心', 'Objects': '物品',
    'Muted by admin': '老师已关闭你的麦克风', 'Push to Talk — hold V key or button': '按住 V 键或按钮发言',
    '🔇 Unmute': '开启麦克风', '🎙 Mute': '关闭麦克风',
    'Unmute participant': '允许该同学发言', 'Force mute participant': '关闭该同学的麦克风',
    'Disconnect': '断开语音', 'Connect Voice': '连接语音', 'Talking…': '正在发言…', 'Talk': '按住发言',
}


def localize_script(name, source):
    # Exact quoted literals and HTML text only. Never translate incoming content.
    for old, new in LITERALS.items():
        for quote in ("'", '"'):
            source = source.replace(quote + old + quote, quote + new + quote)
    fragments = {
        '>No viewers yet<': '>等待同学加入<', '>👑 Host<': '>教师<', '>You<': '>我<',
        '>👁 All Students<': '>全体同学<', '>🔒 Private<': '>仅教师可见<', '>👤 Specific…<': '>指定同学…<',
        '>Private<': '>老师暂时隐藏了屏幕<', '>↓ Download<': '>↓ 下载<', '>System Default<': '>系统默认<',
        'Double-click to focus': '双击放大此屏幕', 'dbl-click to focus': '双击放大',
        'Remove "${name}" from the session?': '确定将“${name}”移出课堂吗？',
        'Microphone ${i + 1}': '麦克风 ${i + 1}', 'Speaker ${i + 1}': '扬声器 ${i + 1}',
    }
    for old, new in fragments.items():
        source = source.replace(old, new)
    if name in ('auth.js', 'chat.js'):
        source = "import { explainError } from '/classroom-ui/classroom-errors.js';\n" + source
        source = source.replace("d.reason || '密码不正确，请重新输入'", "explainError(d.reason, '密码不正确，请重新输入')")
        source = source.replace("data?.reason || '文件发送失败，请重试'", "explainError(data?.reason, '文件发送失败，请重试')")
    if name == 'controls.js':
        source = source.replace("    if (['INPUT', 'TEXTAREA'].includes(e.target.tagName)) return;",
                                "    if (e.ctrlKey || e.metaKey || e.altKey || e.target.isContentEditable ||\n        ['INPUT', 'TEXTAREA', 'SELECT', 'BUTTON', 'SUMMARY'].includes(e.target.tagName)) return;")
    if name == 'sidebar.js':
        source = source.replace("  monitors.forEach(m => {", "  monitors.forEach(m => {\n    m.label = m.id === 0 ? '全部屏幕' : `屏幕 ${m.id}`;")
        source = source.replace("export async function generateNewSession() {", """export async function generateNewSession() {
  if (/^https?:/.test(document.getElementById('current-session-link').textContent.trim()) &&
      !confirm('创建新课堂会使当前课堂失效，学生需要重新进入。确定继续吗？')) return;""")
    return source
