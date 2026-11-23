import { analyzeTransactions } from './api.js';

// Imperative request lifetime shared by the click handler and effect cleanup.
// Construction and cancellation never start an HTTP request.
export function createAnalysisRequest() {
  let active = null;
  return {
    cancel() { active?.abort(); active = null; },
    async start({ password, pending, revision, runAdmin, onState, onUnauthorized }) {
      if (!password || pending || active) return false;
      const controller = new AbortController();
      active = controller;
      try {
        return await runAdmin(async () => {
          onState({ data: null, error: '', status: 'loading' });
          try {
            const data = await analyzeTransactions(password, controller.signal);
            if (!controller.signal.aborted) onState({ data, revision, error: '', status: 'ready' });
          } catch (error) {
            if (controller.signal.aborted) return;
            onState({ data: null, error: error.message, errorStatus: error.status, status: 'error' });
            if (error.status === 401) onUnauthorized();
          }
        });
      } finally {
        if (active === controller) active = null;
      }
    },
  };
}
