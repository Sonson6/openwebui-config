import express from 'express';
import { render } from '@antv/gpt-vis-ssr';
import { randomUUID } from 'node:crypto';
import { mkdirSync, writeFileSync } from 'node:fs';
import path from 'node:path';

const CHARTS_DIR = process.env.CHARTS_DIR || '/charts';
const PUBLIC_BASE_URL = process.env.PUBLIC_BASE_URL || 'http://localhost:3001';
const PORT = process.env.PORT || 3000;

mkdirSync(CHARTS_DIR, { recursive: true });

const app = express();
app.use(express.json({ limit: '10mb' }));
app.use('/charts', express.static(CHARTS_DIR));

// Implements the VIS_REQUEST_SERVER contract used by @antv/mcp-server-chart:
// request body is `{ type, ...options, source }` for charts, or
// `{ serviceId, tool, input, source }` for geographic/map tools.
app.post('/', async (req, res) => {
  const { source, serviceId, tool, input, ...options } = req.body ?? {};

  if (serviceId || tool) {
    return res.json({
      success: false,
      errorMessage:
        'Geographic charts (district-map, path-map, pin-map) require AMap and are not supported by this self-hosted renderer.',
    });
  }

  try {
    const vis = await render(options);
    const filename = `${randomUUID()}.png`;
    writeFileSync(path.join(CHARTS_DIR, filename), vis.toBuffer());
    vis.destroy();
    res.json({ success: true, resultObj: `${PUBLIC_BASE_URL}/charts/${filename}` });
  } catch (err) {
    res.json({ success: false, errorMessage: err instanceof Error ? err.message : String(err) });
  }
});

app.get('/healthz', (_req, res) => res.send('ok'));

app.listen(PORT, () => {
  console.log(`gpt-vis render server listening on :${PORT}`);
});
