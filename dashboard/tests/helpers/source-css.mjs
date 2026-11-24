// The dashboard stylesheet is split into ordered files under src/styles/.
// Source-level tests read the whole cascade as one text, in import order.
import {readFileSync} from 'node:fs'
import {dirname,resolve} from 'node:path'
import {fileURLToPath} from 'node:url'

const entry=fileURLToPath(new URL('../../src/styles.css',import.meta.url))

export function readSourceCss(file=entry,seen=new Set()){
  if(seen.has(file))return ''
  seen.add(file)
  return readFileSync(file,'utf8').replace(/@import\s+['"]([^'"]+)['"]\s*;/g,(_,path)=>readSourceCss(resolve(dirname(file),path),seen))
}
