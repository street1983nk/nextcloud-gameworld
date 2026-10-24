// Entry point: AppAPI's templates/embedded.php renders only <div id="content"></div>.
// The UI language follows the Nextcloud account language (html lang, read by
// @nextcloud/l10n); it is set before the app mounts, anything unsupported is English.
import { getLanguage } from '@nextcloud/l10n'
import { createApp } from 'vue'
import App from './App.vue'
import { normalizeLanguage, setLanguage } from './i18n/index.js'

setLanguage(normalizeLanguage(getLanguage()))

createApp(App).mount('#content')
