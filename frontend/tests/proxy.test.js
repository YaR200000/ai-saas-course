import { test } from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { once } from 'node:events';
import { createServer } from 'vite';
import { localOnly, proxyOptions } from '../local-proxy.js';

test('real Vite proxy preserves same-origin headers and rejects foreign requests', async () => {
  let calls = 0;
  const backend = http.createServer((req, res) => {
    calls++;
    assert.equal(req.socket.remoteAddress, '127.0.0.1');
    assert.equal(req.headers.host, frontHost);
    assert.equal(req.headers.origin, `http://${frontHost}`);
    assert.equal(req.headers['sec-fetch-site'], 'same-origin');
    assert.equal(req.headers['x-forwarded-for'], undefined);
    res.writeHead(200, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' });
    res.end(JSON.stringify({ total_income: '0.00', total_expense: '0.00', balance: '0.00' }));
  });
  backend.listen(0, '127.0.0.1');
  await once(backend, 'listening');
  let vite;
  let frontHost;
  try {
    vite = await createServer({ configFile: false, envFile: false, envDir: false,
      optimizeDeps: { noDiscovery: true, include: [] },
      plugins: [localOnly()], server: { host: '127.0.0.1', port: 0, cors: false, hmr: false,
        proxy: proxyOptions(`http://127.0.0.1:${backend.address().port}`) } });
    await vite.listen();
    frontHost = `127.0.0.1:${vite.httpServer.address().port}`;
    const response = await fetch(`http://${frontHost}/api/summary`, {
      headers: { Origin: `http://${frontHost}`, 'Sec-Fetch-Site': 'same-origin' }, signal: AbortSignal.timeout(5000),
    });
    assert.equal(response.status, 200);
    assert.equal(response.headers.get('cache-control'), 'no-store');
    assert.equal((await response.json()).balance, '0.00');
    for (const headers of [
      { Origin: 'https://attacker.example' },
      { Origin: 'null' },
      { 'Sec-Fetch-Site': 'cross-site' },
      { 'Sec-Fetch-Site': 'same-site' },
    ]) {
      const denied = await fetch(`http://${frontHost}/api/summary`, { headers, signal: AbortSignal.timeout(5000) });
      assert.equal(denied.status, 403);
    }
    // Node fetch normalizes Host; use raw HTTP to exercise DNS-rebinding guard.
    const deniedHost = await new Promise((resolve, reject) => {
      const req = http.get(`http://${frontHost}/api/summary`, { headers: { Host: 'attacker.example' } }, (res) => {
        res.resume();
        res.on('end', () => resolve(res.statusCode));
      });
      req.on('error', reject);
      req.setTimeout(5000, () => req.destroy(new Error('Test HTTP timeout')));
    });
    assert.equal(deniedHost, 403);
    assert.equal(calls, 1);
  } finally {
    await vite?.close();
    backend.closeAllConnections();
    await new Promise((resolve) => backend.close(resolve));
  }
});
