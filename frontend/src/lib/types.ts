export type GraphElement = {
  data: Record<string, unknown> & {
    id: string;
    kind: string;
    label?: string;
    source?: string;
    target?: string;
  };
};

export type CytoscapeExport = {
  elements: GraphElement[];
  generated_at?: string;
};
