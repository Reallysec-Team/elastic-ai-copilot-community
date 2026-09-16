#!/usr/bin/env python3
"""Sign a content pack for online delivery.

Produces a token in the license wire format ``<b64(json)>.<b64(rsa_pss_sig)>``
that the gateway verifies with ``content_store.verify_pack_token`` (same RSA-PSS
/ SHA-256 as the license verifier). The vendor holds the private key; the gateway
trusts the matching public key (RST_CONTENT_PUBLIC_KEY_PATH, or the license key).

Usage:
    # sign a pack
    python sign_content_pack.py sign <pack.json> <private_key.pem> [--out pack.token]

    # generate a throwaway RSA keypair (testing / first-time vendor setup)
    python sign_content_pack.py genkey <out_dir>

Pack JSON shape:
    {
      "app_id": "rst_elastic_ai_copilot",
      "pack_version": "2026-07-01.1",
      "min_app_version": "1.1.0",
      "created_at": "2026-07-01T00:00:00Z",
      "assets": {
        "prompt.nl2dsl.system": {"kind": "prompt", "body": "..."}
      }
    }
"""

import base64
import json
import sys
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa


def sign(pack_path: str, key_path: str, out_path: str | None) -> None:
    pack = json.loads(Path(pack_path).read_text(encoding="utf-8"))
    # Canonical-ish: compact, stable key order, so the signed bytes are reproducible.
    payload_json = json.dumps(pack, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    payload_b64 = base64.b64encode(payload_json.encode("utf-8")).decode("ascii")

    priv = serialization.load_pem_private_key(Path(key_path).read_bytes(), password=None)
    if not isinstance(priv, rsa.RSAPrivateKey):
        raise SystemExit("private key is not RSA")
    sig = priv.sign(
        payload_b64.encode("ascii"),
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
        hashes.SHA256(),
    )
    token = payload_b64 + "." + base64.b64encode(sig).decode("ascii")
    if out_path:
        Path(out_path).write_text(token, encoding="utf-8")
        print(f"wrote {out_path} ({len(token)} bytes)")
    else:
        print(token)


def genkey(out_dir: str) -> None:
    d = Path(out_dir)
    d.mkdir(parents=True, exist_ok=True)
    priv = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    (d / "content_signing_private.pem").write_bytes(
        priv.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    (d / "content_signing_public.pem").write_bytes(
        priv.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    )
    print(f"wrote {d}/content_signing_private.pem + content_signing_public.pem")


def main() -> None:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        raise SystemExit(2)
    cmd = args[0]
    if cmd == "sign":
        if len(args) < 3:
            raise SystemExit("usage: sign <pack.json> <private_key.pem> [--out file]")
        out = args[args.index("--out") + 1] if "--out" in args else None
        sign(args[1], args[2], out)
    elif cmd == "genkey":
        if len(args) < 2:
            raise SystemExit("usage: genkey <out_dir>")
        genkey(args[1])
    else:
        raise SystemExit(f"unknown command {cmd!r} (sign | genkey)")


if __name__ == "__main__":
    main()
