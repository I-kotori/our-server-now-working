#!/bin/sh
set -eu
release=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
for file in server.py index.html favicon.svg dongguk-status.service; do test -f "$release/$file"; done
getent passwd dongguk-status >/dev/null || useradd --system --user-group --home-dir /nonexistent --shell /usr/sbin/nologin dongguk-status
install -d -m755 -o root -g root /opt/dongguk-status
install -d -m700 -o dongguk-status -g dongguk-status /var/lib/dongguk-status
install -m644 -o root -g root "$release/server.py" "$release/index.html" "$release/favicon.svg" /opt/dongguk-status/
install -m644 "$release/dongguk-status.service" /etc/systemd/system/dongguk-status.service
systemctl daemon-reload
systemctl enable --now dongguk-status
systemctl restart dongguk-status
systemctl is-active dongguk-status
