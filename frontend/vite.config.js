// Build of the Gameworld UI.
//
// AppAPI includes paths registered via set_script as a classic script:
// ScriptsService.php registers "proxy_js/<n>", ExAppUiMiddleware.php appends
// ".js" and redirects to /index.php/apps/app_api/proxy/gameworld/<path>.js.
// Nextcloud sets type="module" only for ".mjs" (lib/private/Template/functions.php).
// Therefore this produces exactly one file js/gameworld-main.js in IIFE format, with
// embedded CSS and without lazily loaded chunks.
import { createAppConfig } from '@nextcloud/vite-config'
import { fileURLToPath } from 'node:url'

const outDir = fileURLToPath(new URL('../js', import.meta.url))

export default createAppConfig(
	{ main: 'src/main.js' },
	{
		appName: 'gameworld',
		inlineCSS: true,
		// The plugin empties js/ relative to the working directory (frontend/);
		// emptying the real target is handled by emptyOutDir below.
		emptyOutputDirectory: false,
		// The REUSE license plugin runs out of memory with an outDir outside of frontend/
		// (JavaScript heap out of memory, measured).
		// The license data of the dependencies arrives in phase 6 with the image.
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
