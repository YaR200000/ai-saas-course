// Invoked only by tests/test_dashboard_integration.py with an isolated backend.
import assert from 'node:assert/strict';
import http from 'node:http';
import { once } from 'node:events';
import { createServer } from 'vite';
import { getSummary, getTransactions, formatMoney } from '../src/api.js';
import { proxyOptions } from '../local-proxy.js';

const [scenario, backend] = process.argv.slice(2);
assert.ok(['healthy', 'empty', 'db-down', 'backend-down'].includes(scenario));
assert.match(backend, /^http:\/\/127\.0\.0\.1:\d+$/);
const originalFetch = globalThis.fetch;
let target = backend;
if (scenario === 'backend-down') {
  const unavailable = http.createServer();
  unavailable.listen(0, '127.0.0.1');
  await once(unavailable, 'listening');
  target = `http://127.0.0.1:${unavailable.address().port}`;
  await new Promise((resolve) => unavailable.close(resolve));
}

// Load the actual production Vite config; override only test target/port and HMR.
const vite = await createServer({ logLevel: 'silent',
  optimizeDeps: { noDiscovery: true, include: [] },
  server: { port: 0, strictPort: false, hmr: false, proxy: proxyOptions(target) },
});
try {
  await vite.listen();
  const base = `http://127.0.0.1:${vite.httpServer.address().port}`;
  globalThis.fetch = (path, options = {}) => originalFetch(new URL(path, base), {
    ...options, signal: AbortSignal.timeout(5000), headers: {
      Origin: base, 'Sec-Fetch-Site': 'same-origin', ...options.headers,
    },
  });
  if (scenario === 'healthy') {
    const summary = await getSummary();
    assert.deepEqual(summary, { total_income: '0.00', total_expense: '10000000125.59', balance: '-10000000125.59' });
    assert.equal(formatMoney(summary.balance), '−10\u00a0000\u00a0000\u00a0125,59\u00a0₴');
    const rows = await getTransactions();
    assert.deepEqual(rows.map((row) => row.id), ['3', '2', '1']);
    assert.equal(rows[0].amount, '125.50');
    assert.equal(rows[0].category, 'Інше');
    assert.ok(!JSON.stringify(rows).includes('other-user-private'));
    assert.ok(!JSON.stringify(rows).includes('telegram_'));
    assert.deepEqual(await getTransactions(1), []);
    const page = await (await fetch('/api/transactions?limit=1&offset=1&user_id=2')).json();
    assert.deepEqual(page.map((row) => row.id), ['2']);
    const forged = await fetch('/api/summary?user_id=2&telegram_id=202&limit=1&offset=99', {
      headers: { 'X-Forwarded-For': '192.0.2.1', 'X-User-Id': '2' },
    });
    assert.equal(forged.headers.get('cache-control'), 'no-store');
    assert.deepEqual(await forged.json(), summary);
    assert.deepEqual(await getSummary(), summary);
    assert.equal((await fetch('/api/summary', { headers: { Origin: 'https://attacker.example' } })).status, 403);
    assert.equal((await fetch('/api/transactions', { headers: { 'Sec-Fetch-Site': 'cross-site' } })).status, 403);
  } else if (scenario === 'empty') {
    assert.deepEqual(await getTransactions(), []);
    const summary = await getSummary();
    assert.deepEqual(summary, { total_income: '0.00', total_expense: '0.00', balance: '0.00' });
    assert.equal(formatMoney(summary.balance), '0,00\u00a0₴');
  } else {
    for (const path of ['/api/transactions', '/api/summary']) {
      const response = await fetch(path);
      assert.equal(response.status, scenario === 'db-down' ? 503 : 500);
      if (scenario === 'db-down') {
        assert.equal(response.headers.get('cache-control'), 'no-store');
        assert.deepEqual(await response.json(), { detail: 'Service unavailable.' });
      }
    }
    await assert.rejects(getSummary(), (error) => /API/.test(error.message) && !/SQL|parameters|synthetic/.test(error.message));
    await assert.rejects(getTransactions(), (error) => /API/.test(error.message) && !/SQL|parameters|synthetic/.test(error.message));
  }
  console.log(`${scenario}: integration OK`);
} finally {
  globalThis.fetch = originalFetch;
  await vite.close();
}
