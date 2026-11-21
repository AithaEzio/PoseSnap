type Download = { urls: string[]; parts?: { urls: string[] }[] };

/** Mirror native multipart availability in the browser-only engine fixture. */
export function fixtureDownloads(artifacts: Download[]) {
  const sources = artifacts.map(artifact => artifact.parts?.length ? artifact.parts : [artifact]);
  return {
    downloadSources: sources.flat().flatMap(source => source.urls),
    downloadable: sources.length > 0 && sources.every(parts => parts.every(part => part.urls.length > 0))
  };
}
