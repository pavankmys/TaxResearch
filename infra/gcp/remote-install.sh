#!/usr/bin/env bash
# Runs ON THE VM, started by the deploy workflow after it has copied the deployment files.
# Installs them into /opt/taxresearch and runs the deploy as the taxresearch user.
# Usage: remote-install.sh <tag>

set -euo pipefail

tag="${1:-}"
if ! [[ "$tag" =~ ^[A-Za-z0-9._-]{1,128}$ ]]; then
	echo "ERROR: invalid or missing tag" >&2
	exit 1
fi

src="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
dest="${TAXRESEARCH_DIR:-/opt/taxresearch}"

for f in compose.gcp.yaml deploy.sh verify.sh db-init.sh db-init.sql; do
	if [ ! -f "$src/$f" ]; then
		echo "ERROR: $f was not copied to the VM" >&2
		exit 1
	fi
done

sudo install -d -o taxresearch -g taxresearch -m 750 "$dest"
sudo install -o taxresearch -g taxresearch -m 640 "$src/compose.gcp.yaml" "$dest/compose.gcp.yaml"
sudo install -o taxresearch -g taxresearch -m 750 "$src/deploy.sh" "$dest/deploy.sh"
sudo install -o taxresearch -g taxresearch -m 750 "$src/verify.sh" "$dest/verify.sh"
sudo install -o taxresearch -g taxresearch -m 750 "$src/db-init.sh" "$dest/db-init.sh"
sudo install -o taxresearch -g taxresearch -m 640 "$src/db-init.sql" "$dest/db-init.sql"

# The copied files are no longer needed in the login user's home.
rm -rf "$src"

exec sudo -iu taxresearch "$dest/deploy.sh" "$tag"
