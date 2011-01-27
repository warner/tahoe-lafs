from allmydata.util.ecdsa import SigningKey, VerifyingKey, NIST192p
from allmydata.util import base32

# in base32, the signing key is 39 chars long, and the verifying key is 77.
# in base62, the signing key is 33 chars long, and the verifying key is 65.
# in base64, the signing key is 32 chars long, and the verifying key is 64.
#
# We can't use base64 because we want to reserve punctuation and preserve
# cut-and-pasteability. The base62 encoding is not significantly shorter than
# the base32 form, and the minor usability improvement is not worth the
# documentation/specification confusion of using a non-standard encoding. So
# we stick with base32.

def make_keypair():
    privkey = SigningKey.generate(curve=NIST192p)
    privkey_vs = "priv-v0-%s" % base32.b2a(privkey.to_string())
    pubkey = privkey.get_verifying_key()
    pubkey_vs = "pub-v0-%s" % base32.b2a(pubkey.to_string())
    return privkey_vs, pubkey_vs

def parse_privkey(privkey_vs):
    if not privkey_vs.startswith("priv-v0-"):
        raise ValueError("private key must look like 'priv-v0-...', not '%s'" % privkey_vs)
    privkey_s = privkey_vs[len("priv-v0-"):]
    sk = SigningKey.from_string(base32.a2b(privkey_s), curve=NIST192p)
    pubkey = sk.get_verifying_key()
    pubkey_vs = "pub-v0-%s" % base32.b2a(pubkey.to_string())
    return sk, pubkey_vs

def parse_pubkey(pubkey_vs):
    if not pubkey_vs.startswith("pub-v0-"):
        raise ValueError("public key must look like 'pub-v0-...', not '%s'" % pubkey_vs)
    pubkey_s = pubkey_vs[len("pub-v0-"):]
    vk = VerifyingKey.from_string(base32.a2b(pubkey_s), curve=NIST192p)
    return vk
