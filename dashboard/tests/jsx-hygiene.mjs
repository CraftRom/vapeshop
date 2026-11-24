// A JSX element with the same attribute twice silently keeps only the last
// one (e.g. className="u-flex-1" className="muted" loses the layout class).
import test from 'node:test'
import assert from 'node:assert/strict'
import {fileURLToPath} from 'node:url'
import {build} from 'esbuild'

test('no JSX element repeats an attribute',async()=>{
  const result=await build({entryPoints:[fileURLToPath(new URL('../src/main.jsx',import.meta.url))],bundle:true,write:false,jsx:'automatic',loader:{'.css':'empty','.js':'jsx'},logLevel:'silent',define:{'import.meta.env.VITE_API_URL':'""','process.env.NODE_ENV':'"test"'}})
  const duplicates=result.warnings.filter(w=>/Duplicate/.test(w.text)).map(w=>`${w.location?.file}:${w.location?.line} ${w.text}`)
  assert.deepEqual(duplicates,[])
})
