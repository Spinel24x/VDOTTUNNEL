#!/bin/sh
if [ -z "$UUID" ]; then
  UUID=$(cat /proc/sys/kernel/random/uuid)
  echo "Generated UUID: $UUID"
fi
# Save UUID for Python to read
echo "$UUID" > /app/uuid.txt

# Replace in Xray config
sed "s/UUID_PLACEHOLDER/$UUID/" /etc/xray/config.json.template > /etc/xray/config.json

# Start Python server (HTTP config page + SOCKS5 proxy)
cd /app
python3 main.py &

# Start Xray
/usr/local/bin/xray -config /etc/xray/config.json
