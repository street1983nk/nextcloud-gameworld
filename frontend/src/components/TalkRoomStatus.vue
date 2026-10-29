<!-- Talk room of a world (TALK-01, D-17, D-19): link into Talk, switch "Nur lesen", takeover hints (UI-SPEC B4).
     Without Talk the management shows the hint once above the list, here nothing is shown. -->
<template>
	<div v-if="status && status.available" class="talk-room">
		<template v-if="status.has_room && !recreating">
			<a
				v-if="roomUrl"
				class="talk-room__link"
				:href="roomUrl"
				target="_blank"
				rel="noopener noreferrer">
				{{ t('admin.talk.open') }}
			</a>
			<NcCheckboxRadioSwitch
				type="switch"
				:model-value="readOnly"
				:disabled="saving"
				@update:model-value="toggle">
				{{ t('admin.talk.readOnly') }}
			</NcCheckboxRadioSwitch>
		</template>
		<span v-else class="talk-room__pending">{{ t('admin.talk.pending') }}</span>
		<NcNoteCard v-if="hint" type="info" class="talk-room__note">
			{{ hint }}
		</NcNoteCard>
		<template v-if="formerOwner">
			<div ref="formerCard" tabindex="-1" class="talk-room__focus">
				<NcNoteCard type="warning" class="talk-room__note">
					{{ formerOwner }}
				</NcNoteCard>
			</div>
			<NcButton
				ref="recreateButton"
				variant="secondary"
				class="talk-room__recreate"
				:disabled="saving"
				@click="askRecreate">
				<template v-if="recreating" #icon>
					<NcLoadingIcon :size="20" />
				</template>
				{{ t('admin.talk.recreate') }}
			</NcButton>
		</template>
		<NcNoteCard v-if="status.orphaned_token" type="info" class="talk-room__note">
			{{ orphanedBefore() }}<code>{{ orphanedCommand(status.orphaned_token) }}</code>{{ orphanedAfter() }}
		</NcNoteCard>
		<NcNoteCard v-if="success" type="success" class="talk-room__note">
			{{ success }}
		</NcNoteCard>
		<NcNoteCard v-if="notice" type="warning" class="talk-room__note">
			{{ notice }}
		</NcNoteCard>
		<NcNoteCard v-if="error" type="error" class="talk-room__note">
			{{ error }}
		</NcNoteCard>
		<NcDialog
			v-if="confirmRecreate"
			:open="true"
			:name="t('admin.talk.recreateTitle')"
			:message="recreateMessage"
			:buttons="recreateButtons"
			@update:open="onDialogOpen" />
	</div>
</template>

<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { generateUrl } from '@nextcloud/router'
import NcButton from '@nextcloud/vue/components/NcButton'
import NcCheckboxRadioSwitch from '@nextcloud/vue/components/NcCheckboxRadioSwitch'
import NcDialog from '@nextcloud/vue/components/NcDialog'
import NcLoadingIcon from '@nextcloud/vue/components/NcLoadingIcon'
import NcNoteCard from '@nextcloud/vue/components/NcNoteCard'
import { errorText, recreateTalkRoom, setTalkReadOnly } from '../api.js'
import {
	formerOwnerText,
	orphanedAfter,
	orphanedBefore,
	orphanedCommand,
	recreatedText,
	recreateQuestion,
	talkHint,
} from '../playtime.js'
import { t } from '../i18n/index.js'

const props = defineProps({
	// { id, name } of the world.
	world: { type: Object, required: true },
	// Entry of the world from GET /api/talk plus available; null while nothing is loaded.
	status: { type: Object, default: null },
})
const emit = defineEmits(['changed'])

const saving = ref(false)
const recreating = ref(false)
const confirmRecreate = ref(false)
const notice = ref('')
const success = ref('')
const error = ref('')
const formerCard = ref(null)
const recreateButton = ref(null)
// Own display of the switch, so that it does not jump back while saving.
const readOnly = ref(Boolean(props.status?.read_only))

watch(() => props.status?.read_only, (value) => {
	if (!saving.value) {
		readOnly.value = Boolean(value)
	}
})

const roomUrl = computed(() => (props.status?.token
	? generateUrl('/call/{token}', { token: props.status.token })
	: ''))

const hint = computed(() => talkHint(props.status))

// A former manager is still owner in Talk (D-19); only with a finished room.
const formerOwner = computed(() => (props.status?.has_room && props.status?.owner_not_admin
	? formerOwnerText(props.status.owner_display)
	: ''))

// Focus on the warning as soon as it appears; the button is right below it.
watch(formerOwner, async (text, before) => {
	if (text && !before) {
		await nextTick()
		formerCard.value?.focus()
	}
})

const recreateMessage = computed(() => recreateQuestion(props.world.name, props.status?.owner_display))

// Computed, so the labels follow the current language when the dialog renders.
const recreateButtons = computed(() => [
	{ label: t('admin.common.cancel'), variant: 'tertiary' },
	{
		label: t('admin.talk.recreate'),
		variant: 'error',
		callback: () => {
			confirmRecreate.value = false
			recreate()
		},
	},
])

function askRecreate() {
	if (saving.value) {
		return
	}
	success.value = ''
	error.value = ''
	confirmRecreate.value = true
}

function onDialogOpen(open) {
	if (!open) {
		confirmRecreate.value = false
	}
}

// Only after confirmation in the dialog: old room including history is gone, new room without the former manager.
async function recreate() {
	if (saving.value) {
		return
	}
	saving.value = true
	recreating.value = true
	notice.value = ''
	error.value = ''
	try {
		await recreateTalkRoom(props.world.id)
		success.value = recreatedText()
		emit('changed')
	} catch (err) {
		error.value = errorText(err)
		await nextTick()
		recreateButton.value?.$el?.focus()
	} finally {
		saving.value = false
		recreating.value = false
	}
}

async function toggle(on) {
	if (saving.value) {
		return
	}
	saving.value = true
	notice.value = ''
	error.value = ''
	success.value = ''
	readOnly.value = on
	try {
		const result = await setTalkReadOnly(props.world.id, on)
		readOnly.value = result.read_only
		if (result.applied === false) {
			notice.value = t('admin.talk.savedLater')
		}
		emit('changed')
	} catch (err) {
		readOnly.value = !on
		error.value = errorText(err)
	} finally {
		saving.value = false
	}
}
</script>

<style scoped>
.talk-room {
	display: flex;
	flex-direction: column;
	gap: 4px;
	margin-top: 8px;
}

.talk-room__link {
	color: var(--color-primary-element);
	text-decoration: underline;
}

.talk-room__pending {
	font-size: 0.9em;
	color: var(--color-text-maxcontrast);
}

.talk-room__note {
	margin: 4px 0 0;
}

.talk-room__focus:focus {
	outline: 2px solid var(--color-primary-element);
	outline-offset: 2px;
}

.talk-room__recreate {
	align-self: flex-start;
}

.talk-room code {
	overflow-wrap: anywhere;
}
</style>
