// UI-005: the stylesheet is split into ordered files; nothing may be lost or
// loaded twice, and the tokens must load before every rule that uses them.
import test from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync,readdirSync} from 'node:fs'

const src=new URL('../src/',import.meta.url)
const entry=readFileSync(new URL('styles.css',src),'utf8')

test('main.jsx loads the tokens first and the cascade entry once',()=>{
  const imports=[...readFileSync(new URL('main.jsx',src),'utf8').matchAll(/^import\s+'(\.\/[^']+\.css)'/gm)].map(m=>m[1])
  assert.deepEqual(imports,['./tokens.css','./styles.css'])
})

test('styles.css only lists imports, so the cascade order is visible in one place',()=>{
  const code=entry.replace(/\/\*[\s\S]*?\*\//g,'').split('\n').map(line=>line.trim()).filter(Boolean)
  assert.ok(code.length>0)
  for(const line of code)assert.match(line,/^@import '\.\/styles\/[\w-]+\.css';$/)
})

test('every split stylesheet is imported exactly once',()=>{
  const imported=[...entry.matchAll(/@import '\.\/styles\/([\w-]+\.css)'/g)].map(m=>m[1])
  const files=readdirSync(new URL('styles/',src)).filter(name=>name.endsWith('.css')).sort()
  assert.deepEqual([...imported].sort(),files)
  assert.equal(new Set(imported).size,imported.length)
})

test('split files do not import further stylesheets or redefine the theme tokens',()=>{
  for(const name of readdirSync(new URL('styles/',src)).filter(name=>name.endsWith('.css'))){
    const css=readFileSync(new URL(`styles/${name}`,src),'utf8')
    assert.doesNotMatch(css,/@import/,name)
    assert.doesNotMatch(css,/--(?:action|surface|text|status|border|bg)-[\w-]+\s*:/,`${name} must take tokens from tokens.css`)
  }
})
