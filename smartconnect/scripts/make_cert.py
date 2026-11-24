"""
Create a self-signed HTTPS certificate for LAN use.

Why: phone browsers only allow camera access (getUserMedia) on HTTPS pages (or
localhost).  A plain http://192.168.x.x address would NOT let the scanner open
the camera.  This script makes instance/cert.pem and instance/key.pem that
include your computer's LAN IP addresses.

Run:   python scripts/make_cert.py
Then set LAN_HTTPS=true and SESSION_COOKIE_SECURE=true in .env and run: python run.py
The first time, the phone shows a warning ("not private") - choose Advanced -> Proceed.
That is expected for a self-signed certificate.
"""
import datetime
import ipaddress
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from app.utils.helpers import get_lan_ips

out_dir = Path(__file__).resolve().parent.parent / "instance"
out_dir.mkdir(exist_ok=True)

key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "SmartConnect LAN")])

names = [x509.DNSName("localhost"), x509.DNSName(socket.gethostname()),
         x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
for ip in get_lan_ips():
    names.append(x509.IPAddress(ipaddress.ip_address(ip)))

now = datetime.datetime.now(datetime.timezone.utc)
cert = (x509.CertificateBuilder()
        .subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=365))
        .add_extension(x509.SubjectAlternativeName(names), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(key, hashes.SHA256()))

(out_dir / "key.pem").write_bytes(key.private_bytes(
    serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
    serialization.NoEncryption()))
(out_dir / "cert.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))

print("Created instance/cert.pem and instance/key.pem")
print("Valid for:", ", ".join(str(n.value) for n in names))
print("If your Wi-Fi IP changes, run this script again.")
