<script lang="ts">
  import {ChevronDown,ArrowUpRight} from 'lucide-svelte';
  import CopyButton from './CopyButton.svelte';
  import type {HelpTopic} from './help';
  import skillText from '../../skills/kimodo-prompt/SKILL.md?raw';
  let {topics,openTopic='',textMode=false}:{topics:HelpTopic[];openTopic?:string;textMode?:boolean}=$props();
  const groups=$derived((textMode?['kimodo','general']:['general','kimodo']).map(group=>({id:group,title:group==='kimodo'?'Text to Pose · Prompt guide':'Help topics',topics:topics.filter(t=>(t.section??'general')===group)})).filter(g=>g.topics.length));
</script>
{#each groups as group (group.id)}
  <section class="help-section" aria-label={group.title}>
    <h3>{group.title}</h3>
    {#each group.topics as topic (topic.id??topic.title)}
      <details class="help-topic" open={openTopic===topic.id}>
        <summary><span>{topic.title}<small>{topic.tag}</small></span><ChevronDown size={14}/></summary>
        <div class="help-content">
          <p>{topic.text}</p>
          {#if topic.steps?.length}<ol>{#each topic.steps as step}<li>{step}</li>{/each}</ol>{/if}
          {#each topic.paragraphs??[] as paragraph}<p>{paragraph}</p>{/each}
          {#if topic.bullets?.length}<ul>{#each topic.bullets as bullet}<li>{bullet}</li>{/each}</ul>{/if}
          {#each topic.examples??[] as example}
            <article class="help-example" aria-label={example.title}>
              <div class="example-heading"><h4>{example.title}</h4>{#if example.experimental}<span class="state-tag">Experimental</span>{/if}</div>
              <p class="help-prompt">{example.prompt}</p>
              <p class="example-settings">{example.actors===2?'Two characters':'One character'} · Approximate hand shapes {example.handShapes?'On':'Off'}</p>
              <p class="example-note">{example.notes}</p>
              <CopyButton text={example.prompt} ariaLabel={'Copy '+example.title+' prompt'}/>
            </article>
          {/each}
          {#each topic.rewrites??[] as rewrite}
            <article class="help-example" aria-label={rewrite.title}>
              <h4>{rewrite.title}</h4>
              <p class="rewrite-label">Original direction</p><p>{rewrite.before}</p>
              <p class="rewrite-label">Clearer direction</p><p class="help-prompt">{rewrite.after}</p>
              <p class="example-note">{rewrite.note}</p>
              <CopyButton text={rewrite.after} ariaLabel={'Copy '+rewrite.title+' prompt'}/>
            </article>
          {/each}
          {#if topic.skill}
            <div class="help-skill"><CopyButton text={skillText} label="Copy LLM skill"/>
              <details class="skill-view"><summary>View SKILL.md <ChevronDown size={13}/></summary><textarea readonly value={skillText} aria-label="LLM prompt-writing skill" spellcheck="false" rows="10"></textarea></details>
            </div>
          {/if}
          {#if topic.sources?.length}<ul class="help-sources">{#each topic.sources as source}<li><a href={source.url} target="_blank" rel="noreferrer">{source.title}<ArrowUpRight size={12}/></a></li>{/each}</ul>{/if}
        </div>
      </details>
    {/each}
  </section>
{/each}
<style>
  .help-section{margin:19px 0 8px;min-width:0}.help-section>h3{font-size:13px;font-weight:600;line-height:1.6;margin-bottom:5px;color:var(--text)}
  .help-content{padding-bottom:16px;overflow-wrap:anywhere}.help-content>p{padding:0;margin:0 0 13px}.help-content ul,.help-content ol{margin:0 0 14px;padding-left:19px;color:var(--muted);font-size:12px;line-height:1.8}.help-content li{margin:0 0 9px}
  .help-example{border:1px solid var(--line);border-radius:10px;background:var(--deep);padding:13px;margin:13px 0;min-width:0}.example-heading{display:flex;align-items:flex-start;gap:8px;justify-content:space-between;flex-wrap:wrap}.help-example h4{font-size:12px;font-weight:600;line-height:1.6;margin:0 0 8px;color:var(--text)}.help-example p{padding:0;margin:0 0 10px;line-height:1.75;font-size:12px}.help-example .help-prompt{color:var(--text);white-space:pre-wrap;user-select:text}.help-example .example-settings,.help-example .example-note{font-size:10px;line-height:1.7;color:var(--muted)}.help-example .example-settings{color:var(--accent)}.help-example .rewrite-label{font-size:10px;color:var(--muted);margin-bottom:4px}
  .help-skill{margin:14px 0}.skill-view{border:1px solid var(--line);border-radius:8px;margin-top:12px;padding:0 11px}.skill-view summary{font-size:11px}.skill-view textarea{width:100%;resize:vertical;min-height:180px;max-height:420px;box-sizing:border-box;margin:0 0 11px;padding:10px;border:1px solid var(--line);border-radius:6px;background:var(--deep);color:var(--text);font-family:monospace;font-size:11px;line-height:1.6}
  .help-content .help-sources{list-style:none;padding:0}.help-sources a{display:inline-flex;align-items:center;gap:5px;line-height:1.6;font-size:11px}
</style>
