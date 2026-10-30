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
				<div v-for="command in proxyCommands" :key="command.id" class="setup-check__command-entry">
					<p class="setup-check__command-label">
						{{ t(COMMAND_LABELS[command.id] ?? 'admin.setup.commandCompose') }}
					</p>
					<pre class="setup-check__command"><code>{{ command.command }}</code></pre>
					<NcButton variant="secondary" @click="copyCommand(command)">
						{{ copiedId === command.id ? t('admin.setup.copied') : t('admin.setup.copyCommand') }}
					</NcButton>
				</div>
				<p v-if="copyError" class="setup-check__copy-error">
					{{ copyError }}
				</p>
			</div>
		</NcNoteCard>

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
	</div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import NcButton from '@nextcloud/vue/components/NcButton'
import NcLoadingIcon from '@nextcloud/vue/components/NcLoadingIcon'
import NcNoteCard from '@nextcloud/vue/components/NcNoteCard'
import { getSetupCheck } from '../api.js'
import { t } from '../i18n/index.js'

// checked: after every check run (success or failure), so that the world list follows.
const emit = defineEmits(['update:ok', 'checked'])

const result = ref(null)
const checking = ref(false)
const unreachable = ref(false)

const failed = computed(() => (result.value?.items ?? []).filter((item) => !item.ok))
const errors = computed(() => failed.value.filter((item) => item.severity === 'error'))
const warnings = computed(() => failed.value.filter((item) => item.severity === 'warning'))
// Commands come ready-made from the backend (single source of truth); never built here.
const proxyCommands = computed(() => result.value?.proxy_commands ?? [])

const COMMAND_LABELS = {
	compose: 'admin.setup.commandCompose',
	aio: 'admin.setup.commandAio',
}
const copiedId = ref('')
const copyError = ref('')
let copiedTimer = null

async function copyCommand(command) {
	copyError.value = ''
	try {
		await navigator.clipboard.writeText(command.command)
		copiedId.value = command.id
		clearTimeout(copiedTimer)
		copiedTimer = setTimeout(() => {
			copiedId.value = ''
		}, 2000)
	} catch {
		copyError.value = t('admin.setup.copyFailed')
	}
}

async function check() {
	if (checking.value) {
		return
	}
	checking.value = true
	try {
		result.value = await getSetupCheck()
		unreachable.value = false
		emit('update:ok', result.value.ok === true)
	} catch {
		result.value = null
		unreachable.value = true
		emit('update:ok', false)
	} finally {
		checking.value = false
		emit('checked')
	}
}

onMounted(check)
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

.setup-check__copy-error {
	margin-top: 8px;
}
</style>
