# Testbed Console & Dashboard

A web console for planning, running, watching and reviewing tests on the BMW Lab
O-RAN testbed. ETHOS is the first rApp it drives.

The console **presents** the testbed; ETHOS is the component that touches it. The
console reaches ETHOS over loopback and holds no credential of its own, no
InfluxDB token, no SSH key, no SDNC password, and nothing of the sort ever
reaches a browser.

```
browser (lab LAN) ──HTTPS :8443, one password──► Testbed Console
                                                      │ HTTP over loopback
                                                      ▼
                                                 ETHOS API 127.0.0.1:8081
                                                      │
                                    SSH · kubectl · adb · InfluxDB · SDNC
```

- **[docs/running-guide.md](docs/running-guide.md)**: install, configure, run,
  reach it, what each page does, and troubleshooting. Start here.
- **[docs/ethos-backlog.md](docs/ethos-backlog.md)**: the ETHOS endpoints the
  console is waiting for, and what each one unlocks.
- **[docs/01-requirements.md](docs/01-requirements.md)** …
  **[04-build-plan.md](docs/04-build-plan.md)**: the contract this is built
  against.
- **[CLAUDE.md](CLAUDE.md)**: the rules for changing it.

```bash
cd ~/testbed-console
python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt
./deploy/make-cert.sh 192.168.8.78
cp console.env.example console.env && chmod 600 console.env
.venv/bin/python -m console set-password     # paste the hash into console.env
.venv/bin/python -m console check
systemctl --user enable --now testbed-console
```

Then `https://192.168.8.78:8443`.
