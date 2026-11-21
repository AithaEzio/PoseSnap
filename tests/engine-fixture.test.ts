import { expect, it } from 'vitest';
import { fixtureDownloads } from '../scripts/engine-fixture';

it('keeps a multipart runtime with its raw helper downloadable in the browser fixture', () => {
  expect(fixtureDownloads([
    { urls: [], parts: [{ urls: ['part-1'] }, { urls: ['part-2'] }] },
    { urls: ['helper'] }
  ])).toEqual({ downloadSources: ['part-1', 'part-2', 'helper'], downloadable: true });
});

it('reports incomplete or unavailable components as blocked', () => {
  expect(fixtureDownloads([]).downloadable).toBe(false);
  expect(fixtureDownloads([{ urls: [] }]).downloadable).toBe(false);
  expect(fixtureDownloads([{ urls: [], parts: [{ urls: ['part-1'] }, { urls: [] }] }]).downloadable).toBe(false);
});
