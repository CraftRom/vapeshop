import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { createHash } from 'node:crypto'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'

// A13: content digest of the shipped sources, so a deployed bundle is
// unambiguous even when nobody bumped the version label. Exposed to the app
// as __APP_RELEASE__ and served as /release.json for post-deploy checks.
function sourceFiles(root, dir, out = []) {
  for (const name of readdirSync(join(root, dir))) {
    const path = join(dir, name)
    if (statSync(join(root, path)).isDirectory()) sourceFiles(root, path, out)
    else out.push(path)
  }
  return out
}
function releaseDigest(root) {
  const hash = createHash('sha256')
  const files = [...sourceFiles(root, 'src'), 'index.html', 'package-lock.json', 'vite.config.js']
  for (const file of files.map((f) => f.split('\\').join('/')).sort()) {
    hash.update(file + '\0'); hash.update(readFileSync(join(root, file))); hash.update('\0')
  }
  return hash.digest('hex')
}
function releasePlugin(component) {
  const root = new URL('.', import.meta.url).pathname
  const digest = releaseDigest(root)
  const release = { component, digest, id: `${component}+${digest.slice(0, 12)}` }
  return {
    name: 'release-id',
    config: () => ({ define: { __APP_RELEASE__: JSON.stringify(release.id) } }),
    generateBundle() {
      this.emitFile({ type: 'asset', fileName: 'release.json', source: JSON.stringify({ ...release, built_at: new Date().toISOString() }) + '\n' })
    },
  }
}

export default defineConfig({
  plugins: [react(), releasePlugin('dashboard')],
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          // recharts тягне d3 — виносимо окремо, щоб не роздувати основний бандл
          charts: ['recharts'],
          vendor: ['react', 'react-dom', 'react-router-dom'],
        },
      },
    },
  },
  server: {
    host: true,
    port: 5173,
    proxy: {
      '/api': { target: 'http://localhost:8000', changeOrigin: true },
      '/media': { target: 'http://localhost:8000', changeOrigin: true },
    },
  },
})
