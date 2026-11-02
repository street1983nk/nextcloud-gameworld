// Area "admin" (en). Filled by plan 06-20 (TalkRoomStatus, OrphanSection, VerwalterGroupsSection, SetupCheck, JoinHostSettings, ReviewSetting, TimeZoneSetting).
// Flat table: every key starts with "admin."; values are plain text, never HTML.
export default {
	// Shared by several admin components
	'admin.common.cancel': 'Cancel',
	'admin.common.save': 'Save',

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

	// SetupCheck.vue
	'admin.setup.notReady': 'Gameworld is not ready yet',
	'admin.setup.unreachable': 'Gameworld is not responding. Please check the app in the Nextcloud settings.',
	'admin.setup.proxyWarning': 'Security notice about the Docker proxy',
	'admin.setup.recheck': 'Check again',
	'admin.setup.commandsHeading': 'Create the Docker proxy with one command',
	'admin.setup.commandsHint': 'Run the matching command on the server as a user with Docker rights, then choose "Check again". It creates the container gameworld-docker-proxy with exactly the settings from the guide, without a host port. If a container with this name already exists, remove it first with docker rm -f gameworld-docker-proxy. For your own Compose file the network gameworld must already exist (it is created by the HaRP Compose file).',
	'admin.setup.commandCompose': 'Own Compose file with HaRP (network gameworld)',
	'admin.setup.commandAio': 'Nextcloud All-in-One (network nextcloud-aio)',
	'admin.setup.copyCommand': 'Copy command',
	'admin.setup.copied': 'Copied',
	'admin.setup.copyFailed': 'Copying did not work. Select the command and copy it by hand.',
	'admin.setup.commandDetected': 'Network {network} (detected from the running Gameworld)',
	'admin.setup.commandOther': 'Other network: replace <docker-network> with the network name of your deploy daemon',
	'admin.setup.networkNotDetected': 'The Docker network of Gameworld could not be detected automatically. Use the command for your installation. If your deploy daemon runs in another network, use the last command and replace the placeholder <docker-network>.',
	'admin.setup.downloadCompose': 'Download Compose file',
	'admin.setup.composeHint': 'Instead of the command you can also use the Compose file: save it and start it on the server with docker compose -f gameworld-docker-proxy.yaml up -d. It contains the same settings, without a host port.',
	'admin.setup.autoRecheck': 'Gameworld checks again on its own at regular intervals and turns green as soon as the Docker proxy answers.',
	'admin.setup.firewallHeading': 'Firewall: open UDP ports {range} in the home network only',
	'admin.setup.firewallHint': 'Run the command for your firewall on the server and first replace <lan-network> with your home network in the form network address/prefix length, as your router shows it. No port forwarding in the router and no UPnP: worlds are meant for the home network only.',
	'admin.setup.firewallUfw': 'ufw (for example Ubuntu, Debian)',
	'admin.setup.firewallFirewalld': 'firewalld (for example Fedora, RHEL, openSUSE)',

	// JoinHostSettings.vue
	'admin.joinHost.title': 'Settings',
	'admin.joinHost.label': 'Player address',
	'admin.joinHost.helper': 'Leave empty: Gameworld uses the address you are opening Nextcloud with right now.',
	'admin.joinHost.effective': 'Players see this address:',
	'admin.joinHost.loopback': 'Other devices cannot reach this address. Enter the address of the home server in your home network.',
	'admin.joinHost.internet': 'This looks like an internet address. Games run over UDP and not through a web tunnel; enter the address of the home server in your home network.',
	'admin.joinHost.saved': 'Saved. Players see the new address the next time they refresh.',

	// ReviewSetting.vue
	'admin.review.title': 'Daily summary in the evening',
	'admin.review.hint': 'Applies only to you. On a day without playtime, no message is sent.',
	'admin.review.time': 'Time',
	'admin.review.unsaved': 'Not saved yet.',
	'admin.review.loadError': 'The setting could not be loaded: {error}',
	'admin.review.savedAt': 'Saved. The summary arrives at {time}.',
	'admin.review.savedOff': 'Saved. You will not receive a daily summary.',

	// TimeZoneSetting.vue
	'admin.timeZone.title': 'Time zone for playtimes',
	'admin.timeZone.hint': 'Playtimes, time windows and holidays apply in this time zone.',
	'admin.timeZone.useBrowser': 'Use this browser\'s time zone',
	'admin.timeZone.browserUses': 'This browser uses {zone}.',
	'admin.timeZone.savedLater': 'Saved. Worlds that cannot be reached right now apply the time zone at their next start.',
	'admin.timeZone.saved': 'Saved. Playtimes are now calculated in this time zone.',
}
