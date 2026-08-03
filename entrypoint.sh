#!/bin/sh
if [ -z "$UUID" ]; then
  UUID=$(cat /proc/sys/kernel/random/uuid)
  echo "Generated UUID: $UUID"
fi
sed "s/UUID_PLACEHOLDER/$UUID/" /etc/xray/config.json.template > /etc/xray/config.json

# Start Python HTTP+SOCKS5 server in background
cd /app
python3 main.py &

# Start Xray
/usr/local/bin/xray -config /etc/xray/config.json
