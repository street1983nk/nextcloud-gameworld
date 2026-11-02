<template>
	<div class="setup-check">
		<NcLoadingIcon v-if="checking && !result" :size="20" />

		<NcNoteCard v-if="unreachable" type="error" :heading="t('admin.setup.notReady')">
			<p>{{ t('admin.setup.unreachable') }}</p>
		</NcNoteCard>

		<NcNoteCard v-if="errors.length > 0" type="error" :heading="t('admin.setup.notReady')">
			<ul class="setup-check__list">
				<li v-for="item in errors" :key="item.id">
					{{ item.message }}
				</li>
			</ul>
			<div v-if="proxyCommands.length > 0" class="setup-check__commands">
				<p class="setup-check__commands-heading">
					<strong>{{ t('admin.setup.commandsHeading') }}</strong>
				</p>
				<p>{{ t('admin.setup.commandsHint') }}</p>
				<p v-if="!networkDetected" class="setup-check__not-detected">
					{{ t('admin.setup.networkNotDetected') }}
				</p>
				<div v-for="command in proxyCommands" :key="command.id" class="setup-check__command-entry">
					<p class="setup-check__command-label">
						{{ commandLabel(command) }}
					</p>
					<pre class="setup-check__command"><code>{{ command.command }}</code></pre>
					<div class="setup-check__command-actions">
						<NcButton variant="secondary" @click="copyCommand(command.command, `proxy-${command.id}`)">
							{{ copiedId === `proxy-${command.id}` ? t('admin.setup.copied') : t('admin.setup.copyCommand') }}
						</NcButton>
						<NcButton variant="secondary" @click="downloadCompose(command)">
							{{ t('admin.setup.downloadCompose') }}
						</NcButton>
					</div>
				</div>
				<p class="setup-check__compose-hint">
					{{ t('admin.setup.composeHint') }}
				</p>
				<p v-if="copyError.startsWith('proxy-')" class="setup-check__copy-error">
					{{ t('admin.setup.copyFailed') }}
				</p>
			</div>
		</NcNoteCard>

		<p v-if="polling && (unreachable || errors.length > 0)" class="setup-check__auto">
			{{ t('admin.setup.autoRecheck') }}
		</p>

		<NcNoteCard v-if="warnings.length > 0" type="warning" :heading="t('admin.setup.proxyWarning')">
			<ul class="setup-check__list">
				<li v-for="item in warnings" :key="item.id">
					{{ item.message }}
				</li>
			</ul>
		</NcNoteCard>

		<NcButton v-if="unreachable || errors.length > 0 || warnings.length > 0" :disabled="checking" @click="check">
			<template v-if="checking" #icon>
				<NcLoadingIcon :size="20" />
			</template>
			{{ t('admin.setup.recheck') }}
		</NcButton>

		<details v-if="firewall" class="setup-check__firewall">
			<summary>{{ t('admin.setup.firewallHeading', { range: firewall.port_range }) }}</summary>
			<p>{{ t('admin.setup.firewallHint') }}</p>
			<div v-for="command in firewall.commands" :key="command.id" class="setup-check__command-entry">
				<p class="setup-check__command-label">
					{{ t(FIREWALL_LABELS[command.id] ?? 'admin.setup.firewallUfw') }}
				</p>
				<pre class="setup-check__command"><code>{{ command.command }}</code></pre>
				<NcButton variant="secondary" @click="copyCommand(command.command, `fw-${command.id}`)">
					{{ copiedId === `fw-${command.id}` ? t('admin.setup.copied') : t('admin.setup.copyCommand') }}
				</NcButton>
			</div>
			<p v-if="copyError.startsWith('fw-')" class="setup-check__copy-error">
				{{ t('admin.setup.copyFailed') }}
			</p>
		</details>
	</div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import NcButton from '@nextcloud/vue/components/NcButton'
import NcLoadingIcon from '@nextcloud/vue/components/NcLoadingIcon'
import NcNoteCard from '@nextcloud/vue/components/NcNoteCard'
import { getSetupCheck } from '../api.js'
import { t } from '../i18n/index.js'

// checked: after the first run, every manual run and every automatic run that changed
// the ok state, so that the world list follows without reloading every 15 s.
const emit = defineEmits(['update:ok', 'checked'])

const result = ref(null)
const checking = ref(false)
const unreachable = ref(false)

const failed = computed(() => (result.value?.items ?? []).filter((item) => !item.ok))
const errors = computed(() => failed.value.filter((item) => item.severity === 'error'))
const warnings = computed(() => failed.value.filter((item) => item.severity === 'warning'))
// Commands and Compose text come ready-made from the backend (single source of truth);
// never built here.
const proxyCommands = computed(() => result.value?.proxy_commands ?? [])
const networkDetected = computed(() => proxyCommands.value.some((command) => command.id === 'detected'))
const firewall = computed(() => result.value?.firewall ?? null)

const COMMAND_LABELS = {
	detected: 'admin.setup.commandDetected',
	compose: 'admin.setup.commandCompose',
	aio: 'admin.setup.commandAio',
	other: 'admin.setup.commandOther',
}
const FIREWALL_LABELS = {
	ufw: 'admin.setup.firewallUfw',
	firewalld: 'admin.setup.firewallFirewalld',
}
const COMPOSE_FILE_NAME = 'gameworld-docker-proxy.yaml'

function commandLabel(command) {
	return t(COMMAND_LABELS[command.id] ?? 'admin.setup.commandOther', { network: command.network })
}

const copiedId = ref('')
// Key ("proxy-..." or "fw-...") of the command whose copy failed; the hint shows in its section.
const copyError = ref('')
let copiedTimer = null

async function copyCommand(text, key) {
	copyError.value = ''
	try {
		await navigator.clipboard.writeText(text)
		copiedId.value = key
		clearTimeout(copiedTimer)
		copiedTimer = setTimeout(() => {
			copiedId.value = ''
		}, 2000)
	} catch {
		copyError.value = key
	}
}

function downloadCompose(command) {
	const url = URL.createObjectURL(new Blob([command.compose], { type: 'text/yaml' }))
	const link = document.createElement('a')
	link.href = url
	link.download = COMPOSE_FILE_NAME
	link.rel = 'noopener'
	document.body.appendChild(link)
	link.click()
	link.remove()
	URL.revokeObjectURL(url)
}

// Self re-check while not green: a setTimeout chain (never an interval), 15 s for the
// first 20 automatic runs, then 60 s. Stops when green, while the tab is hidden and
// when the view is left.
const AUTO_FAST_MS = 15000
const AUTO_SLOW_MS = 60000
const AUTO_FAST_RUNS = 20
const polling = ref(false)
let autoTimer = null
let autoRuns = 0
let lastOk = null
let stopped = false

function isGreen() {
	return !unreachable.value && result.value?.ok === true
}

function clearAuto() {
	clearTimeout(autoTimer)
	autoTimer = null
	polling.value = false
}

function scheduleAuto() {
	clearAuto()
	if (stopped || document.hidden || isGreen()) {
		return
	}
	polling.value = true
	autoTimer = setTimeout(() => {
		autoTimer = null
		autoRuns += 1
		runCheck(true)
	}, autoRuns < AUTO_FAST_RUNS ? AUTO_FAST_MS : AUTO_SLOW_MS)
}

async function runCheck(automatic) {
	if (checking.value) {
		return
	}
	checking.value = true
	let ok = false
	try {
		result.value = await getSetupCheck()
		unreachable.value = false
		ok = result.value.ok === true
	} catch {
		result.value = null
		unreachable.value = true
	} finally {
		checking.value = false
	}
	if (stopped) {
		return
	}
	emit('update:ok', ok)
	if (!automatic || ok !== lastOk) {
		emit('checked')
	}
	lastOk = ok
	scheduleAuto()
}

// Initial run and "Check again": resets the automatic counter.
function check() {
	autoRuns = 0
	return runCheck(false)
}

function onVisibilityChange() {
	if (document.hidden) {
		clearAuto()
	} else if (!stopped && !isGreen()) {
		runCheck(true)
	}
}

onMounted(() => {
	document.addEventListener('visibilitychange', onVisibilityChange)
	check()
})

onBeforeUnmount(() => {
	stopped = true
	clearAuto()
	clearTimeout(copiedTimer)
	document.removeEventListener('visibilitychange', onVisibilityChange)
})
</script>

<style scoped>
.setup-check {
	margin-bottom: 16px;
}

.setup-check__list {
	margin: 0;
	padding-inline-start: 20px;
	list-style: disc;
	/* The guide link in the messages is one long word; let it break at 390 px. */
	overflow-wrap: anywhere;
}

/* The note card content is a flex child; without min-width: 0 it grows to its longest word. */
.setup-check :deep(.notecard > div) {
	min-width: 0;
}

.setup-check__commands {
	min-width: 0;
	margin-top: 12px;
}

.setup-check__commands-heading {
	margin-bottom: 4px;
}

.setup-check__command-entry {
	min-width: 0;
	margin-top: 12px;
}

.setup-check__command-label {
	margin-bottom: 4px;
	font-weight: bold;
}

/* Wrap instead of scrolling sideways: the whole command stays visible, even at 390 px. */
.setup-check__command {
	box-sizing: border-box;
	max-width: 100%;
	margin: 0 0 8px;
	padding: 8px;
	overflow-x: hidden;
	font-family: var(--font-face-monospace, monospace);
	font-size: 13px;
	white-space: pre-wrap;
	overflow-wrap: anywhere;
	background: var(--color-background-dark);
	border-radius: var(--border-radius);
}

.setup-check__command-actions {
	display: flex;
	flex-wrap: wrap;
	gap: 8px;
}

.setup-check__not-detected,
.setup-check__compose-hint {
	margin-top: 8px;
}

.setup-check__auto {
	margin: 4px 0 12px;
	color: var(--color-text-maxcontrast);
}

.setup-check__firewall {
	min-width: 0;
	margin-top: 16px;
	overflow-wrap: anywhere;
}

.setup-check__firewall > summary {
	cursor: pointer;
	font-weight: bold;
}

.setup-check__firewall > p {
	margin-top: 8px;
}

.setup-check__copy-error {
	margin-top: 8px;
}
</style>
