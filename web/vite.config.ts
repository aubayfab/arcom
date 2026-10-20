import { defineConfig, type Plugin } from 'vite'
import { spawn, type ChildProcess } from 'node:child_process'
import { existsSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = fileURLToPath(new URL('..', import.meta.url))
const PORT = process.env.ARCOM_PORT ?? '8787'
// 127.0.0.1 et non « localhost » : sous Windows, localhost tente d'abord ::1 et perd ~2 s par requête.
const BACKEND = `http://127.0.0.1:${PORT}`

async function backendUp(): Promise<boolean> {
  try {
    const res = await fetch(`${BACKEND}/api/health`, { signal: AbortSignal.timeout(500) })
    return res.ok
  } catch {
    return false
  }
}

/**
 * En dev, lance server.py (qui tient les connexions BLE) avec Vite, sauf s'il tourne déjà,
 * et le relance s'il s'arrête. Il survit aux redémarrages de Vite (modif. de cette config)
 * et s'arrête avec le processus Vite.
 */
function arcomBackend(): Plugin {
  let child: ChildProcess | undefined
  let stopping = false
  let quickExits = 0
  const stop = () => {
    stopping = true
    child?.kill()
  }
  return {
    name: 'arcom-backend',
    apply: 'serve',
    async configureServer(server) {
      const logger = server.config.logger
      const python = path.join(ROOT, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python')

      const start = async () => {
        if (stopping || child) return
        if (await backendUp()) {
          logger.info(`[arcom] serveur déjà actif sur ${BACKEND}`)
          return
        }
        if (!existsSync(python)) {
          logger.error(`[arcom] ${python} introuvable : crée l'environnement Python (voir README).`)
          return
        }
        const startedAt = Date.now()
        child = spawn(python, ['server.py', '--port', PORT], {
          cwd: ROOT,
          stdio: 'inherit',
          env: { ...process.env, PYTHONUNBUFFERED: '1', PYTHONIOENCODING: 'utf-8' },
        })
        child.on('exit', (code) => {
          child = undefined
          if (stopping) return
          quickExits = Date.now() - startedAt < 10_000 ? quickExits + 1 : 0
          if (quickExits >= 3) {
            logger.error(`[arcom] server.py s'arrête en boucle (code ${code}) : relance abandonnée.`)
            return
          }
          logger.warn(`[arcom] server.py s'est arrêté (code ${code}), relance dans 2 s…`)
          setTimeout(start, 2000)
        })
      }

      await start()
      process.once('exit', stop)
    },
  }
}

export default defineConfig({
  plugins: [arcomBackend()],
  server: {
    host: '127.0.0.1',
    proxy: {
      '/api': { target: BACKEND, ws: true },
    },
  },
})
