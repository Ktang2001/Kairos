**Testing Across Two Computer**

1. Clone the repo and install deps (pyproject.toml) on both machines.
2. Decide which machine hosts this session.
3. On the host, run python -m server.gui — it shows the LAN IP/port to give your teammate directly. (Or python -m server.main, but then you'll need to find the LAN IP yourself via hostname -I / ip addr.)
4. Open the firewall port on the host (Fedora: sudo firewall-cmd --add-port=8000/tcp).
5. Make sure both machines are on the same LAN (same Wi-Fi/switch — won't work across separate networks without a VPN).
6. On the client machine, run python -m client.main, type http://<host-LAN-IP></host>:8000 into the host field, click Connect. (Or set KAIROS_SERVER_URL env var instead.)
7. Send a message from each side and confirm both see it (the GUI polls /messages every second).
8. Watch out for: gui.py's LAN-IP lookup can show 127.0.1.1 on some Linux /etc/hosts setups (use hostname -I instead if so), and guest/corporate Wi-Fi with AP isolation will block this even with correct IP + open firewall.


**Testing Across One Computer**

1. Open two terminals in the repo root (with the venv activated in both).
2. **Terminal 1 — start the server** : python -m server.gui
3. **Terminal 2 — start client :** python -m server.gui
4. On Client click success
5. On client send a message
6. To check persistance either check: server/db/karios.db or restart the client and send another message
