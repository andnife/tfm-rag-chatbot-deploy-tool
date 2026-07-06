#!/usr/bin/env bash
# Grant (or revoke) application superadmin to a user by email.
#
# Usage:
#   bash scripts/grant-superadmin.sh <email>            # grant
#   bash scripts/grant-superadmin.sh <email> --revoke   # revoke
#
# Superadmin is DB-seeded only (no API can set it). After flipping the flag,
# the user must log in again to get a token carrying the new claim.
set -euo pipefail

EMAIL="${1:?usage: grant-superadmin.sh <email> [--revoke]}"
VALUE="true"
[[ "${2:-}" == "--revoke" ]] && VALUE="false"

docker exec -e PGPASSWORD=tfm tfm-rag-postgres-1 psql -U tfm -d tfm_rag \
  -c "UPDATE users SET is_superadmin=${VALUE} WHERE email='${EMAIL}';"

echo "set is_superadmin=${VALUE} for ${EMAIL} (re-login required for new token)"
