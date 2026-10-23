export interface ProcessPanelState { hasTrace: boolean; open: boolean }

/** Open only when a trace first arrives; later chunks respect the user's choice. */
export function advanceProcessPanelState(previous: ProcessPanelState, hasTrace: boolean): ProcessPanelState {
  if (previous.hasTrace === hasTrace) return previous;
  return { hasTrace, open: hasTrace || previous.open };
}
