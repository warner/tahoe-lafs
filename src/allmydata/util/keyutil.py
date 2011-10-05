import ed25519
from allmydata.util import base32

# in base32, both the signing key and verifying key are 52 chars long
# in base62, both the signing key and verifying key are 43 chars long
# in base64, both the signing key and verifying key are 43 chars long
#
# We can't use base64 because we want to reserve punctuation and preserve
# cut-and-pasteability. The base62 encoding is shorter than the base32 form,
# but the minor usability improvement is not worth the documentation and
# specification confusion of using a non-standard encoding. So we stick with
# base32.

BadSignatureError = ed25519.BadSignatureError

def make_keypair():
    privkey, pubkey = ed25519.create_keypair()
    privkey_vs = "priv-v0-%s" % base32.b2a(privkey.to_seed())
    pubkey_vs = "pub-v0-%s" % base32.b2a(pubkey.to_string())
    return privkey_vs, pubkey_vs

def parse_privkey(privkey_vs):
    if not privkey_vs.startswith("priv-v0-"):
        raise ValueError("private key must look like 'priv-v0-...', not '%s'" % privkey_vs)
    privkey_s = privkey_vs[len("priv-v0-"):]
    sk = ed25519.SigningKey(base32.a2b(privkey_s))
    pubkey = sk.get_verifying_key()
    pubkey_vs = "pub-v0-%s" % base32.b2a(pubkey.to_string())
    return sk, pubkey_vs

def parse_pubkey(pubkey_vs):
    if not pubkey_vs.startswith("pub-v0-"):
        raise ValueError("public key must look like 'pub-v0-...', not '%s'" % pubkey_vs)
    pubkey_s = pubkey_vs[len("pub-v0-"):]
    vk = ed25519.VerifyingKey(base32.a2b(pubkey_s))
    return vk
