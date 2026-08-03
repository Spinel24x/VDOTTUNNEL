#!/bin/sh
if [ -z "$UUID" ]; then
  export UUID=$(cat /proc/sys/kernel/random/uuid)
  echo "Generated UUID: $UUID"
else
  echo "Using provided UUID: $UUID"
fi

# Replace UUID placeholder in Xray config
sed "s/UUID_PLACEHOLDER/$UUID/" /etc/xray/config.json.template > /etc/xray/config.json

# Start Python server (HTTP config page + SOCKS5 proxy)
cd /app
python3 main.py &

# Start Xray
/usr/local/bin/xray -config /etc/xray/config.json
