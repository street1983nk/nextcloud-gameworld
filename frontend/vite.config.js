// Build der Gameworld-Oberfläche.
//
// AppAPI bindet per set_script registrierte Pfade als klassisches Skript ein:
// ScriptsService.php registriert "proxy_js/<n>", ExAppUiMiddleware.php hängt
// ".js" an und leitet auf /index.php/apps/app_api/proxy/gameworld/<pfad>.js um.
// Nextcloud setzt type="module" nur bei ".mjs" (lib/private/Template/functions.php).
// Darum entsteht hier genau eine Datei js/gameworld-main.js im Format IIFE, mit
// eingebettetem CSS und ohne nachgeladene Chunks.
import { createAppConfig } from '@nextcloud/vite-config'
import { fileURLToPath } from 'node:url'

const outDir = fileURLToPath(new URL('../js', import.meta.url))

export default createAppConfig(
	{ main: 'src/main.js' },
	{
		appName: 'gameworld',
		inlineCSS: true,
		// Das Plugin leert js/ relativ zum Arbeitsverzeichnis (frontend/);
		// das Leeren des echten Ziels übernimmt emptyOutDir unten.
		emptyOutputDirectory: false,
		// Das REUSE-Lizenz-Plugin läuft mit einem outDir außerhalb von frontend/
		// in einen Speicherüberlauf (JavaScript heap out of memory, gemessen).
		// Die Lizenzangaben der Abhängigkeiten kommen in Phase 6 mit dem Image.
		extractLicenseInformation: false,
		config: {
			build: {
				outDir,
				emptyOutDir: true,
				rollupOptions: {
					output: {
						format: 'iife',
						inlineDynamicImports: true,
						entryFileNames: 'gameworld-main.js',
					},
				},
			},
		},
	},
)
