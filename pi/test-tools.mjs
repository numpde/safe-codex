// Run inside the offline runtime container, against its disposable workspace.
import assert from 'node:assert/strict';
import { createToolDefinition } from '/opt/pi/node_modules/@earendil-works/pi-coding-agent/dist/core/tools/index.js';
async function call(name, args) {
  const result = await createToolDefinition(name, '/workspace').execute('smoke', args);
  assert(!result.isError, JSON.stringify(result));
  console.log('PASS', name);
  return result.content.filter(x => x.type === 'text').map(x => x.text).join('\n');
}
await call('write', {path: 'tool-smoke.txt', content: 'alpha\n'});
assert.match(await call('read', {path: 'tool-smoke.txt'}), /alpha/);
await call('edit', {path: 'tool-smoke.txt', edits: [{oldText: 'alpha', newText: 'beta'}]});
assert.match(await call('grep', {pattern: 'beta', path: '/workspace'}), /tool-smoke/);
assert.match(await call('find', {pattern: '*.txt', path: '/workspace'}), /tool-smoke/);
assert.match(await call('ls', {path: '/workspace'}), /tool-smoke/);
assert.match(await call('bash', {command: 'cat tool-smoke.txt', timeout: 5}), /beta/);
