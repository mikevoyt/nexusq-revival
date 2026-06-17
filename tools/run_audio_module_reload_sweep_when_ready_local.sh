#!/bin/sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
NQ_HOST="${NQ_HOST:-192.168.86.38}"
NQ_USER="${NQ_USER:-root}"
WAIT_READY_TIMEOUT="${WAIT_READY_TIMEOUT:-0}"
WAIT_READY_INTERVAL="${WAIT_READY_INTERVAL:-5}"
NQ_DISCOVER_SSH="${NQ_DISCOVER_SSH:-1}"
NQ_DISCOVER_INTERVAL="${NQ_DISCOVER_INTERVAL:-60}"
NQ_DISCOVER_KNOWN_HOST="${NQ_DISCOVER_KNOWN_HOST:-$NQ_HOST}"
NQ_KNOWN_HOSTS="${NQ_KNOWN_HOSTS:-$HOME/.ssh/known_hosts}"
NQ_DISCOVER_CIDR="${NQ_DISCOVER_CIDR:-}"
SSH_CHECK_OPTS="${SSH_CHECK_OPTS:--o BatchMode=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=4}"

if [ "${NQ_SPEAKER_CONNECTED:-0}" != "1" ]; then
	cat >&2 <<EOF
Refusing to wait for playback because NQ_SPEAKER_CONNECTED=1 is not set.

After confirming the speaker is connected, run:

  NQ_SPEAKER_CONNECTED=1 FFMPEG_INPUT=':0' $0
EOF
	exit 2
fi

if [ "${REQUIRE_MIC:-1}" = "1" ] && [ -z "${FFMPEG_INPUT:-}" ]; then
	cat >&2 <<EOF
Refusing to wait for module sweep because REQUIRE_MIC=1 and FFMPEG_INPUT is empty.

List Mac inputs first if needed:

  LIST_AUDIO_INPUTS=1 tools/run_audio_legacydma_probe_local.sh

Then run with an avfoundation input, for example:

  NQ_SPEAKER_CONNECTED=1 FFMPEG_INPUT=':0' $0
EOF
	exit 2
fi

elapsed_seconds() {
	now="$(date +%s)"
	echo $((now - start))
}

ssh_ready() {
	ssh $SSH_CHECK_OPTS "$NQ_USER@$NQ_HOST" 'true' >/dev/null 2>&1
}

fastboot_ready() {
	command -v fastboot >/dev/null 2>&1 || return 1
	fastboot devices | awk 'NF >= 2 && $2 == "fastboot" { found=1 } END { exit found ? 0 : 1 }'
}

discover_cidr() {
	if [ -n "$NQ_DISCOVER_CIDR" ]; then
		echo "$NQ_DISCOVER_CIDR"
		return 0
	fi
	case "$NQ_DISCOVER_KNOWN_HOST" in
		[0-9]*.[0-9]*.[0-9]*.[0-9]*)
			echo "$NQ_DISCOVER_KNOWN_HOST" |
				awk -F. 'NF == 4 { printf "%s.%s.%s.0/24\n", $1, $2, $3 }'
			;;
		*)
			return 1
			;;
	esac
}

known_host_key() {
	command -v ssh-keygen >/dev/null 2>&1 || return 1
	[ -r "$NQ_KNOWN_HOSTS" ] || return 1
	ssh-keygen -F "$NQ_DISCOVER_KNOWN_HOST" -f "$NQ_KNOWN_HOSTS" 2>/dev/null |
		awk '$2 == "ssh-ed25519" { print $3; exit }'
}

scan_ssh_hosts() {
	cidr="$1"
	command -v nmap >/dev/null 2>&1 || return 1
	nmap -n -p 22 --open -oG - "$cidr" 2>/dev/null |
		awk '/Ports: 22\/open/ { print $2 }'
}

host_key_for_ip() {
	ip="$1"
	command -v ssh-keyscan >/dev/null 2>&1 || return 1
	ssh-keyscan -T 2 -t ed25519 "$ip" 2>/dev/null |
		awk '$2 == "ssh-ed25519" { print $3; exit }'
}

discover_ssh_host() {
	[ "$NQ_DISCOVER_SSH" = "1" ] || return 1
	known_key="$(known_host_key || true)"
	if [ -z "$known_key" ]; then
		echo "SSH discovery skipped: no known ed25519 key for $NQ_DISCOVER_KNOWN_HOST in $NQ_KNOWN_HOSTS" >&2
		return 1
	fi
	cidr="$(discover_cidr || true)"
	if [ -z "$cidr" ]; then
		echo "SSH discovery skipped: set NQ_DISCOVER_CIDR for non-IPv4 NQ_DISCOVER_KNOWN_HOST=$NQ_DISCOVER_KNOWN_HOST" >&2
		return 1
	fi

	echo "scanning $cidr for the known Nexus Q SSH host key from $NQ_DISCOVER_KNOWN_HOST" >&2
	for ip in $(scan_ssh_hosts "$cidr" || true); do
		[ "$ip" != "$NQ_HOST" ] || continue
		key="$(host_key_for_ip "$ip" || true)"
		if [ "$key" = "$known_key" ]; then
			echo "$ip"
			return 0
		fi
	done
	return 1
}

start="$(date +%s)"
last_discover=$((0 - NQ_DISCOVER_INTERVAL))
echo "waiting for Nexus Q on SSH $NQ_USER@$NQ_HOST or fastboot"
echo "wait_ready_timeout=$WAIT_READY_TIMEOUT wait_ready_interval=$WAIT_READY_INTERVAL discover_ssh=$NQ_DISCOVER_SSH discover_interval=$NQ_DISCOVER_INTERVAL"

while :; do
	if ssh_ready; then
		echo "Nexus Q is reachable over SSH; running module-reload sweep without fastboot boot"
		NQ_HOST="$NQ_HOST" NQ_USER="$NQ_USER" FASTBOOT_BOOT=0 \
			"$ROOT/tools/run_audio_module_reload_sweep_local.sh"
		exit $?
	fi

	if fastboot_ready; then
		echo "Nexus Q is in fastboot; booting DMA-modular image once, then using module reloads"
		NQ_HOST="$NQ_HOST" NQ_USER="$NQ_USER" FASTBOOT_BOOT=1 \
			"$ROOT/tools/run_audio_module_reload_sweep_local.sh"
		exit $?
	fi

	elapsed="$(elapsed_seconds)"
	if [ "$NQ_DISCOVER_SSH" = "1" ] &&
		[ $((elapsed - last_discover)) -ge "$NQ_DISCOVER_INTERVAL" ]; then
		last_discover="$elapsed"
		discovered_host="$(discover_ssh_host || true)"
		if [ -n "$discovered_host" ]; then
			echo "matched Nexus Q SSH host key at $discovered_host; switching NQ_HOST from $NQ_HOST"
			NQ_HOST="$discovered_host"
			if ssh_ready; then
				echo "Nexus Q is reachable over SSH at $NQ_HOST; running module-reload sweep without fastboot boot"
				NQ_HOST="$NQ_HOST" NQ_USER="$NQ_USER" FASTBOOT_BOOT=0 \
					"$ROOT/tools/run_audio_module_reload_sweep_local.sh"
				exit $?
			fi
		fi
	fi

	if [ "$WAIT_READY_TIMEOUT" -gt 0 ] && [ "$elapsed" -ge "$WAIT_READY_TIMEOUT" ]; then
		echo "timed out waiting for Nexus Q after ${elapsed}s" >&2
		exit 1
	fi

	sleep "$WAIT_READY_INTERVAL"
done
