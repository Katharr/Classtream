/** Helpers for a receive-only classroom over ordinary LAN HTTP. */
export function watchClassroomAddress() {
  const update = async () => {
    try {
      const response = await fetch('/lan-info', {cache: 'no-store'});
      if (!response.ok) return;
      const {student_url, fallback_url, mdns_status} = await response.json();
      for (const id of ['current-session-link', 'link-modal-url']) {
        const element = document.getElementById(id);
        if (element && /^https?:/.test(element.textContent.trim())) element.textContent = student_url;
      }
      const url = document.getElementById('link-modal-url');
      if (url && fallback_url) {
        let backup = document.getElementById('lan-backup-address');
        if (!backup) {
          backup = document.createElement('p');
          backup.id = 'lan-backup-address';
          backup.style.cssText = 'font-size:13px;overflow-wrap:anywhere;margin-top:10px';
          url.insertAdjacentElement('afterend', backup);
        }
        backup.textContent = mdns_status === 'published'
          ? `名称打不开时，使用备用地址：${fallback_url}`
          : mdns_status === 'conflict'
            ? '局域网名称已被占用，请使用上方 IP 地址。'
            : mdns_status === 'disabled' ? '' : '局域网名称暂不可用，请使用上方 IP 地址。';
      }
    } catch { /* reconnect after a temporary network interruption */ }
  };
  update();
  setInterval(update, 3000);
}

export function createSessionId() {
  if (typeof globalThis.crypto?.randomUUID === 'function') {
    return globalThis.crypto.randomUUID();
  }
  const bytes = new Uint8Array(16);
  globalThis.crypto.getRandomValues(bytes);
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, b => b.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

export async function copyText(text) {
  if (typeof navigator.clipboard?.writeText === 'function') {
    try { await navigator.clipboard.writeText(text); return; } catch { /* use legacy copy */ }
  }
  const previous = document.activeElement;
  const field = document.createElement('textarea');
  field.value = text;
  field.readOnly = true;
  field.style.cssText = 'position:fixed;top:0;left:0;opacity:0;pointer-events:none';
  document.body.appendChild(field);
  let copied = false;
  try {
    field.focus();
    field.select();
    field.setSelectionRange(0, field.value.length);
    copied = document.execCommand('copy');
  } catch { /* browser policy may disallow programmatic copy */ }
  finally { field.remove(); previous?.focus(); }
  if (!copied) window.prompt('请按 Ctrl+C 复制以下内容：', text);
}
