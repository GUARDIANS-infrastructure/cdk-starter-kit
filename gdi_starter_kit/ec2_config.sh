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

# [edit the config.edn for auth setup]

# start the first time
# docker-compose up -d db
# docker-compose run --rm -e CMD="migrate" app
# docker-compose up -d app

# [stop]
# docker-compose down

# [restart]
# docker-compose up -d
