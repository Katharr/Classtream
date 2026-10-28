/** Local viewport panning; never changes the screen sent to other viewers. */
import { state } from '/static/js/state.js';

const area = document.getElementById('screen-area');
const image = document.getElementById('screen-img');
let x = 0, y = 0, drag = null;
let paintedX = null, paintedY = null;

function stopDrag() {
  if (drag && area.hasPointerCapture(drag.id)) area.releasePointerCapture(drag.id);
  drag = null;
  area.classList.remove('panning');
}

function update() {
  const zoomed = state.zoom > 1;
  area.classList.toggle('zoomed', zoomed);
  if (!zoomed) {
    x = y = 0;
    stopDrag();
  } else {
    const style = getComputedStyle(area);
    const width = area.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
    const height = area.clientHeight - parseFloat(style.paddingTop) - parseFloat(style.paddingBottom);
    const maxX = Math.max(0, (image.offsetWidth * state.zoom - width) / 2);
    const maxY = Math.max(0, (image.offsetHeight * state.zoom - height) / 2);
    x = Math.max(-maxX, Math.min(maxX, x));
    y = Math.max(-maxY, Math.min(maxY, y));
  }
  // A separate translation leaves the zoom controls' scale transform intact.
  if (x !== paintedX || y !== paintedY) {
    image.style.translate = `${x}px ${y}px`;
    paintedX = x;
    paintedY = y;
  }
}

area.addEventListener('pointerdown', event => {
  if (state.zoom <= 1 || event.button !== 0 || !event.isPrimary ||
      !['screen-img', 'single-view', 'screen-area'].includes(event.target.id)) return;
  event.preventDefault();
  stopDrag();
  area.setPointerCapture(event.pointerId);
  drag = { id: event.pointerId, x: event.clientX, y: event.clientY };
  area.classList.add('panning');
});
area.addEventListener('pointermove', event => {
  if (!drag || drag.id !== event.pointerId) return;
  if (!(event.buttons & 1)) return stopDrag();
  x += event.clientX - drag.x;
  y += event.clientY - drag.y;
  drag.x = event.clientX;
  drag.y = event.clientY;
  update();
});
for (const event of ['pointerup', 'pointercancel', 'lostpointercapture']) {
  area.addEventListener(event, stopDrag);
}
window.addEventListener('blur', stopDrag);
image.addEventListener('dragstart', event => event.preventDefault());
// Zoom buttons and keyboard shortcuts both update the image transform.
new MutationObserver(update).observe(image, { attributes: true, attributeFilter: ['style'] });
const resize = new ResizeObserver(update);
resize.observe(area);
resize.observe(image);
update();
