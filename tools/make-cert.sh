#!/usr/bin/env bash
# Generate a local certificate authority and a server certificate, into ./ssl.
#
#   npm run cert          # then restart the server
#
# Run it from anywhere; it always writes next to the project, not to whatever
# directory you happen to be standing in.
#
# Why a CA and not just a self-signed certificate: accepting a browser warning
# gets you a secure context, which is enough for the camera, but Chrome still
# refuses to register a service worker on an origin whose certificate it does
# not trust — "An SSL certificate error occurred when fetching the script" —
# so the offline install silently never happens. Installing ssl/ca.pem on the
# phone once fixes that, and a certificate can only be installed as a trust
# anchor if it is marked as a CA, which a plain self-signed leaf is not.
#
# The certificate carries every LAN address of this machine in subjectAltName.
# Modern browsers ignore the Common Name entirely, so a certificate naming only
# "/CN=192.168.1.20" is rejected rather than merely warned about.

set -euo pipefail

PROJECT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SSL_DIR="$PROJECT/ssl"
CA_DAYS="${CA_DAYS:-3650}"
LEAF_DAYS="${LEAF_DAYS:-825}"   # browsers reject leaf certificates valid much longer

mkdir -p "$SSL_DIR"
cd "$SSL_DIR"

host="$(hostname)"
alt="DNS:localhost,DNS:$host,DNS:$host.local,IP:127.0.0.1"
for ip in $(hostname -I 2>/dev/null || true); do
  alt="$alt,IP:$ip"
done

echo "Certificate will be valid for:"
echo "$alt" | tr ',' '\n' | sed 's/^/    /'
echo

# --- the authority, which is what gets installed on the phone ---------------
if [ -f ca.pem ] && [ -f ca-key.pem ]; then
  echo "Reusing the existing authority (ca.pem) so the phone does not need"
  echo "to trust a new one."
else
  openssl req -x509 -newkey rsa:2048 -nodes -days "$CA_DAYS" \
    -keyout ca-key.pem -out ca.pem \
    -subj "/CN=Uber Scan local CA ($host)" \
    -addext "basicConstraints=critical,CA:TRUE,pathlen:0" \
    -addext "keyUsage=critical,keyCertSign,cRLSign" 2>/dev/null
  echo "Created a new authority: ca.pem"
fi

# --- the server certificate the site is served with -------------------------
openssl req -newkey rsa:2048 -nodes \
  -keyout key.pem -out server.csr \
  -subj "/CN=$host" 2>/dev/null

cat > server.ext <<EXT
subjectAltName=$alt
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
EXT

openssl x509 -req -in server.csr -CA ca.pem -CAkey ca-key.pem -CAcreateserial \
  -out cert.pem -days "$LEAF_DAYS" -sha256 -extfile server.ext 2>/dev/null

rm -f server.csr server.ext
chmod 600 key.pem ca-key.pem

openssl verify -CAfile ca.pem cert.pem

cat <<DONE

Wrote to $SSL_DIR
  cert.pem, key.pem   the server uses these — restart it now
  ca.pem              install this on the phone
  ca-key.pem          keep this private; it can mint certificates

Restart the server and it serves https on port ${HTTPS_PORT:-8443} alongside http.

Without installing ca.pem the phone warns once, and accepting the warning is
enough for the camera to work. It is NOT enough for the offline install: Chrome
refuses service workers on an untrusted certificate. To get both, copy ca.pem to
the phone and install it:

  Android: Settings > Security > More security settings > Encryption &
           credentials > Install a certificate > CA certificate
  iOS:     open the file, install the profile, then Settings > General > About >
           Certificate Trust Settings and enable full trust for it
DONE
