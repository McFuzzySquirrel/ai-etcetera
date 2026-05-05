import type { CytoscapeExport } from './types';

function loadEmbeddedGraph(): CytoscapeExport | null {
  const node = document.getElementById('dirk-graph-data');
  if (!node || !node.textContent) {
    return null;
  }

  try {
    const parsed = JSON.parse(node.textContent) as CytoscapeExport;
    if (Array.isArray(parsed.elements)) {
      return parsed;
    }
  } catch {
    return null;
  }

  return null;
}

export async function loadGraph(): Promise<CytoscapeExport> {
  const embedded = loadEmbeddedGraph();
  if (embedded) {
    return embedded;
  }

  const graphUrl = new URL('./graph.json', window.location.href);
  const response = await fetch(graphUrl);
  if (!response.ok) {
    throw new Error(`Could not load graph.json: HTTP ${response.status}`);
  }
  return response.json() as Promise<CytoscapeExport>;
}
