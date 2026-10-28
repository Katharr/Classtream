/** CS2 JPEG rectangle receiver. RFB-style framebuffer + completed-batch ACK.
 * Reuses the existing stream module's authentication, controls and reconnects.
 */
import { state } from './state.js';

// Keep connection checks with the receiver: a live socket is not a live picture.
function showHealth(ws, phase, text) {
  if (state.wsMap[ws._screenKey] !== ws) return;
  Object.assign(ws._health, { phase, text });
  if (phase !== 'live') ws._health.healthySince = null;
  const cell = ws._cell;
  if (cell) {
    let label = cell.querySelector('.stream-health');
    if (!label) {
      label = document.createElement('div'); label.className = 'stream-health';
      label.style.cssText = 'position:absolute;left:10px;top:38px;padding:4px 8px;background:#181c25dd;color:white;border-radius:4px;z-index:2';
      label.setAttribute('role', 'status'); cell.appendChild(label);
    }
    label.textContent = text; label.hidden = phase === 'live';
  }
  const rank = { live: 0, paused: 1, frozen: 1, waiting: 2, source: 3, lagging: 4, interrupted: 5, reconnecting: 6, ended: 7 };
  const health = Object.values(state.wsMap).map(w => w._health).filter(Boolean)
    .reduce((a, b) => (rank[b.phase] ?? 7) > (rank[a.phase] ?? 7) ? b : a, ws._health);
  const conn = document.getElementById('conn-state');
  conn.dataset.phase = health.phase; conn.dataset.message = health.text;
  conn.style.color = health.phase === 'live' ? 'var(--green)' :
    ['waiting', 'paused', 'frozen'].includes(health.phase) ? 'var(--text-dim)' : 'var(--red)';
  conn.textContent = '● ' + health.text;
  const overlay = document.getElementById('stream-overlay');
  // In a grid each cell reports its own fault, so healthy screens stay visible.
  overlay.classList.toggle('hidden', state.currentMode === 'grid' || ['live', 'paused', 'frozen'].includes(health.phase));
  document.getElementById('overlay-msg').textContent = health.text;
}

export function closeScreen(ws) {
  if (!ws) return;
  ws._dead = true;
  ws._cleanup?.();
  ws.close();
}

export function connectScreen(url, key, canvas, handlers) {
  const previous = state.wsMap[key];
  const attempts = previous?._retryCount || 0;
  closeScreen(previous);
  const ws = new WebSocket(url);
  ws.binaryType = 'blob'; ws._screenKey = key; ws._cell = handlers.cell;
  ws._retryCount = attempts;
  state.wsMap[key] = ws;
  const started = performance.now();
  ws._health = { phase: 'waiting', text: '正在等待老师的画面…', lastMeta: started,
    lastProgress: started, epoch: 0, seq: 0, painted: false, meta: null, healthySince: null };
  const current = () => state.wsMap[key] === ws && canvas.isConnected &&
    state.currentMode === (key === 'single' ? 'single' : 'grid');
  let watchdog, retryTimer;
  function cleanup() {
    clearInterval(watchdog); clearTimeout(retryTimer);
    document.removeEventListener('visibilitychange', visible);
    window.removeEventListener('classtream-pause', check);
    ws._disposeFrameReceiver?.();
  }
  ws._cleanup = cleanup;
  function retry() {
    clearTimeout(retryTimer);
    ws._retryCount += 1;
    const delay = Math.min(15000, 1000 * 2 ** Math.min(ws._retryCount - 1, 4)) * (.8 + Math.random() * .4);
    retryTimer = setTimeout(() => {
      if (current()) handlers.reconnect();
    }, delay);
  }
  function recover(text) {
    if (!current() || ws._dead) return;
    closeScreen(ws);
    showHealth(ws, 'reconnecting', text || '画面中断，正在自动重连…');
    retry();
  }
  function check() {
    if (!current() || ws._dead || document.hidden) return;
    const h = ws._health, now = performance.now(), silent = now - h.lastMeta;
    if (silent >= 5000) { recover(); return; }
    if (silent >= 3000) { showHealth(ws, 'interrupted', '画面中断，正在检测连接…'); return; }
    const meta = h.meta;
    if (meta && (meta.capture_age_ms === null || meta.capture_age_ms + silent >= 3000)) {
      h.lastProgress = now;
      showHealth(ws, 'source', '教师画面暂不可用，请等待老师恢复'); return;
    }
    if (state.paused) {
      h.lastProgress = now; showHealth(ws, 'paused', '画面已暂停 · 可继续观看'); return;
    }
    if (meta?.frozen && state.myRole !== 'host') {
      h.lastProgress = now; showHealth(ws, 'frozen', '教师已冻结画面'); return;
    }
    const ahead = meta && (meta.stream_epoch !== h.epoch || meta.stream_seq > h.seq);
    if ((!h.painted || ahead) && now - h.lastProgress >= 5000) {
      recover('画面未能跟上，正在重新获取最新画面…'); return;
    }
    if (ahead && now - h.lastProgress >= 3000) {
      showHealth(ws, 'lagging', '画面暂时落后，正在恢复…'); return;
    }
    if (!h.painted) { showHealth(ws, 'waiting', '正在等待老师的画面…'); return; }
    showHealth(ws, 'live', '已连接');
    h.healthySince ??= now;
    if (now - h.healthySince >= 10000) ws._retryCount = 0;
  }
  function visible() {
    if (!document.hidden) {
      // Background timer throttling must not count as a broken connection.
      ws._health.lastMeta = ws._health.lastProgress = performance.now();
      check();
    }
  }
  const receive = createFrameReceiver(ws, canvas, handlers.frame);
  window.addEventListener('classtream-pause', check);
  document.addEventListener('visibilitychange', visible);
  watchdog = setInterval(check, 250);
  ws._frameApplied = (epoch, seq, painted) => {
    const h = ws._health;
    h.epoch = epoch; h.seq = seq; h.painted ||= painted;
    h.lastProgress = performance.now();
    check();
  };
  ws.onopen = () => { if (current() && !ws._dead) handlers.register(ws); };
  ws.onclose = () => {
    if (ws._dead) return;
    cleanup(); ws._dead = true;
    if (!current()) return;
    showHealth(ws, 'reconnecting', '画面中断，正在自动重连…'); retry();
  };
  ws.onmessage = event => {
    if (!current() || ws._dead) return;
    if (typeof event.data !== 'string') { receive(event.data); return; }
    let data;
    try { data = JSON.parse(event.data); } catch { recover('连接数据异常，正在重连…'); return; }
    if (data.type === 'meta') {
      ws._health.lastMeta = performance.now(); ws._health.meta = data; check();
    }
    if (['private', 'error', 'kicked'].includes(data.type)) {
      closeScreen(ws);
      const text = data.type === 'private' ? '老师暂时隐藏了屏幕' : data.type === 'kicked' ? '你已离开课堂' :
        data.reason === 'refresh_required' ? '版本已更新，请刷新进入课堂' :
        data.reason === 'invalid_session' ? '课堂已更新，请重新进入' :
        data.reason === 'host_disconnected' ? '老师暂时离线' : '画面连接已结束，请重新进入课堂';
      showHealth(ws, 'ended', text);
      if (data.type === 'private') {
        handlers.private(data, () => { if (current()) handlers.reconnect(); });
        if (['global', 'global_private'].includes(data.reason)) retry();
      }
    }
    handlers.message(data);
  };
  showHealth(ws, 'waiting', '正在等待老师的画面…');
  return ws;
}

async function decodeImage(blob) {
  if (typeof createImageBitmap === 'function') return createImageBitmap(blob);
  const url = URL.createObjectURL(blob);
  try {
    const img = new Image();
    const ready = new Promise((resolve, reject) => { img.onload = resolve; img.onerror = reject; });
    img.src = url;
    await ready;
    return img;
  } finally { URL.revokeObjectURL(url); }
}

export function createFrameReceiver(ws, canvas, onFrame) {
  const base = document.createElement('canvas');
  let epoch = 0, seq = 0, cursor = [0, 0, false], busy = false;
  const active = () => !ws._dead && ws.readyState === WebSocket.OPEN && canvas.isConnected;
  function paint() {
    if (!active() || state.paused || !epoch) return;
    if (canvas.width !== base.width || canvas.height !== base.height) {
      canvas.width = base.width; canvas.height = base.height;
    }
    const ctx = canvas.getContext('2d');
    ctx.drawImage(base, 0, 0);
    if (cursor[2]) {
      const [x, y] = cursor;
      // Match the upstream capture module's existing teaching pointer.
      ctx.save(); ctx.translate(x, y); ctx.beginPath();
      ctx.moveTo(0, 0); ctx.lineTo(0, 22); ctx.lineTo(8, 15);
      ctx.lineTo(13, 22); ctx.lineTo(17, 19); ctx.lineTo(11, 13);
      ctx.lineTo(13, 0); ctx.closePath();
      ctx.fillStyle = 'white'; ctx.strokeStyle = '#1e1e1e'; ctx.lineWidth = 1;
      ctx.fill(); ctx.stroke(); ctx.restore();
    }
    onFrame();
    ws._frameApplied?.(epoch, seq, true);
  }
  window.addEventListener('classtream-pause', paint);
  const dispose = () => {
    window.removeEventListener('classtream-pause', paint);
    base.width = base.height = 0;
  };
  ws._disposeFrameReceiver = dispose;
  ws.addEventListener('close', dispose, { once: true });
  return async function receiveFrame(blob) {
    if (!active()) return;
    if (busy) { ws.close(1002, 'Overlapping screen batches'); return; }
    busy = true;
    const decoded = [];
    try {
      const buffer = await blob.arrayBuffer();
      const bytes = new Uint8Array(buffer);
      if (bytes.length < 8 || bytes[0] !== 67 || bytes[1] !== 83 || bytes[2] !== 50 || bytes[3] !== 0)
        throw new Error('Unsupported screen packet');
      const length = new DataView(buffer).getUint32(4);
      if (length > 65536 || 8 + length > bytes.length) throw new Error('Invalid screen header');
      const header = JSON.parse(new TextDecoder().decode(bytes.subarray(8, 8 + length)));
      if (!Number.isInteger(header.width) || !Number.isInteger(header.height) ||
          header.width < 1 || header.width > 8192 || header.height < 1 || header.height > 8192 ||
          !Array.isArray(header.patches) || header.patches.length > 4096)
        throw new Error('Invalid screen dimensions');
      if (!header.key && (header.epoch !== epoch || header.width !== base.width || header.height !== base.height)) {
        ws.send(JSON.stringify({ type: 'stream:resync' }));
        return;
      }
      if (header.epoch === epoch && header.seq <= seq) throw new Error('Out of order screen batch');
      let offset = 8 + length;
      for (const patch of header.patches) {
        const [x, y, width, height, size] = patch;
        if (![x, y, width, height, size].every(Number.isInteger) || x < 0 || y < 0 ||
            width < 1 || height < 1 || x + width > header.width || y + height > header.height ||
            size < 1 || offset + size > bytes.length) throw new Error('Invalid rectangle');
        const img = await decodeImage(new Blob([bytes.subarray(offset, offset + size)], { type: 'image/jpeg' }));
        decoded.push({ img, x, y, width, height });
        if (img.width !== width || img.height !== height) throw new Error('Invalid decoded rectangle');
        offset += size;
      }
      if (offset !== bytes.length) throw new Error('Unexpected rectangle bytes');
      if (!active()) return;
      if (header.key) { base.width = header.width; base.height = header.height; }
      const ctx = base.getContext('2d');
      for (const tile of decoded) ctx.drawImage(tile.img, tile.x, tile.y);
      epoch = header.epoch; seq = header.seq; cursor = header.cursor;
      ws._frameApplied?.(epoch, seq, false);
      paint();
      ws.send(JSON.stringify({ type: 'stream:ack', epoch, seq }));
    } catch (error) {
      if (active()) ws.close(1002, 'Screen decode failed');
    } finally {
      for (const tile of decoded) tile.img.close?.();
      busy = false;
    }
  };
}
