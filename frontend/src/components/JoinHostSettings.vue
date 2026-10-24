<!-- Einstellung der Eltern: Adresse, die Spieler in Luanti eintragen (join_host, Pattern 7). -->
<template>
	<section class="join-host">
		<h3>{{ t('admin.joinHost.title') }}</h3>
		<form class="join-host__form" @submit.prevent="save">
			<NcTextField
				v-model="value"
				:label="t('admin.joinHost.label')"
				:maxlength="253"
				:disabled="loading || saving"
				:helper-text="t('admin.joinHost.helper')" />
			<NcButton type="submit" variant="primary" :disabled="loading || saving || !changed">
				<template v-if="saving" #icon>
					<NcLoadingIcon :size="20" />
				</template>
				{{ t('admin.common.save') }}
			</NcButton>
		</form>
		<p class="join-host__effective">
			{{ t('admin.joinHost.effective') }} <strong>{{ effective }}</strong>
		</p>

		<NcNoteCard v-if="warning === 'loopback'" type="warning">
			{{ t('admin.joinHost.loopback') }}
		</NcNoteCard>
		<NcNoteCard v-else-if="warning === 'internet'" type="warning">
			{{ t('admin.joinHost.internet') }}
		</NcNoteCard>
		<NcNoteCard v-if="notice" type="success">
			{{ notice }}
		</NcNoteCard>
		<NcNoteCard v-if="error" type="error">
			{{ error }}
		</NcNoteCard>
	</section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import NcButton from '@nextcloud/vue/components/NcButton'
import NcLoadingIcon from '@nextcloud/vue/components/NcLoadingIcon'
import NcNoteCard from '@nextcloud/vue/components/NcNoteCard'
import NcTextField from '@nextcloud/vue/components/NcTextField'
import { errorText, getSettings, saveSettings } from '../api.js'
import { t } from '../i18n/index.js'

// Endungen typischer Heimnetz-Namen; sonst gilt ein Name mit Punkt als Internetadresse.
const HOME_SUFFIXES = ['.local', '.lan', '.home', '.fritz.box']

const value = ref('')
const saved = ref('')
const loading = ref(true)
const saving = ref(false)
const notice = ref('')
const error = ref('')

const changed = computed(() => value.value.trim() !== saved.value)
// Wirksame Adresse: Eingabe, sonst Hostname dieses Browsers (wie in der Spieleransicht).
const effective = computed(() => value.value.trim() || window.location.hostname)
const warning = computed(() => classify(effective.value))

function ipv4(host) {
	const match = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/.exec(host)
	return match ? match.slice(1).map(Number) : null
}

function isPrivateIpv4(parts) {
	const [a, b] = parts
	return a === 10 || (a === 172 && b >= 16 && b <= 31) || (a === 192 && b === 168)
}

// 'loopback', 'internet' oder '' (kein Hinweis).
function classify(rawHost) {
	const host = rawHost.toLowerCase().replace(/^\[|\]$/g, '')
	const parts = ipv4(host)
	if (host === 'localhost' || host.endsWith('.localhost') || host === '::1' || (parts && parts[0] === 127)) {
		return 'loopback'
	}
	if (!host.includes('.')) {
		return ''
	}
	if (parts) {
		return isPrivateIpv4(parts) ? '' : 'internet'
	}
	return HOME_SUFFIXES.some((suffix) => host.endsWith(suffix)) ? '' : 'internet'
}

async function load() {
	try {
		const settings = await getSettings()
		saved.value = settings.join_host ?? ''
		value.value = saved.value
		error.value = ''
	} catch (err) {
		error.value = errorText(err)
	} finally {
		loading.value = false
	}
}

async function save() {
	if (!changed.value || saving.value) {
		return
	}
	saving.value = true
	notice.value = ''
	error.value = ''
	try {
		const settings = await saveSettings(value.value.trim())
		saved.value = settings.join_host
		value.value = settings.join_host
		notice.value = t('admin.joinHost.saved')
	} catch (err) {
		error.value = errorText(err)
	} finally {
		saving.value = false
	}
}

onMounted(load)
</script>

<style scoped>
.join-host {
	margin-top: 32px;
}

.join-host__form {
	display: flex;
	gap: 12px;
	align-items: flex-end;
}

.join-host__form button {
	flex-shrink: 0;
}

.join-host__effective {
	margin: 8px 0;
	color: var(--color-text-maxcontrast);
}
</style>
