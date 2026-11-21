/** Live pose fields share one Undo transaction from the first change to blur. */
type LiveNumberOptions = {
  value: number;
  context: string;
  normalize?: (value: number) => number;
  onValue: (value: number) => void;
  onEditing: (active: boolean) => void;
};

export function liveNumber(input: HTMLInputElement, initial: LiveNumberOptions) {
  let options = initial, editing = false;
  const display = (value: number) => String(Number(value.toFixed(3)));
  function finish() {
    if (!editing) return;
    editing = false;
    options.onEditing(false);
  }
  function render(force = false) {
    // Keep unfinished negative/decimal entries until blur. Preserve the caret
    // and typed precision when the input already represents the current value.
    if (!force && document.activeElement === input && !Number.isFinite(input.valueAsNumber)) return;
    const value = display(options.value);
    if (force || input.valueAsNumber !== Number(value)) input.value = value;
  }
  function apply(value: number) {
    if (input.disabled || !Number.isFinite(value)) return;
    const bounded = options.normalize?.(value) ?? value;
    if (!Number.isFinite(bounded)) return;
    if (bounded !== value) input.value = display(bounded);
    if (bounded === options.value) return;
    if (!editing) { editing = true; options.onEditing(true); }
    options.onValue(bounded);
  }
  function change() { apply(input.valueAsNumber); }
  function blur() {
    if (Number.isFinite(input.valueAsNumber)) apply(Number(input.valueAsNumber.toFixed(3)));
    render(true);
    finish();
  }
  function keydown(event: KeyboardEvent) {
    if (event.key === 'Enter' || event.key === 'Escape') {
      event.preventDefault();
      input.blur();
    }
  }
  render(true);
  input.addEventListener('input', change);
  input.addEventListener('blur', blur);
  input.addEventListener('keydown', keydown);
  return {
    update(next: LiveNumberOptions) {
      const changedContext = next.context !== options.context;
      if (changedContext || input.disabled) finish();
      options = next;
      render(changedContext);
    },
    destroy() {
      finish();
      input.removeEventListener('input', change);
      input.removeEventListener('blur', blur);
      input.removeEventListener('keydown', keydown);
    }
  };
}
