#!/usr/bin/env bash
# A self-signed certificate for the console, valid for this host's LAN address.
#
# The browser will warn once on the first visit. To silence it, add the
# certificate to your laptop's trust store — the file printed at the end.
#
#   ./deploy/make-cert.sh                 # for 192.168.8.78
#   ./deploy/make-cert.sh 192.168.8.99    # for another address

set -euo pipefail

ADDRESS="${1:-192.168.8.78}"
DIR="${CONSOLE_TLS_DIR:-$HOME/.config/testbed-console/tls}"
CRT="$DIR/console.crt"
KEY="$DIR/console.key"
DAYS=825   # the longest a current browser accepts for a new certificate

mkdir -p "$DIR"
chmod 700 "$DIR"

if [ -f "$CRT" ] && [ -f "$KEY" ]; then
  echo "A certificate already exists:"
  openssl x509 -in "$CRT" -noout -subject -dates -ext subjectAltName
  read -rp "Replace it? [y/N] " answer
  [ "$answer" = "y" ] || { echo "Kept the existing certificate."; exit 0; }
fi

openssl req -x509 -nodes -newkey rsa:2048 \
  -keyout "$KEY" -out "$CRT" -days "$DAYS" -sha256 \
  -subj "/CN=$ADDRESS/O=BMW Lab Testbed Console" \
  -addext "subjectAltName=IP:$ADDRESS,IP:127.0.0.1,DNS:localhost" \
  -addext "basicConstraints=critical,CA:FALSE" \
  -addext "keyUsage=critical,digitalSignature,keyEncipherment" \
  -addext "extendedKeyUsage=serverAuth"

chmod 600 "$KEY"
chmod 644 "$CRT"

echo
openssl x509 -in "$CRT" -noout -subject -dates -ext subjectAltName
echo
echo "Put these in console.env:"
echo "  CONSOLE_TLS_CERT=$CRT"
echo "  CONSOLE_TLS_KEY=$KEY"
echo
echo "To stop the browser warning, add $CRT to your laptop's trust store."
