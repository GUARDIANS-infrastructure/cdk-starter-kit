#!/bin/sh

# install necessaries
dnf update -y
dnf install -y git docker pwgen
systemctl enable docker
systemctl start docker
curl -L https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m) -o /usr/local/bin/docker-compose
chmod +x /usr/local/bin/docker-compose

# install authlib for generate_jwks.py
curl -O https://bootstrap.pypa.io/get-pip.py
python3 get-pip.py
pip install authlib

# clone the REMS repo
cd /opt
git clone https://github.com/GUARDIANS-infrastructure/starter-kit-rems
cd starter-kit-rems/

# generate keys
python3 generate_jwks.py

# Configuration requires:
# 1. '/Rems/PublicURL' SSM parameter (set in the CDK script)
# 2. '/Rems/OidcSecName' SSM parameter (set in CDK script)
# 3. The named AWS Secrets Manager entry (type: other) with 3 key-vals:
# - 'oidc-metadata-url'
# - 'oidc-client-id'
# - 'oidc-client-secret'.

# fetch secrets and other deployment config; set as env vars.
oidc_sec_name=$(aws ssm get-parameter --name "/Rems/OidcSecName" --query Parameter.Value --output text)
oidc_config=$(aws secretsmanager get-secret-value --secret-id $oidc_sec_name --query SecretString --output text | jq .)
export OIDC_METADATA_URL=$(jq -r '."oidc-metadata-url"' <<< $oidc_config)
export OIDC_CLIENT_ID=$(jq -r '."oidc-client-id"' <<< $oidc_config)
export OIDC_CLIENT_SECRET=$(jq -r '."oidc-client-secret"' <<< $oidc_config)
export DB_NAME=remsdb
export DB_USER=rems
export DB_PASSWORD=$(pwgen)
export PUBLIC_URL=$(aws ssm get-parameter --name "/Rems/PublicURL" --query Parameter.Value --output text)

# configure the application
for cfgfile in config.edn docker-compose.yml; do
	tmpfile=$(mktemp)
	\cp -f --preserve=all --attributes-only $cfgfile $tmpfile
	envsubst < $cfgfile > $tmpfile
	\mv -f $tmpfile $cfgfile
done

# start the first time
docker-compose up -d db
docker-compose run --rm -e CMD="migrate" app
docker-compose up -d app

# [stop]
# docker-compose down

# [restart]
# docker-compose up -d
