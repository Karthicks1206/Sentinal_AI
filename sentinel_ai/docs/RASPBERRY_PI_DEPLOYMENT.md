# Raspberry Pi Deployment Guide

## Hardware Requirements

- **Raspberry Pi**: 3B+, 4, or 5 recommended
- **RAM**: Minimum 1GB (2GB+ recommended)
- **Storage**: 16GB+ SD card
- **Network**: Ethernet or WiFi connectivity
- **Power**: Official Raspberry Pi power supply

## Operating System Setup

### Step 1: Flash Raspberry Pi OS

1. Download Raspberry Pi Imager: https://www.raspberrypi.com/software/
2. Flash Raspberry Pi OS Lite (64-bit recommended)
3. Enable SSH before booting:
   ```bash
   # Create empty SSH file on boot partition
   touch /Volumes/boot/ssh
   ```

### Step 2: Initial Boot

```bash
# SSH into Pi (default password: raspberry)
ssh pi@raspberrypi.local

# Update system
sudo apt-get update
sudo apt-get upgrade -y

# Install required packages
sudo apt-get install -y \
    python3-pip \
    python3-dev \
    git \
    mosquitto \
    mosquitto-clients \
    build-essential \
    libssl-dev \
    libffi-dev
```

## Sentinel AI Installation

### Step 1: Clone Repository

```bash
# Create application directory
sudo mkdir -p /opt/sentinel
sudo chown pi:pi /opt/sentinel

cd /opt/sentinel
git clone <repository-url> .
```

### Step 2: Install Python Dependencies

```bash
# Install in virtual environment (recommended)
python3 -m venv venv
source venv/bin/activate

# Install requirements
pip install -r requirements.txt

# Or install globally
sudo pip3 install -r requirements.txt
```

### Step 3: Configure MQTT Broker

```bash
# Start Mosquitto
sudo systemctl start mosquitto
sudo systemctl enable mosquitto

# Test MQTT
mosquitto_pub -t test -m "hello"
mosquitto_sub -t test
```

### Step 4: Configure Sentinel AI

```bash
# Create configuration directory
mkdir -p /opt/sentinel/config
mkdir -p /opt/sentinel/data
mkdir -p /opt/sentinel/logs
mkdir -p /opt/sentinel/certs

# Copy example config
cp config/config.yaml /opt/sentinel/config/config.yaml

# Edit configuration
nano /opt/sentinel/config/config.yaml
```

Update configuration for Raspberry Pi:

```yaml
system:
  device_id: "rpi-001"  # Unique device ID
  environment: "production"

monitoring:
  collection_interval: 5
  metrics:
    mqtt:
      enabled: true
      broker_host: "localhost"
      broker_port: 1883

aws:
  enabled: false  # Enable after AWS setup
```

### Step 5: Test Installation

```bash
# Run Sentinel AI
cd /opt/sentinel
python3 main.py

# Should see:
# INFO - Sentinel AI - Autonomous Self-Healing System
# INFO - Device ID: rpi-001
# INFO - All agents started successfully
# INFO - Sentinel AI is now operational
```

## AWS Integration (Optional)

### Step 1: Install AWS CLI

```bash
sudo pip3 install awscli
aws configure
```

### Step 2: Provision IoT Thing

```bash
# Create thing
aws iot create-thing --thing-name sentinel-rpi-001

# Create certificate
aws iot create-keys-and-certificate \
  --set-as-active \
  --certificate-pem-outfile /opt/sentinel/certs/device.cert.pem \
  --public-key-outfile /opt/sentinel/certs/device.public.key \
  --private-key-outfile /opt/sentinel/certs/device.private.key \
  --certificate-arn > cert_arn.txt

# Download root CA
wget -O /opt/sentinel/certs/root-CA.crt \
  https://www.amazontrust.com/repository/AmazonRootCA1.pem

# Attach policy to certificate
CERT_ARN=$(jq -r .certificateArn cert_arn.txt)
aws iot attach-policy --policy-name SentinelDevicePolicy --target $CERT_ARN
aws iot attach-thing-principal --thing-name sentinel-rpi-001 --principal $CERT_ARN
```

### Step 3: Update Configuration

```yaml
aws:
  enabled: true
  region: "us-east-1"

  iot_core:
    enabled: true
    endpoint: "<your-iot-endpoint>.amazonaws.com"
    cert_path: "/opt/sentinel/certs/device.cert.pem"
    key_path: "/opt/sentinel/certs/device.private.key"
    ca_path: "/opt/sentinel/certs/root-CA.crt"
    thing_name: "sentinel-rpi-001"
```

## systemd Service Setup

### Step 1: Create Service File

```bash
sudo nano /etc/systemd/system/sentinel-ai.service
```

Content:

```ini
[Unit]
Description=Sentinel AI - Autonomous Self-Healing System
After=network.target mosquitto.service

[Service]
Type=simple
User=pi
WorkingDirectory=/opt/sentinel
ExecStart=/usr/bin/python3 /opt/sentinel/main.py
Restart=always
RestartSec=10

# Environment variables
Environment="DEVICE_ID=rpi-001"
Environment="ENVIRONMENT=production"
Environment="AWS_REGION=us-east-1"

# Logging
StandardOutput=append:/opt/sentinel/logs/systemd.log
StandardError=append:/opt/sentinel/logs/systemd-error.log

[Install]
WantedBy=multi-user.target
```

### Step 2: Enable and Start Service

```bash
# Reload systemd
sudo systemctl daemon-reload

# Enable service (start on boot)
sudo systemctl enable sentinel-ai

# Start service
sudo systemctl start sentinel-ai

# Check status
sudo systemctl status sentinel-ai

# View logs
sudo journalctl -u sentinel-ai -f
```

## Performance Optimization

### Reduce Memory Usage

Edit config:
```yaml
anomaly_detection:
  methods:
    z_score:
      window_size: 50  # Reduce from 100

learning:
  local_db:
    retention_days: 30  # Reduce from 90
```

### Reduce CPU Usage

```yaml
monitoring:
  collection_interval: 10  # Increase from 5 seconds
```

### Optimize SQLite

```bash
# Add to config
learning:
  local_db:
    path: "/opt/sentinel/data/sentinel.db"

# Run vacuum periodically (cron)
echo "0 2 * * * sqlite3 /opt/sentinel/data/sentinel.db 'VACUUM;'" | crontab -
```

## Monitoring

### Check System Resources

```bash
# CPU and memory
htop

# Disk usage
df -h

# Service status
systemctl status sentinel-ai
```

### View Logs

```bash
# Real-time logs
tail -f /opt/sentinel/logs/sentinel.log

# Parse JSON logs
tail -f /opt/sentinel/logs/sentinel.log | jq '.'

# Filter by level
tail -f /opt/sentinel/logs/sentinel.log | jq 'select(.level=="ERROR")'
```

### Database Inspection

```bash
sqlite3 /opt/sentinel/data/sentinel.db

# Query incidents
SELECT * FROM incidents ORDER BY timestamp DESC LIMIT 10;

# Query anomalies
SELECT metric_name, COUNT(*) FROM anomalies GROUP BY metric_name;

# Exit
.quit
```

## Backup & Recovery

### Backup Database

```bash
# Create backup script
cat > /opt/sentinel/backup.sh << 'EOF'
#!/bin/bash
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="/opt/sentinel/backups"
mkdir -p $BACKUP_DIR

# Backup database
sqlite3 /opt/sentinel/data/sentinel.db ".backup $BACKUP_DIR/sentinel_$DATE.db"

# Backup config
cp /opt/sentinel/config/config.yaml $BACKUP_DIR/config_$DATE.yaml

# Keep only last 7 days
find $BACKUP_DIR -name "sentinel_*.db" -mtime +7 -delete
find $BACKUP_DIR -name "config_*.yaml" -mtime +7 -delete
EOF

chmod +x /opt/sentinel/backup.sh

# Add to cron (daily at 2 AM)
echo "0 2 * * * /opt/sentinel/backup.sh" | crontab -
```

### Restore from Backup

```bash
# Stop service
sudo systemctl stop sentinel-ai

# Restore database
cp /opt/sentinel/backups/sentinel_YYYYMMDD_HHMMSS.db \
   /opt/sentinel/data/sentinel.db

# Start service
sudo systemctl start sentinel-ai
```

## Troubleshooting

### Service Won't Start

```bash
# Check logs
sudo journalctl -u sentinel-ai -n 50

# Check permissions
ls -la /opt/sentinel

# Verify Python dependencies
pip3 list | grep -E "pyyaml|psutil|paho-mqtt"
```

### High CPU Usage

```bash
# Check process
top -p $(pgrep -f sentinel)

# Disable simulation if enabled
# Edit config.yaml:
simulation:
  enabled: false
```

### MQTT Connection Issues

```bash
# Test local MQTT
mosquitto_pub -t test -m "hello"
mosquitto_sub -t test

# Check Mosquitto status
sudo systemctl status mosquitto

# View Mosquitto logs
sudo journalctl -u mosquitto -f
```

### AWS IoT Connection Issues

```bash
# Test with mosquitto_pub
mosquitto_pub \
  --cafile /opt/sentinel/certs/root-CA.crt \
  --cert /opt/sentinel/certs/device.cert.pem \
  --key /opt/sentinel/certs/device.private.key \
  -h <your-endpoint>.iot.us-east-1.amazonaws.com \
  -p 8883 \
  -t sentinel/test \
  -m "test message"

# Check certificate permissions
ls -la /opt/sentinel/certs/
chmod 600 /opt/sentinel/certs/*.key
```

## Security Hardening

### Change Default Password

```bash
passwd
```

### Setup Firewall

```bash
sudo apt-get install ufw
sudo ufw allow ssh
sudo ufw allow 1883/tcp  # MQTT
sudo ufw enable
```

### Disable Unnecessary Services

```bash
sudo systemctl disable bluetooth
sudo systemctl disable avahi-daemon
```

### Encrypt Sensitive Files

```bash
# Install GPG
sudo apt-get install gnupg

# Encrypt AWS credentials
gpg -c /opt/sentinel/certs/device.private.key
```

## Updates

### Update Sentinel AI

```bash
cd /opt/sentinel
git pull
pip3 install -r requirements.txt --upgrade
sudo systemctl restart sentinel-ai
```

### Update OS

```bash
sudo apt-get update
sudo apt-get upgrade -y
sudo reboot
```

## Multi-Device Deployment

### Deploy to Multiple Pi Devices

```bash
# Create deployment script
cat > deploy.sh << 'EOF'
#!/bin/bash
DEVICES=(
  "pi@192.168.1.101"
  "pi@192.168.1.102"
  "pi@192.168.1.103"
)

for device in "${DEVICES[@]}"; do
  echo "Deploying to $device..."

  # Copy files
  scp -r /opt/sentinel $device:/tmp/

  # Install remotely
  ssh $device << 'REMOTE'
    sudo mv /tmp/sentinel /opt/
    sudo chown -R pi:pi /opt/sentinel
    sudo systemctl restart sentinel-ai
REMOTE

  echo "Deployed to $device"
done
EOF

chmod +x deploy.sh
./deploy.sh
```

## Conclusion

Your Sentinel AI system is now deployed on Raspberry Pi and ready for autonomous operation. Monitor logs regularly and adjust configuration based on your specific IoT infrastructure needs.

For support, refer to the main README.md or open an issue on GitHub.
