import { build } from 'esbuild';
import { readdir, rm } from 'node:fs/promises';
import { spawnSync } from 'node:child_process';

await rm('.test-build', { recursive: true, force: true });
const entries = (await readdir('tests')).filter(name => /\.test\.tsx?$/.test(name)).map(name => `tests/${name}`);
await build({ entryPoints: entries, outdir: '.test-build', bundle: true,
  packages: 'external', platform: 'node', target: 'node20', format: 'cjs',
  jsx: 'automatic', outExtension: { '.js': '.cjs' } });
const files = (await readdir('.test-build')).filter(name => name.endsWith('.cjs')).map(name => `.test-build/${name}`);
const result = spawnSync(process.execPath, ['--test', ...files], { stdio: 'inherit' });
process.exit(result.status ?? 1);
