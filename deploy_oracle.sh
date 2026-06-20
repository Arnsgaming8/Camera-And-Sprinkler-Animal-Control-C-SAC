#!/bin/bash
set -e

echo "=== BABBS Oracle Deployment ==="

# Install Python + deps
apt-get update -qq
apt-get install -y -qq python3 python3-pip python3-venv git

# Clone repo
cd /opt
rm -rf babbs
git clone https://github.com/Arnsgaming8/Blink-And-Bhyve-Bunny-System.git babbs
cd babbs

# Setup venv + install
python3 -m venv venv
source venv/bin/activate
pip install -q aiohttp pyyaml blinkpy

# Create systemd service to run on boot + restart
cat > /etc/systemd/system/babbs.service << 'SERVICE'
[Unit]
Description=BABBS Blink-Bhyve Bridge
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/babbs
Environment=PATH=/opt/babbs/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
ExecStart=/opt/babbs/venv/bin/python /opt/babbs/app.py
Restart=always
RestartSec=5
User=root

[Install]
WantedBy=multi-user.target
SERVICE

# Open firewall port 5000
ufw allow 5000/tcp 2>/dev/null || true

# Enable and start
systemctl daemon-reload
systemctl enable babbs
systemctl start babbs

echo ""
echo "=== Done! ==="
echo "Visit: http://$(curl -4 -s ifconfig.me):5000"
echo ""
echo "First visit opens the Setup page. Enter credentials there."
echo ""
echo "Commands:"
echo "  systemctl status babbs    # check status"
echo "  systemctl restart babbs   # restart"
echo "  journalctl -u babbs -f    # tail logs"
