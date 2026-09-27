import fs from 'node:fs';
import crypto from 'node:crypto';
const digest = path => crypto.createHash('sha256').update(fs.readFileSync(path)).digest('hex');
const root = process.env.INPUT_ROOT || '/output';
const policy = process.env.POLICY_ROOT || '/scripts';
if (process.argv[2] === 'apk') {
  const lock = JSON.parse(fs.readFileSync(`${policy}/apk.lock.json`));
  const actual = fs.readdirSync(`${root}/apk`).sort();
  if (JSON.stringify(actual) !== JSON.stringify(lock.map(x => x.file).sort())) throw Error('Unexpected APK files');
  for (const entry of lock) {
    if (digest(`${root}/apk/${entry.file}`) !== entry.sha256) throw Error(`APK checksum mismatch: ${entry.file}`);
  }
} else if (process.argv[2] === 'app') {
  for (const name of ['package.json', 'package-lock.json']) {
    if (digest(`${root}/app/${name}`) !== digest(`${policy}/${name}`)) throw Error(`App lock mismatch: ${name}`);
  }
  const packageInfo = JSON.parse(fs.readFileSync(`${root}/app/node_modules/@earendil-works/pi-coding-agent/package.json`));
  if (packageInfo.version !== '0.86.1') throw Error('Unexpected Pi version');
} else throw Error('Expected apk or app');
console.log('Verified pinned', process.argv[2], 'inputs');
