#!/bin/bash
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y docker.io docker-compose-v2 unzip curl
systemctl enable --now docker
snap install aws-cli --classic
install -d -m 0700 /opt/renewables /opt/renewables/credentials /opt/renewables/backups
# No application secrets, tokens or AWS access keys in user-data.
