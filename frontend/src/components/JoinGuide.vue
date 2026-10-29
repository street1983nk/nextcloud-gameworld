<!-- Instructions in five steps for the Luanti client (Pattern 7). Values only via text interpolation. -->
<template>
	<div class="join-guide">
		<h4>{{ t('kids.guide.title') }}</h4>
		<ol>
			<li>
				{{ installParts[0] }}<a href="https://www.luanti.org/downloads/" target="_blank" rel="noopener noreferrer">luanti.org</a>{{ installParts[1] }}
				{{ t('kids.guide.platforms') }}
				{{ t('kids.guide.noIos') }}
			</li>
			<li>{{ t('kids.guide.openTab') }}</li>
			<li>
				<template v-for="(part, index) in addressParts" :key="index">
					<strong v-if="part.value">{{ part.text }}</strong><template v-else>{{ part.text }}</template>
				</template>
			</li>
			<li>
				<template v-for="(part, index) in nameParts" :key="index">
					<strong v-if="part.value">{{ part.text }}</strong><template v-else>{{ part.text }}</template>
				</template>
				{{ t('kids.guide.case') }}
			</li>
			<li>{{ t('kids.guide.join') }}</li>
		</ol>
		<p class="join-guide__note">
			{{ t('kids.guide.note') }}
		</p>
	</div>
</template>

<script setup>
import { computed } from 'vue'
import { t } from '../i18n/index.js'

// The password itself is only in the card (hidden, copyable), not in the instruction text.
const props = defineProps({
	host: {
		type: String,
		required: true,
	},
	port: {
		type: Number,
		required: true,
	},
	playerName: {
		type: String,
		required: true,
	},
})

// Splits a translated sentence at its {placeholders}: text parts stay plain, values are
// marked for <strong>. Everything is rendered by text interpolation, never as HTML.
function highlight(key, values) {
	return t(key).split(/(\{[a-zA-Z]+\})/).filter((piece) => piece !== '').map((piece) => {
		const name = piece.match(/^\{([a-zA-Z]+)\}$/)?.[1]
		return name && name in values
			? { value: true, text: String(values[name]) }
			: { value: false, text: piece }
	})
}

// Sentence around the download link: text before and after {site}.
const installParts = computed(() => {
	const [before = '', after = ''] = t('kids.guide.install').split('{site}')
	return [before, after]
})
const addressParts = computed(() => highlight('kids.guide.address', { host: props.host, port: props.port }))
const nameParts = computed(() => highlight('kids.guide.name', { name: props.playerName }))
</script>

<style scoped>
.join-guide h4 {
	margin: 12px 0 4px;
}

.join-guide ol {
	padding-inline-start: 24px;
	list-style: decimal;
}

.join-guide li {
	margin-bottom: 6px;
}

.join-guide__note {
	color: var(--color-text-maxcontrast);
}
</style>
