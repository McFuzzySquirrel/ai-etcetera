import { forwardRef, useEffect, useImperativeHandle, useRef } from 'react';
import cytoscape, { type Core, type ElementDefinition } from 'cytoscape';

import type { GraphElement } from '../lib/types';

type GraphCanvasProps = {
  elements: GraphElement[];
  selectedId: string | null;
  highlightedIds: string[];
  kindColors: Record<string, string>;
  onSelect: (id: string | null) => void;
};

export type GraphCanvasHandle = {
  fitAll: () => void;
  resetView: () => void;
};

const GraphCanvas = forwardRef<GraphCanvasHandle, GraphCanvasProps>(function GraphCanvas(
  { elements, selectedId, highlightedIds, kindColors, onSelect },
  ref,
) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const instanceRef = useRef<Core | null>(null);

  useImperativeHandle(ref, () => ({
    fitAll: () => {
      const cy = instanceRef.current;
      if (!cy) {
        return;
      }
      cy.animate({ fit: { eles: cy.elements(), padding: 40 }, duration: 260 });
    },
    resetView: () => {
      const cy = instanceRef.current;
      if (!cy) {
        return;
      }
      cy.elements().unselect();
      cy.elements().removeClass('dimmed');
      cy.elements().removeClass('focused');
      cy.elements().removeClass('search-match');
      cy.animate({ zoom: 1, pan: { x: 0, y: 0 }, duration: 260 });
    },
  }));

  useEffect(() => {
    if (!containerRef.current) {
      return;
    }

    const definitions: ElementDefinition[] = elements.map((element) => ({ data: element.data }));
    const cy = cytoscape({
      container: containerRef.current,
      elements: definitions,
      style: [
        {
          selector: 'node',
          style: {
            label: 'data(label)',
            'background-color': (node) => kindColors[node.data('kind')] ?? '#8a94a6',
            color: '#102033',
            'font-size': 11,
            'font-weight': 600,
            'text-wrap': 'wrap',
            'text-max-width': '90px',
            'text-valign': 'center',
            'text-halign': 'center',
            width: 28,
            height: 28,
            'border-width': 2,
            'border-color': 'rgba(255,255,255,0.85)',
          },
        },
        {
          selector: 'edge',
          style: {
            width: 1.2,
            'line-color': '#b8c6db',
            'curve-style': 'bezier',
            opacity: 0.55,
          },
        },
        {
          selector: 'node:selected',
          style: {
            'border-color': '#ff6b35',
            'border-width': 4,
            'overlay-opacity': 0,
          },
        },
        {
          selector: '.dimmed',
          style: {
            opacity: 0.14,
          },
        },
        {
          selector: '.focused',
          style: {
            opacity: 1,
            width: 34,
            height: 34,
            'z-index': 20,
          },
        },
        {
          selector: '.search-match',
          style: {
            'border-color': '#0a8f6a',
            'border-width': 4,
            'background-opacity': 1,
            'z-index': 18,
          },
        },
      ],
      layout: {
        name: 'cose',
        animate: false,
        fit: true,
        padding: 24,
      },
    });

    cy.on('tap', 'node', (event) => {
      onSelect(event.target.id());
    });

    cy.on('tap', (event) => {
      if (event.target === cy) {
        onSelect(null);
      }
    });

    instanceRef.current = cy;

    return () => {
      cy.destroy();
      instanceRef.current = null;
    };
  }, [elements, kindColors, onSelect]);

  useEffect(() => {
    const cy = instanceRef.current;
    if (!cy) {
      return;
    }

    cy.elements().removeClass('dimmed');
    cy.elements().removeClass('focused');
    cy.elements().unselect();

    if (!selectedId) {
      cy.fit(cy.elements(), 40);
      return;
    }

    const selected = cy.getElementById(selectedId);
    if (!selected.nonempty()) {
      return;
    }

    const neighborhood = selected.closedNeighborhood();
    cy.elements().difference(neighborhood).addClass('dimmed');
    neighborhood.addClass('focused');
    selected.select();
    cy.animate({ fit: { eles: neighborhood, padding: 80 }, duration: 260 });
  }, [selectedId]);

  useEffect(() => {
    const cy = instanceRef.current;
    if (!cy) {
      return;
    }

    cy.nodes().removeClass('search-match');
    if (!highlightedIds.length) {
      return;
    }

    for (const id of highlightedIds) {
      const node = cy.getElementById(id);
      if (node.nonempty()) {
        node.addClass('search-match');
      }
    }
  }, [highlightedIds]);

  return <div className="graph-canvas" id="graph-canvas" ref={containerRef} />;
});

export default GraphCanvas;
