"""Classroom discussion permissions for the pinned upstream application."""
import json

from fastapi import Request
from fastapi.responses import JSONResponse

from app import state
from stream_transport import StreamManager


class DiscussionManager(StreamManager):
    def __init__(self):
        super().__init__()
        self.discussion_all_muted = False
        self.discussion_muted = set()

    def moderation(self, ws):
        sid = self._ws_session.get(id(ws))
        teacher = bool(state.admin_tokens.get(ws.query_params.get('admin_token', '')))
        return dict(type='chat:moderation', all_muted=self.discussion_all_muted,
                    muted=not teacher and (self.discussion_all_muted or sid in self.discussion_muted),
                    individually_muted=not teacher and sid in self.discussion_muted,
                    muted_viewer_ids=[self._viewer_id[s] for s in self.discussion_muted
                                      if s in self._viewer_id] if teacher else [])

    async def push_moderation(self):
        for peer in list(self.peers.values()):
            peer.enqueue_control(json.dumps(self.moderation(peer.ws)))

    def register_viewer(self, ws, session_id, name, role='guest'):
        super().register_viewer(ws, session_id, name, role)
        peer = self.peers.get(id(ws))
        if peer:
            peer.enqueue_control(json.dumps(self.moderation(ws)))

    async def connect(self, ws, monitor_id):
        await super().connect(ws, monitor_id)
        receive = ws.receive
        # Bind registration to this connection's identity. A muted student cannot
        # re-register as another student or as the teacher on an existing socket.
        registered_sid = ws.query_params.get('session_id', '')[:64]
        teacher = bool(state.admin_tokens.get(ws.query_params.get('admin_token', '')))

        async def moderated_receive():
            nonlocal registered_sid
            while True:
                message = await receive()
                try:
                    data = json.loads(message.get('text') or 'null')
                except ValueError:
                    return message
                if not isinstance(data, dict):
                    return message
                if data.get('type') == 'register' and not teacher:
                    sid = str(data.get('session_id', ''))[:64]
                    if not sid or (registered_sid and sid != registered_sid):
                        continue
                    if self._session_role.get(sid) == 'host':
                        continue
                    registered_sid = sid
                if data.get('type') in ('chat:send', 'chat:react') and self.moderation(ws)['muted']:
                    await ws.send_text(json.dumps(dict(self.moderation(ws), type='chat:blocked')))
                    continue
                return message

        ws.receive = moderated_receive


def install_discussion(application, local_teacher):
    @application.get('/api/discussion')
    async def get_discussion(request: Request):
        if not local_teacher(request):
            return JSONResponse({'ok': False}, status_code=401)
        manager = state.manager
        return JSONResponse(dict(ok=True, all_muted=manager.discussion_all_muted,
                                 muted_viewer_ids=[manager._viewer_id[s] for s in manager.discussion_muted
                                                   if s in manager._viewer_id]))

    @application.post('/api/discussion')
    async def set_discussion(request: Request):
        if not local_teacher(request):
            return JSONResponse({'ok': False}, status_code=401)
        try:
            data = await request.json()
        except ValueError:
            data = None
        if (not isinstance(data, dict) or type(data.get('muted')) is not bool
                or data.get('scope') not in ('all', 'student')):
            return JSONResponse({'ok': False, 'reason': '无效的禁言设置'}, status_code=400)
        manager = state.manager
        if data['scope'] == 'all':
            manager.discussion_all_muted = data['muted']
        else:
            viewer_id = data.get('viewer_id')
            sid = manager.get_session_id_by_viewer_id(viewer_id) if type(viewer_id) is int else None
            if not sid or manager._session_role.get(sid) == 'host':
                return JSONResponse({'ok': False, 'reason': '该学员已离线，请刷新后重试'}, status_code=404)
            if data['muted']:
                manager.discussion_muted.add(sid)
            else:
                manager.discussion_muted.discard(sid)
        await manager.push_moderation()
        return await get_discussion(request)

    @application.post('/api/session/new')
    async def new_classroom(request: Request):
        from app.routers.api import new_session
        result = await new_session(request, request.headers.get('x-admin-token'))
        if result.status_code == 200:
            state.manager.discussion_all_muted = False
            state.manager.discussion_muted.clear()
            await state.manager.push_moderation()
        return result


def adapt_discussion_scripts(scripts):
    def swap(name, old, new):
        if scripts[name].count(old) != 1:
            raise RuntimeError('Unsupported discussion UI anchor: ' + name + ': ' + old)
        scripts[name] = scripts[name].replace(old, new, 1)

    scripts['main.js'] = "import { initDiscussion } from '/classroom-ui/discussion.js';\n" + scripts['main.js']
    swap('main.js', '  initChat();', '  initDiscussion();\n  initChat();\n  toggleChat();')
    scripts['viewers.js'] = "import { handleModeration, renderDiscussionMembers } from '/classroom-ui/discussion.js';\n" + scripts['viewers.js']
    swap('viewers.js', "  if (data.type?.startsWith('chat:'))", "  if (handleModeration(data)) return;\n  if (data.type?.startsWith('chat:'))")
    swap('viewers.js', '  _renderViewerList(list);', '  _renderViewerList(list);\n  renderDiscussionMembers();')
    scripts['chat.js'] = "import { discussionAllowed, refreshDiscussionInputs } from '/classroom-ui/discussion.js';\n" + scripts['chat.js']
    for anchor in ('export function sendMessage() {', 'async function _uploadAndSend(file) {', 'function _sendCodeSnippet() {'):
        swap('chat.js', anchor, anchor + '\n  if (!discussionAllowed()) return;')
    swap('chat.js', '  sendBtn.disabled = false;', '  sendBtn.disabled = false;\n  refreshDiscussionInputs();')
    # Check permission again when an upload finishes during a mute change.
    swap('chat.js', "  const input = document.getElementById('chat-input');\n  const text  = input.value.trim();\n  sendChatMsg({",
         "  if (!discussionAllowed()) return;\n  const input = document.getElementById('chat-input');\n  const text  = input.value.trim();\n  sendChatMsg({")
