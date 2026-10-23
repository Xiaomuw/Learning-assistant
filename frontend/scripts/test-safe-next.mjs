// No network/model calls. Compile the actual TypeScript helper with the existing dev dependency.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';
const source = fs.readFileSync('lib/safe-next-path.ts', 'utf8');
const output = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } });
const exportsObject = {};
vm.runInNewContext(output.outputText, { exports: exportsObject, URL });
const safe = exportsObject.getSafeNextPath;
for (const path of [null, '', 'https://evil.invalid', '//evil.invalid', '/\\evil.invalid', '/\tevil', '/login', '/login?next=/practice', '/register#x', '/register/', '/%6cogin', '/bad%ZZ']) {
  assert.equal(safe(path), '/chat', String(path));
}
for (const path of ['/practice?subject=original#question', '/dashboard']) assert.equal(safe(path), path);
console.log('14 same-origin redirect cases passed');
