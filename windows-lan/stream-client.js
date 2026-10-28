/** CS2 JPEG rectangle receiver. RFB-style framebuffer + completed-batch ACK.
 * Reuses the existing stream module's authentication, controls and reconnects.
 */
import { state } from './state.js';

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
  }
  window.addEventListener('classtream-pause', paint);
  ws.addEventListener('close', () => {
    window.removeEventListener('classtream-pause', paint);
    base.width = base.height = 0;
  }, { once: true });
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
