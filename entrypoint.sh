#!/bin/sh
if [ -z "$UUID" ]; then
  export UUID=$(cat /proc/sys/kernel/random/uuid)
  echo "Generated UUID: $UUID"
fi
sed "s/UUID_PLACEHOLDER/$UUID/" /etc/xray/config.json.template > /etc/xray/config.json

cd /app
python3 main.py &
/usr/local/bin/xray -config /etc/xray/config.json
