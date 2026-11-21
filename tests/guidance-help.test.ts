import {describe,it,expect} from 'vitest';
import {helpMatches,helpTopics} from '../src/lib/help';
import {guidanceHelp} from '../src/lib/guidanceHelp';

describe('Offline image guidance help',()=>{
  it('searches mode choices, depth conventions and optional engine limitations',()=>{
    for(const [query,id] of [['Automatic baseline extraction','image-guidance'],['zero relative','guidance-depth-input'],['albedo geometry','guidance-evidence'],['10% accuracy','guidance-moge']]){
      expect(helpTopics.some(topic=>topic.id===id&&helpMatches(topic,query))).toBe(true);
    }
  });
  it('keeps source links and unique navigation targets',()=>{
    expect(new Set(helpTopics.map(topic=>topic.id??topic.title)).size).toBe(helpTopics.length);
    expect(guidanceHelp.every(topic=>topic.paragraphs?.length||topic.bullets?.length)).toBe(true);
    expect(guidanceHelp.flatMap(topic=>topic.sources??[]).every(source=>source.url.startsWith('https://'))).toBe(true);
  });
});
