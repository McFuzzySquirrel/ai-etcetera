import { useEffect, useMemo, useRef, useState } from 'react';

import GraphCanvas, { type GraphCanvasHandle } from './components/GraphCanvas';
import { loadGraph } from './lib/loadGraph';
import type { CytoscapeExport, GraphElement } from './lib/types';

type ViewState =
  | { status: 'loading' }
  | { status: 'ready'; graph: CytoscapeExport }
  | { status: 'error'; message: string };

const KIND_COLORS: Record<string, string> = {
  Repo: '#2667ff',
  Concept: '#ff8c42',
  Technology: '#41b883',
  Interface: '#b76ac4',
  Person: '#9b6b43',
  Domain: '#ef476f',
  Artifact: '#5c7cfa',
};

function isNode(element: GraphElement): boolean {
  return typeof element.data.source !== 'string' && typeof element.data.target !== 'string';
}

function isEdge(element: GraphElement): boolean {
  return typeof element.data.source === 'string' && typeof element.data.target === 'string';
}

function App() {
  const [state, setState] = useState<ViewState>({ status: 'loading' });
  const [search, setSearch] = useState('');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [showHelp, setShowHelp] = useState(false);
  const searchInputRef = useRef<HTMLInputElement | null>(null);
  const graphRef = useRef<GraphCanvasHandle | null>(null);

  useEffect(() => {
    let cancelled = false;

    loadGraph()
      .then((graph) => {
        if (!cancelled) {
          setState({ status: 'ready', graph });
        }
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          const message = error instanceof Error ? error.message : 'Unknown graph loading error';
          setState({ status: 'error', message });
        }
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const graph = state.status === 'ready' ? state.graph : null;

  const nodeElements = useMemo(() => {
    if (!graph) {
      return [];
    }
    return graph.elements.filter(isNode);
  }, [graph]);

  const edgeCount = useMemo(() => {
    if (!graph) {
      return 0;
    }
    return graph.elements.filter(isEdge).length;
  }, [graph]);

  const filteredNodes = useMemo(() => {
    const query = search.trim().toLowerCase();
    if (!query) {
      return nodeElements.slice(0, 12);
    }

    return nodeElements
      .filter((element) => {
        const label = String(element.data.label ?? '').toLowerCase();
        const kind = String(element.data.kind ?? '').toLowerCase();
        const id = String(element.data.id).toLowerCase();
        return label.includes(query) || kind.includes(query) || id.includes(query);
      })
      .slice(0, 12);
  }, [nodeElements, search]);

  const selectedElement = useMemo(() => {
    if (!graph || !selectedId) {
      return null;
    }
    return graph.elements.find((element) => element.data.id === selectedId) ?? null;
  }, [graph, selectedId]);

  const selectedProperties = useMemo(() => {
    if (!selectedElement) {
      return [] as Array<[string, unknown]>;
    }
    return Object.entries(selectedElement.data).filter(([key]) => key !== 'id');
  }, [selectedElement]);

  const selectedConnections = useMemo(() => {
    if (!graph || !selectedId) {
      return 0;
    }
    return graph.elements.filter((element) => {
      if (!isEdge(element)) {
        return false;
      }
      return element.data.source === selectedId || element.data.target === selectedId;
    }).length;
  }, [graph, selectedId]);

  const searchMatchIds = useMemo(
    () => filteredNodes.map((element) => element.data.id),
    [filteredNodes],
  );

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === '/' && document.activeElement !== searchInputRef.current) {
        event.preventDefault();
        searchInputRef.current?.focus();
        return;
      }

      if (event.key === 'Escape') {
        setSelectedId(null);
        setSearch('');
        setShowHelp(false);
        return;
      }

      if (
        event.key === '?' ||
        (event.key === '/' && event.shiftKey) ||
        (event.code === 'Slash' && event.shiftKey)
      ) {
        event.preventDefault();
        setShowHelp((value) => !value);
        return;
      }

      if (event.key === ' ') {
        if (document.activeElement === searchInputRef.current) {
          return;
        }
        event.preventDefault();
        graphRef.current?.fitAll();
      }
    };

    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <p className="eyebrow">Dirk Graph UI</p>
        <h1>Holistic Discovery</h1>
        <p className="lede">
          A React-based viewer for exploring repository relationships with search, focused
          selection, and a cleaner information hierarchy.
        </p>

        <label className="search-block">
          <span>Search nodes</span>
          <input
            id="search-input"
            ref={searchInputRef}
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Repo, concept, technology..."
          />
        </label>

        <div className="panel-card rail-card">
          <div className="rail-header">
            <h2>Matches</h2>
            <span>
              {filteredNodes.length} / {nodeElements.length}
            </span>
          </div>
          <div className="result-list">
            {filteredNodes.map((element) => (
              <button
                key={element.data.id}
                className={`result-item${selectedId === element.data.id ? ' active' : ''}`}
                onClick={() => setSelectedId(element.data.id)}
                type="button"
              >
                <strong>{String(element.data.label ?? element.data.id)}</strong>
                <span>{String(element.data.kind)}</span>
              </button>
            ))}
          </div>
        </div>
      </aside>

      <section className="content-panel">
        {state.status === 'loading' && (
          <div className="panel-card">
            <h2>Loading graph</h2>
            <p>Reading graph.json from the generated output directory.</p>
          </div>
        )}

        {state.status === 'error' && (
          <div className="panel-card panel-error">
            <h2>Graph load failed</h2>
            <p>{state.message}</p>
          </div>
        )}

        {state.status === 'ready' && (
          <div className="viewer-layout">
            <div className="viewer-column">
              <div className="panel-card stats-grid">
                <div>
                  <span className="stat-label">Nodes</span>
                  <strong>{nodeElements.length}</strong>
                </div>
                <div>
                  <span className="stat-label">Edges</span>
                  <strong>{edgeCount}</strong>
                </div>
                <div>
                  <span className="stat-label">Generated</span>
                  <strong>{state.graph.generated_at ?? 'unknown'}</strong>
                </div>
              </div>

              <div className="panel-card canvas-card">
                <div className="canvas-header">
                  <div>
                    <h2>Relationship map</h2>
                    <p>Select a node from the graph or the left rail to focus its neighborhood.</p>
                  </div>
                  <div className="button-row">
                    <button className="ghost-button" onClick={() => graphRef.current?.fitAll()} type="button">
                      Fit (Space)
                    </button>
                    <button
                      className="ghost-button"
                      onClick={() => {
                        setSelectedId(null);
                        graphRef.current?.resetView();
                      }}
                      type="button"
                    >
                      Reset
                    </button>
                    <button className="ghost-button" onClick={() => setShowHelp((value) => !value)} type="button">
                      Help (?)
                    </button>
                  </div>
                </div>
                <GraphCanvas
                  ref={graphRef}
                  elements={state.graph.elements}
                  selectedId={selectedId}
                  highlightedIds={search.trim() ? searchMatchIds : []}
                  onSelect={setSelectedId}
                  kindColors={KIND_COLORS}
                />
              </div>
            </div>

            <aside className="detail-column">
              <div className="panel-card detail-card">
                <h2>Details</h2>
                {!selectedElement && (
                  <p className="detail-empty">
                    No node selected yet. Click inside the graph or choose a match on the left.
                  </p>
                )}

                {selectedElement && (
                  <>
                    <div className="detail-heading">
                      <strong>{String(selectedElement.data.label ?? selectedElement.data.id)}</strong>
                      <span>{String(selectedElement.data.kind)}</span>
                    </div>
                    <div className="summary-chips">
                      <span>{selectedConnections} connected edges</span>
                      <span>ID: {String(selectedElement.data.id)}</span>
                    </div>
                    <dl className="detail-grid">
                      {selectedProperties.map(([key, value]) => (
                        <div key={key} className="detail-row">
                          <dt>{key}</dt>
                          <dd>{typeof value === 'string' ? value : JSON.stringify(value)}</dd>
                        </div>
                      ))}
                    </dl>
                  </>
                )}
              </div>

              {showHelp && (
                <div className="panel-card help-card" id="help-panel">
                  <h2>Keyboard shortcuts</h2>
                  <ul>
                    <li>/ - Focus search</li>
                    <li>Space - Fit graph to viewport</li>
                    <li>Escape - Clear search and selection</li>
                    <li>? - Toggle this help panel</li>
                  </ul>
                </div>
              )}

              <div className="panel-card legend-card">
                <h2>Legend</h2>
                <div className="legend-list">
                  {Object.entries(KIND_COLORS).map(([kind, color]) => (
                    <div key={kind} className="legend-item" role="listitem">
                      <span className="legend-swatch" style={{ backgroundColor: color }} />
                      <span>{kind}</span>
                    </div>
                  ))}
                </div>
              </div>
            </aside>
          </div>
        )}
      </section>
    </main>
  );
}

export default App;
