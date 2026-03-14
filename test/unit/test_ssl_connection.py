import asyncio
import os
import ssl
import pytest
import socket
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.backends import default_backend
import datetime

import sys
import os as os_module

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../src"))

from maim_message.ws_connection import WebSocketServer, WebSocketClient


def is_port_open(host, port, timeout=1):
    """Check if a port is open"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((host, port))
        sock.close()
        return result == 0
    except Exception:
        return False


def generate_self_signed_cert():
    """Generate self-signed SSL certificates for testing"""
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization

    key = rsa.generate_private_key(
        public_exponent=65537, key_size=2048, backend=default_backend()
    )

    subject = issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
            x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "Test"),
            x509.NameAttribute(NameOID.LOCALITY_NAME, "Test"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Test"),
            x509.NameAttribute(NameOID.COMMON_NAME, "localhost"),
        ]
    )

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.utcnow())
        .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=365))
        .sign(key, hashes.SHA256(), default_backend())
    )

    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    key_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )

    return cert_pem, key_pem


@pytest.mark.asyncio
async def test_ssl_connection():
    """Test SSL/TLS connection"""
    cert_pem, key_pem = generate_self_signed_cert()

    cert_path = "/tmp/test_server.crt"
    key_path = "/tmp/test_server.key"

    with open(cert_path, "wb") as f:
        f.write(cert_pem)

    with open(key_path, "wb") as f:
        f.write(key_pem)

    try:
        server = WebSocketServer(
            host="localhost", port=18097, ssl_certfile=cert_path, ssl_keyfile=key_path
        )
        server_task = asyncio.create_task(server.start())

        for _ in range(20):
            await asyncio.sleep(0.5)
            if is_port_open("localhost", 18097):
                break

        client = WebSocketClient()
        await client.configure(
            url="https://localhost:18097",
            platform="test_platform",
            ssl_verify=cert_path,
        )

        connected = await client.connect()
        assert connected is True
        assert client.is_connected() is True

        await client.stop()
        await server.stop()

        server_task.cancel()
        try:
            await server_task
        except asyncio.CancelledError:
            pass
    finally:
        if os.path.exists(cert_path):
            os.remove(cert_path)
        if os.path.exists(key_path):
            os.remove(key_path)
