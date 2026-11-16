/** Production entrypoint: init db -> optional seed -> listen -> graceful shutdown. */
import { createApp } from './app.js';
import { assertProductionSafety, config } from './config.js';
import { initDb, closeDb } from './db.js';
import { seedDemoData } from './lib/seed.js';

assertProductionSafety();
initDb();

if (config.seedOnStart) {
  const { user, password } = await seedDemoData();
  console.log(`Seeded demo account: ${user.email} / ${password}`);
}

const app = createApp();
const server = app.listen(config.port, '0.0.0.0', () => {
  console.log(`TaskFlow API listening on http://localhost:${config.port} (${config.env})`);
});

const shutdown = (signal) => {
  console.log(`\n${signal} received, closing server...`);
  server.close(() => {
    closeDb();
    process.exit(0);
  });
  // Force exit if connections linger.
  setTimeout(() => process.exit(1), 10_000).unref();
};

process.on('SIGINT', () => shutdown('SIGINT'));
process.on('SIGTERM', () => shutdown('SIGTERM'));
