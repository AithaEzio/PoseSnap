/** A single, accessible tooltip portal. No runtime dependency or per-control timer loop. */
let dismissActive: (() => void) | undefined;
export function dismissTooltips(){dismissActive?.();}
// Clear supplemental help when any control is activated, including controls
// whose own tooltip has not opened yet and focus restored by a closing drawer.
const dismissForActivation=(event:Event)=>{if(!(event.target instanceof Element) || !event.target.closest('.control-tooltip'))dismissActive?.();};
document.addEventListener('pointerdown',dismissForActivation,true);
document.addEventListener('click',dismissForActivation,true);
document.addEventListener('change',dismissForActivation,true);
export function tooltip(node: HTMLElement, initial: string) {
  let text = initial, timer: ReturnType<typeof setTimeout>, popup: HTMLDivElement | undefined;
  let hovered = false, focused = false, dismissed = false;
  const target = node.matches('button,input,select,summary') ? node : node.querySelector<HTMLElement>('button,input,select') ?? node;
  const previous = target.getAttribute('aria-describedby');
  const id = 'tip-' + crypto.randomUUID();
  function hide() {
    clearTimeout(timer); popup?.remove(); popup = undefined;
    if (previous) target.setAttribute('aria-describedby', previous); else target.removeAttribute('aria-describedby');
    if (dismissActive === dismiss) dismissActive = undefined;
  }
  function dismiss() { dismissed = true; hide(); }
  function position() {
    if (!popup) return;
    const r = node.getBoundingClientRect(), p = popup.getBoundingClientRect();
    popup.style.left = Math.max(8, Math.min(innerWidth - p.width - 8, r.left + r.width / 2 - p.width / 2)) + 'px';
    popup.style.top = (r.top > p.height + 12 ? r.top - p.height - 8 : Math.min(innerHeight - p.height - 8, r.bottom + 8)) + 'px';
  }
  function show() {
    if (document.querySelector('.curtain')) { hide(); return; }
    if (!text || dismissed || (!hovered && !focused) || node.closest('[inert]')) return;
    dismissActive?.();
    popup = document.createElement('div'); popup.id = id; popup.className = 'control-tooltip';
    popup.setAttribute('role', 'tooltip'); popup.textContent = text;
    const style = getComputedStyle(node.closest('.app') || node);
    for (const key of ['--text', '--panel', '--line']) popup.style.setProperty(key, style.getPropertyValue(key));
    popup.addEventListener('mouseenter', () => { hovered = true; clearTimeout(timer); });
    popup.addEventListener('mouseleave', () => { hovered = false; scheduleHide(); });
    document.body.append(popup); target.setAttribute('aria-describedby', [previous, id].filter(Boolean).join(' '));
    dismissActive = dismiss; position();
  }
  function schedule() { clearTimeout(timer); if (!popup) timer = setTimeout(show, focused ? 100 : 350); }
  function scheduleHide() { clearTimeout(timer); timer = setTimeout(() => { if (!hovered && !focused) { hide(); dismissed = false; } }, 120); }
  const enter = () => { hovered = true; dismissed = false; schedule(); };
  const leave = () => { hovered = false; scheduleHide(); };
  const focus = () => { focused = true; dismissed = false; schedule(); };
  const blur = () => { focused = false; scheduleHide(); };
  // Activation should clear supplemental help, including native select popups.
  const activate = () => dismiss();
  const key = (e: KeyboardEvent) => { if (e.key === 'Escape' && popup) { dismiss(); if(!node.closest('.curtain')) { e.stopImmediatePropagation(); e.preventDefault(); } } };
  node.addEventListener('mouseenter', enter); node.addEventListener('mouseleave', leave);
  node.addEventListener('focusin', focus); node.addEventListener('focusout', blur);
  node.addEventListener('pointerdown', activate); node.addEventListener('click', activate); node.addEventListener('change', activate);
  window.addEventListener('keydown', key, true); window.addEventListener('resize', hide);
  return {
    update(value: string) { text = value; if (popup) { popup.textContent = value; position(); } },
    destroy() { hide(); node.removeEventListener('mouseenter', enter); node.removeEventListener('mouseleave', leave); node.removeEventListener('focusin', focus); node.removeEventListener('focusout', blur); node.removeEventListener('pointerdown', activate); node.removeEventListener('click', activate); node.removeEventListener('change', activate); window.removeEventListener('keydown', key, true); window.removeEventListener('resize', hide); }
  };
}
