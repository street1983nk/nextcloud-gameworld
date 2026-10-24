// Area "admin" (en). Filled by plan 06-20 (TalkRoomStatus, OrphanSection, VerwalterGroupsSection, SetupCheck, JoinHostSettings, ReviewSetting, TimeZoneSetting).
// Flat table: every key starts with "admin."; values are plain text, never HTML.
export default {
	// Shared by several admin components
	'admin.common.cancel': 'Cancel',

	// VerwalterGroupsSection.vue
	'admin.groups.title': 'Manager groups',
	'admin.groups.alwaysIncluded': 'always included',
	'admin.groups.removeLabel': 'Remove group {gid}',
	'admin.groups.remove': 'Remove',
	'admin.groups.groupLabel': 'Group',
	'admin.groups.placeholder': 'Enter a group name',
	'admin.groups.add': 'Add group',

	// OrphanSection.vue
	'admin.orphans.title': 'Leftovers from earlier installations',
	'admin.orphans.chipContainer': 'Container',
	'admin.orphans.chipVolume': 'World data',
	'admin.orphans.removeContainerLabel': 'Remove container {name}',
	'admin.orphans.deleteVolumeLabel': 'Permanently delete world data {name}',
	'admin.orphans.remove': 'Remove',
	'admin.orphans.delete': 'Delete',
	'admin.orphans.rescanLabel': 'Search for leftovers again',
	'admin.orphans.rescan': 'Search again',
	'admin.orphans.docsLink': 'Guide to the cleanup script',
	'admin.orphans.removeContainer': 'Remove container',
	'admin.orphans.deleteVolumeTitle': 'Permanently delete world data',
	'admin.orphans.deleteVolume': 'Delete permanently',

	// TalkRoomStatus.vue
	'admin.talk.open': 'Open Talk room',
	'admin.talk.readOnly': 'Read only',
	'admin.talk.pending': 'Setting up the Talk room',
	'admin.talk.recreate': 'Recreate room',
	'admin.talk.recreateTitle': 'Recreate Talk room',
	'admin.talk.savedLater': 'Saved. Talk will apply it at the next sync.',
}
