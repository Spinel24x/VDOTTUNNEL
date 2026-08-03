FROM debian:stable-slim

# Install dependencies
RUN apt-get update && apt-get install -y unzip curl ca-certificates python3 python3-pip

# Install Xray
ADD https://github.com/XTLS/Xray-core/releases/download/v1.8.23/Xray-linux-64.zip /tmp/xray.zip
RUN unzip /tmp/xray.zip -d /usr/local/bin/ && chmod +x /usr/local/bin/xray && rm /tmp/xray.zip

# Copy Python requirements and install
COPY requirements.txt /tmp/
RUN pip3 install -r /tmp/requirements.txt

# Copy all Python scripts and config template to root of app
COPY main.py vless.py dns_utils.py /app/
COPY config.json.template /etc/xray/config.json.template
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8080
ENTRYPOINT ["/entrypoint.sh"]
