#!/usr/bin/env python3
import argparse, base64, hashlib, getpass, secrets

parser = argparse.ArgumentParser(description="Create a PQM PBKDF2 password hash")
parser.add_argument("--password", help="Password; omit to enter it interactively")
args = parser.parse_args()
password = args.password if args.password is not None else getpass.getpass("Password: ")
iterations = 310_000
salt = secrets.token_bytes(16)
digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
enc = lambda b: base64.urlsafe_b64encode(b).decode().rstrip("=")
print(f"pbkdf2_sha256${iterations}${enc(salt)}${enc(digest)}")
