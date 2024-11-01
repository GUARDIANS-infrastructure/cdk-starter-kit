#!/bin/sh

# install git, docker, docker-compose
dnf update -y
dnf install -y git docker
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
git clone https://github.com/delocalizer/starter-kit-rems
cd starter-kit-rems/

# generate keys
python3 generate_jwks.py

# fetch secrets and other deployment config; set as env vars
export PUBLIC_URL=$(aws ssm get-parameter --name "/Rems/PublicURL" --query Parameter.Value --output text)
OIDC_CONFIG=$(aws secretsmanager get-secret-value --secret-id LSLogin.starter-kit-rems.oidc --query SecretString --output text | jq .)
export OIDC_METADATA_URL=$(jq '."oidc-metadata-url"' <<< $OIDC_CONFIG)
export OIDC_CLIENT_ID=$(jq '."oidc-client-id"' <<< $OIDC_CONFIG)
export OIDC_CLIENT_SECRET=$(jq '."oidc-client-secret"' <<< $OIDC_CONFIG)
DB_CONFIG=$(aws secretsmanager get-secret-value --secret-id starter-kit-rems.db --query SecretString --output text | jq .)
export DB_NAME=$(jq ."dbname" <<< $DB_CONFIG)
export DB_USER=$(jq ."username" <<< $DB_CONFIG)
export DB_PASSWORD=$(jq ."password" <<< $DB_CONFIG)

# configure the application
for cfgfile in "config.edn docker-compose.yml"; do
	cfgfile=config.edn
	tmpfile=$(mktemp)
	cp -a $cfgfile $tmpfile
	envsubst < $cfgfile > $tmpfile
	mv $tmpfile $cfgfile
done

# start the first time
docker-compose up -d db
docker-compose run --rm -e CMD="migrate" app
docker-compose up -d app

# [stop]
# docker-compose down

# [restart]
# docker-compose up -d
