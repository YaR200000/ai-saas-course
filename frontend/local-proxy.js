import { isIP } from 'node:net';

// Keep Host unchanged: the backend compares Origin with http://Host.
export function proxyOptions(target = 'http://127.0.0.1:8000') {
  return { '/api': { target, changeOrigin: false, xfwd: false } };
}

export function localOnly() {
  const install = (server) => { server.middlewares.use((req, res, next) => {
    const peer = req.socket.remoteAddress;
    const host = req.headers.host || '';
    const localPeer = peer === '127.0.0.1' || peer === '::1' || peer === '::ffff:127.0.0.1';
    const localHost = /^(127\.0\.0\.1|localhost):\d+$/.test(host);
    const origin = req.headers.origin;
    const foreign = origin !== undefined && origin !== `http://${host}`;
    if (!localPeer || !isIP(peer?.replace('::ffff:', '') || '') || !localHost || foreign ||
        ['cross-site', 'same-site'].includes(req.headers['sec-fetch-site'])) {
      res.writeHead(403, { 'Cache-Control': 'no-store', 'Content-Type': 'text/plain; charset=utf-8' });
      res.end('Local access only.');
      return;
    }
    next();
  }); };
  return { name: 'local-access-only', configureServer: install, configurePreviewServer: install };
}
