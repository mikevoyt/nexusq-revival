#!/bin/sh
set -eu

NQ_HOST="${NQ_HOST:-192.168.86.38}"
NQ_USER="${NQ_USER:-root}"
NQ_WATCHDOG_TIMEOUT="${NQ_WATCHDOG_TIMEOUT:-60}"
NQ_WATCHDOG_INTERVAL="${NQ_WATCHDOG_INTERVAL:-20}"
SSH_OPTS="${SSH_OPTS:--o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=10}"

ssh $SSH_OPTS "$NQ_USER@$NQ_HOST" \
	"nq_watchdog_timeout='$NQ_WATCHDOG_TIMEOUT' nq_watchdog_interval='$NQ_WATCHDOG_INTERVAL' sh -s" <<'REMOTE'
set -eu

mkdir -p /run

for f in /sys/class/watchdog/watchdog0/timeout /sys/class/watchdog/watchdog0/nowayout; do
	[ -w "$f" ] || continue
	case "$f" in
		*/timeout) (echo "$nq_watchdog_timeout" >"$f") 2>/dev/null || true ;;
		*/nowayout) (echo 1 >"$f") 2>/dev/null || true ;;
	esac
done

find_watchdog_holder() {
	for proc in /proc/[0-9]*; do
		[ -d "$proc/fd" ] || continue
		for fd in "$proc"/fd/*; do
			target="$(readlink "$fd" 2>/dev/null || true)"
			case "$target" in
				*/watchdog|/dev/watchdog*)
					pid="${proc##*/}"
					cmd="$(tr '\0' ' ' < "$proc/cmdline" 2>/dev/null || true)"
					printf '%s %s\n' "$pid" "$cmd"
					return 0
					;;
			esac
		done
	done
	return 1
}

if holder="$(find_watchdog_holder)"; then
	echo "nq root watchdog feeder already active pid=${holder%% *} cmd=${holder#* }"
	rm -f /run/nq-watchdog-root.pid
else
	if [ -s /run/nq-watchdog-root.pid ]; then
		kill "$(cat /run/nq-watchdog-root.pid)" 2>/dev/null || true
		rm -f /run/nq-watchdog-root.pid
	fi

	cat >/run/nq-watchdog-root-feeder <<'SCRIPT'
#!/bin/sh

timeout="${1:-60}"
interval="${2:-20}"

case "$timeout" in
	""|*[!0-9]*) timeout=60 ;;
esac
case "$interval" in
	""|*[!0-9]*) interval=20 ;;
esac
[ "$interval" -ge 5 ] || interval=5

echo "nq root watchdog feeder starting timeout=${timeout}s interval=${interval}s" >/dev/console 2>/dev/null || true

while true; do
	if [ -w /sys/class/watchdog/watchdog0/timeout ]; then
		(echo "$timeout" >/sys/class/watchdog/watchdog0/timeout) 2>/dev/null || true
	fi
	if [ -w /sys/class/watchdog/watchdog0/nowayout ]; then
		(echo 1 >/sys/class/watchdog/watchdog0/nowayout) 2>/dev/null || true
	fi

	/bin/sh -c 'echo "nq root watchdog feeder armed" >/dev/console 2>/dev/null || true; while true; do echo 1; sleep "$1"; done > /dev/watchdog' feeder "$interval"
	echo "watchdog open/feed child exited rc=$?" >>/run/nq-watchdog-root-feeder.log

	sleep 5
done
SCRIPT
	chmod 755 /run/nq-watchdog-root-feeder

	/run/nq-watchdog-root-feeder "$nq_watchdog_timeout" "$nq_watchdog_interval" >/run/nq-watchdog-root-feeder.log 2>&1 &
	echo "$!" >/run/nq-watchdog-root.pid

	echo "nq root watchdog feeder launcher pid=$(cat /run/nq-watchdog-root.pid)"
fi

for f in /sys/class/watchdog/watchdog*/state /sys/class/watchdog/watchdog*/timeout /sys/class/watchdog/watchdog*/nowayout; do
	[ -r "$f" ] || continue
	echo "$f=$(cat "$f" 2>/dev/null || true)"
done
REMOTE
