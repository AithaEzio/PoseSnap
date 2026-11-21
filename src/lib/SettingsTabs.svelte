<script lang="ts">
  import { Palette, Settings2, ScanLine, Link2, Cpu, CircleHelp } from 'lucide-svelte';
  import { settingsCategories, type SettingsCategory } from './settings';
  import { tooltip } from './tooltip';
  let { selected, onselect }: { selected: SettingsCategory; onselect: (id: SettingsCategory) => void } = $props();
  const icons = { appearance: Palette, studio: Settings2, extractions: ScanLine, daz: Link2, engine: Cpu, about: CircleHelp };
  function navigate(event: KeyboardEvent, index: number) {
    const steps: Record<string, number> = { ArrowRight: 1, ArrowLeft: -1, ArrowDown: 3, ArrowUp: -3 };
    if (!(event.key in steps) && event.key !== 'Home' && event.key !== 'End') return;
    event.preventDefault();
    const vertical = index < 3 ? Math.min(index + 3, settingsCategories.length - 1) : index - 3;
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? settingsCategories.length - 1 : event.key === 'ArrowUp' || event.key === 'ArrowDown' ? vertical : (index + steps[event.key] + settingsCategories.length) % settingsCategories.length;
    onselect(settingsCategories[next].id);
    (event.currentTarget as HTMLButtonElement).parentElement?.querySelector<HTMLButtonElement>('#settings-tab-' + settingsCategories[next].id)?.focus();
  }
</script>
<div class="settings-tabs" role="tablist" aria-label="Settings categories">
  {#each settingsCategories as category, index}
    {@const Icon = icons[category.id]}
    <button id={'settings-tab-' + category.id} role="tab" aria-selected={selected === category.id} aria-controls={'settings-panel-' + category.id} tabindex={selected === category.id ? 0 : -1} class:active={selected === category.id} onclick={() => onselect(category.id)} onkeydown={event => navigate(event, index)} use:tooltip={category.description}>
      <Icon size={16}/><span>{category.label}</span>
    </button>
  {/each}
</div>
