import { build } from 'esbuild';
import { copyFile, mkdir, readFile, rm, writeFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { dirname, join } from 'node:path';

const require = createRequire(import.meta.url);
await rm('dist', { recursive: true, force: true });
await mkdir('dist', { recursive: true });
await build({
  entryPoints: ['src/main.tsx'],
  bundle: true,
  outfile: 'dist/app.js',
  format: 'iife',
  platform: 'browser',
  target: ['es2017'],
  minify: true,
  sourcemap: false,
  legalComments: 'inline',
  charset: 'utf8',
  define: { 'process.env.NODE_ENV': '"production"' }
});
await copyFile('index.html', 'dist/index.html');
let notices = 'TankSession UI — third-party software notices\n\n';
for (const name of ['react', 'react-dom', 'scheduler', 'loose-envify', 'js-tokens']) {
  const folder = dirname(require.resolve(name + '/package.json'));
  const info = JSON.parse(await readFile(join(folder, 'package.json'), 'utf8'));
  const license = await readFile(join(folder, 'LICENSE'), 'utf8');
  notices += `${name} ${info.version}\n${license.trim()}\n\n`;
}
await writeFile('dist/THIRD_PARTY_LICENSES.txt', notices, 'utf8');
console.log('Built ui/dist: index.html, app.js, app.css and third-party notices.');
