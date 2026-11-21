import {describe,it,expect} from 'vitest';
import {helpTopics,helpMatches} from './help';
import {promptGuideTopics} from './text/promptGuide';
import examples from './text/prompt-examples.json';
describe('searchable offline Kimodo prompt guide',()=>{
  it('finds example prompts, required controls and notes, across multiple search terms',()=>{
    const matching=(query:string)=>helpTopics.filter(t=>helpMatches(t,query));
    expect(matching('right index extended').some(t=>t.examples?.some(e=>e.id==='index'))).toBe(true);
    expect(matching('pinch shapes on').some(t=>t.examples?.some(e=>e.id==='pinch'))).toBe(true);
    expect(matching('two characters same way').some(t=>t.examples?.some(e=>e.id==='handhold'))).toBe(true);
    expect(matching('chair furniture').some(t=>t.examples?.some(e=>e.id==='seated'))).toBe(true);
    expect(matching('screen anatomical').some(t=>t.rewrites?.some(e=>e.id==='screen'))).toBe(true);
    expect(matching('BONES-SEED').some(t=>t.sources?.length)).toBe(true);
    expect(matching('  KIMODO   PROMPT GUIDE  ')).toEqual(promptGuideTopics);
    expect(matching('unmatchable-unique-query')).toEqual([]);
  });
  it('keeps 24 original examples with separate controls and limitations, and six rewrites',()=>{
    const cards=promptGuideTopics.flatMap(t=>t.examples??[]).filter(e=>e.id!=='template');
    expect(cards.map(e=>e.id)).toEqual(examples.map(e=>e.id));
    expect(cards.filter(e=>e.actors===2)).toHaveLength(4);
    expect(cards.filter(e=>e.handShapes)).toHaveLength(3);
    expect(cards.filter(e=>e.experimental)).toHaveLength(10);
    expect(promptGuideTopics.flatMap(t=>t.rewrites??[])).toHaveLength(6);
    for(const card of cards){
      expect(card.prompt.length).toBeLessThanOrEqual(2000);
      expect(card.notes).not.toBe('');
      expect(card.prompt).not.toContain('Approximate hand shapes');
      expect(card.prompt).not.toContain('Genesis');
    }
    const original=cards.map(e=>e.prompt);
    for(const topic of helpTopics)helpMatches(topic,'floor support');
    expect(cards.map(e=>e.prompt)).toEqual(original);
  });
});
