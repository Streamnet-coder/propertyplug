const express = require('express');
const path = require('path');
const http = require('http');
const https = require('https');
require('dotenv').config();

const app = express();
const PORT = process.env.PORT || 3000;
// Live PropertyPlug backend (set API_URL in Hostinger's environment variables), e.g. https://your-app.emergent.host
const API_URL = (process.env.API_URL || '').replace(/\/+$/, '');
const BUILD_DIR = path.join(__dirname, 'client', 'build');

// ==========================================
// 1. API PROXY: /api/* is forwarded to the PropertyPlug backend
// ==========================================
app.use('/api', (req, res) => {
  if (!API_URL) {
    return res.status(503).json({ error: 'API_URL is not set on the server' });
  }
  const target = new URL(API_URL + req.originalUrl);
  const client = target.protocol === 'https:' ? https : http;
  const headers = { ...req.headers, host: target.host };
  const upstream = client.request(target, { method: req.method, headers }, (up) => {
    res.writeHead(up.statusCode || 502, up.headers);
    up.pipe(res);
  });
  upstream.on('error', (err) => {
    console.error('API proxy error:', err.message);
    if (!res.headersSent) res.status(502).json({ error: 'Could not reach the PropertyPlug server' });
  });
  req.pipe(upstream);
});

// ==========================================
// 2. WEB APP: serve the built PropertyPlug website
// ==========================================
app.use(express.static(BUILD_DIR, { index: false, maxAge: '7d' }));

// Every other page loads the app, which handles its own routing
app.get('*', (req, res) => {
  res.setHeader('Cache-Control', 'no-cache');
  res.sendFile(path.join(BUILD_DIR, 'index.html'));
});

// ==========================================
// 3. ERROR HANDLING
// ==========================================
app.use((err, req, res, next) => {
  console.error(err.stack);
  res.status(500).json({ error: 'Something went wrong on the server!' });
});

app.listen(PORT, () => {
  console.log(`PropertyPlug website running on port ${PORT}${API_URL ? `, API -> ${API_URL}` : ' (API_URL not set)'}`);
});
