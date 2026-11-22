import { useEffect, useState } from 'react';

export function useResource(loader, page, version) {
  const [state, setState] = useState({ status: 'loading', data: null, error: '' });
  useEffect(() => {
    const controller = new AbortController();
    setState({ status: 'loading', data: null, error: '' });
    loader(page, controller.signal).then(
      (data) => { if (!controller.signal.aborted) setState({ status: 'ready', data, error: '', page, version }); },
      (error) => { if (!controller.signal.aborted) setState({ status: 'error', data: null, page, version,
        error: error.message || 'Не вдалося завантажити дані.' }); },
    );
    return () => controller.abort();
  }, [loader, page, version]);
  // Never display a previous request's data between render and effect cleanup.
  return state.page === page && state.version === version ? state : { status: 'loading', data: null, error: '' };
}
