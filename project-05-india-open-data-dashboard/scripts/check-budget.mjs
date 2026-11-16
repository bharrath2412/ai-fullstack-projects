#!/usr/bin/env node
/**
 * Performance budget gate.
 *
 * Reads the production build in dist/ and fails if the shipped JavaScript or CSS
 * exceeds the budget the README promises. Gzip is measured, because that is what
 * the browser downloads — raw byte counts punish readable code for no reason.
 *
 * Usage: npm run build && npm run check:budget
 */
import { gzipSync, constants } from 'node:zlib';
import { readdir, readFile, stat } from 'node:fs/promises';
import { join, relative } from 'node:path';

const BUDGET = {
  jsGzip: 200 * 1024,
  cssGzip: 40 * 1024,
  totalGzip: 320 * 1024,
  swGzip: 8 * 1024,
};

const DIST = new URL('../dist/', import.meta.url).pathname;

async function walk(dir) {
  const entries = await readdir(dir, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) files.push(...(await walk(path)));
    else files.push(path);
  }
  return files;
}

const kb = (bytes) => `${(bytes / 1024).toFixed(1)} kB`;

async function main() {
  try {
    await stat(DIST);
  } catch {
    console.error('✗ dist/ not found — run `npm run build` first.');
    process.exit(1);
  }

  const files = await walk(DIST);
  // Source maps ship in the build but are only fetched by devtools, so they are
  // reported separately and excluded from the budget.
  const buckets = { js: 0, css: 0, html: 0, other: 0, map: 0 };
  const rows = [];

  for (const file of files) {
    const raw = await readFile(file);
    const gz = gzipSync(raw, { level: constants.Z_BEST_COMPRESSION }).length;
    const ext = file.split('.').pop();
    const kind = file.endsWith('.map')
      ? 'map'
      : ext === 'js'
        ? 'js'
        : ext === 'css'
          ? 'css'
          : ext === 'html'
            ? 'html'
            : 'other';
    buckets[kind] += gz;
    rows.push({ path: relative(DIST, file), gz, kind });
  }

  rows.sort((a, b) => b.gz - a.gz);
  console.log('\nAirGrid production payload (gzip)\n');
  for (const row of rows) {
    console.log(`  ${row.kind.padEnd(5)} ${kb(row.gz).padStart(10)}  ${row.path}`);
  }

  const total = buckets.js + buckets.css + buckets.html + buckets.other;
  console.log(`\n  js     ${kb(buckets.js).padStart(10)}  budget ${kb(BUDGET.jsGzip)}`);
  console.log(`  css    ${kb(buckets.css).padStart(10)}  budget ${kb(BUDGET.cssGzip)}`);
  console.log(`  maps   ${kb(buckets.map).padStart(10)}  excluded (devtools only)`);
  console.log(`  total  ${kb(total).padStart(10)}  budget ${kb(BUDGET.totalGzip)}`);

  const failures = [];
  if (buckets.js > BUDGET.jsGzip) failures.push(`JS ${kb(buckets.js)} > ${kb(BUDGET.jsGzip)}`);
  if (buckets.css > BUDGET.cssGzip) failures.push(`CSS ${kb(buckets.css)} > ${kb(BUDGET.cssGzip)}`);
  if (total > BUDGET.totalGzip) failures.push(`total ${kb(total)} > ${kb(BUDGET.totalGzip)}`);

  if (failures.length) {
    console.error(`\n✗ Budget exceeded: ${failures.join('; ')}`);
    process.exit(1);
  }
  console.log('\n✓ Within budget.\n');
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
