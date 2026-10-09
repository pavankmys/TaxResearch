#!/usr/bin/env bash
# One-time setup of the Compute Engine VM (Debian 13). Run as root: sudo bash vm-setup.sh
# Safe to run again. Installs rootless Podman and the Google Cloud CLI (if missing), creates the
# unprivileged "taxresearch" user that runs the containers, and prepares /opt/taxresearch.
# Stores and prints no secrets.

set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
	echo "ERROR: run this as root: sudo bash $0" >&2
	exit 1
fi

export DEBIAN_FRONTEND=noninteractive
APP_USER="taxresearch"
APP_DIR="/opt/taxresearch"

echo "1/6  Installing packages (podman, podman-compose, helpers)"
apt-get update -qq
apt-get install -y -qq podman podman-compose curl ca-certificates gnupg python3 uidmap

echo "2/6  Google Cloud CLI"
if command -v gcloud >/dev/null 2>&1; then
	echo "     already installed"
else
	install -d -m 755 /usr/share/keyrings
	curl -fsSL https://packages.cloud.google.com/apt/doc/apt-key.gpg |
		gpg --dearmor --yes -o /usr/share/keyrings/cloud.google.gpg
	echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main" \
		>/etc/apt/sources.list.d/google-cloud-sdk.list
	apt-get update -qq
	apt-get install -y -qq google-cloud-cli
fi

echo "3/6  User ${APP_USER}"
if id "$APP_USER" >/dev/null 2>&1; then
	echo "     already exists"
else
	useradd --create-home --shell /bin/bash "$APP_USER"
fi
# Rootless Podman needs a range of sub-user and sub-group IDs. useradd normally adds them.
if ! grep -q "^${APP_USER}:" /etc/subuid; then
	usermod --add-subuids 200000-265535 "$APP_USER"
fi
if ! grep -q "^${APP_USER}:" /etc/subgid; then
	usermod --add-subgids 200000-265535 "$APP_USER"
fi

echo "4/6  Keeping the user's services running without a login (linger)"
loginctl enable-linger "$APP_USER"
APP_UID="$(id -u "$APP_USER")"
systemctl start "user@${APP_UID}.service"

echo "5/6  Directory ${APP_DIR}"
install -d -o "$APP_USER" -g "$APP_USER" -m 750 "$APP_DIR"

echo "6/6  Restart containers after a reboot (podman-restart.service)"
export XDG_RUNTIME_DIR="/run/user/${APP_UID}"
enabled=0
for _ in 1 2 3 4 5 6 7 8 9 10; do
	if runuser -u "$APP_USER" -- env XDG_RUNTIME_DIR="$XDG_RUNTIME_DIR" \
		systemctl --user enable --now podman-restart.service >/dev/null 2>&1; then
		enabled=1
		break
	fi
	sleep 2
done
if [ "$enabled" -eq 1 ]; then
	echo "     enabled"
else
	echo "     WARNING: could not enable it automatically. Run on the VM:" >&2
	echo "       sudo -iu ${APP_USER} systemctl --user enable --now podman-restart.service" >&2
fi

echo
echo "Checking that rootless Podman works for ${APP_USER}..."
if runuser -u "$APP_USER" -- env XDG_RUNTIME_DIR="$XDG_RUNTIME_DIR" podman info >/dev/null 2>&1; then
	echo "     podman works"
else
	echo "     WARNING: 'podman info' failed for ${APP_USER}. Check: sudo -iu ${APP_USER} podman info" >&2
fi

cat <<EOF

VM setup finished.
Next: in GitHub, run the "Deploy to GCP" workflow. The first run also prepares the database.
EOF
