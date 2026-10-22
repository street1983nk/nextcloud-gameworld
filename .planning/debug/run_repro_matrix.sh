#!/bin/sh
# Führt die Minimal-Reproduktion für alle Kontrollen aus, je RUNS Läufe.
# Wartet vor jedem Lauf, bis wenige Sockets in TIME_WAIT (deutsch: WARTEND)
# stehen, damit Port-Erschöpfung das Ergebnis nicht verfälscht.
# Aufruf: sh run_repro_matrix.sh [RUNS] [PYTHON] [CONFIG...]
set -u
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
RUNS=${1:-5}
PY=${2:-3.13}
shift 2 2>/dev/null || shift $#
if [ $# -eq 0 ]; then
	set -- "proactor thread" "proactor loop" "proactor close" "selector thread"
fi
wait_ports() {
	while [ "$(netstat -an | grep -c -E 'WARTEND|TIME_WAIT')" -gt 3000 ]; do
		sleep 10
	done
}
for config in "$@"; do
	set -- ${config}
	loop=$1
	drop=$2
	i=1
	while [ "${i}" -le "${RUNS}" ]; do
		wait_ports
		timeout 300 uv run --no-project --python "${PY}" python -I \
			"${HERE}/repro_proactor_offthread_cancel.py" --loop "${loop}" --drop "${drop}" \
			--rounds 20 --conns 25
		i=$((i + 1))
	done
done
