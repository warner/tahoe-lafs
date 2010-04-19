
from zope.interface import Interface, implements
import simplejson
from twisted.internet import defer
from pycryptopp.publickey import ecdsa
from allmydata.util import base32, log

class IBlesser(Interface):
    def bless(what):
        """Bless 'what', which must be a dictionary, by signing it with a key.

        Returns a Deferred that fires with a certificate chain (tuple of
        (json, sig, pubkey) tuples).

        The 'what' dictionary must be safe to serialize with JSON, so it
        cannot contain any binary strings.
        """

class NonBlesser:
    implements(IBlesser)

    def bless(self, what):
        assert isinstance(what, dict)
        ann_s = simplejson.dumps(what)
        cert = (ann_s, "", "")
        chain = (cert,)
        return defer.succeed(chain)

class PrivateKeyBlesser:
    # for now, the blessing must be a single private key. In the future, it
    # may be a combination of a private key and a cert-chain which delegates
    # some authority to it. We always return a list (with a single cert), for
    # forwards compatibility.
    implements(IBlesser)

    def __init__(self, privkey_b32_verinfo):
        privkey_b32_verinfo = privkey_b32_verinfo.strip()
        assert privkey_b32_verinfo.startswith("priv-v0-")
        privkey_b32 = privkey_b32_verinfo[len("priv-v0-"):] # strip the verinfo
        privkey_s = base32.a2b(privkey_b32)
        self.privkey = ecdsa.create_signing_key_from_string(privkey_s)
        pubkey = self.privkey.get_verifying_key()
        self.pubkey_s = pubkey.serialize()

    def bless(self, what):
        assert isinstance(what, dict)
        ann_s = simplejson.dumps(what)
        sig = self.privkey.sign(ann_s)
        cert = (ann_s, sig, self.pubkey_s)
        chain = (cert,)
        return defer.succeed(chain)

class BadSignatureError(Exception):
    pass


class PrivateKeyBlessing:
    def __init__(self, pubkey_s):
        self.pubkey_s = pubkey_s # base32
    def get_short_display(self):
        """Return a short printable string summarizing the pubkey"""
        # I'd prefer to use the first e.g. 8 chars of the base32
        # representation of the key, but the pre-#331 pubkeys all have the
        # same 316 chars of boilerplate at the start (followed by 78 chars of
        # actual key), so to make these strings unique, I need to use the
        # *last* 8 chars. When #331 is fixed, I'll change this.
        return self.pubkey_s[:-8]
    def get_pubkey_s(self):
        return self.pubkey_s

class BlessedObject:
    @classmethod
    def from_certificate_chain(cls, chain):
        """Given a certificate chain (a list of (msg,sig,pubkey) tuples),
        create a new BlessedObject instance. Only the leaf (last) certificate
        is examined: this code does not yet support certificate chains. If
        the leaf signature is invalid, BadSignatureError will be raised.
        """
        bo = cls()
        (msg, sig, pubkey_s) = chain[-1]
        bo.leaf = simplejson.loads(msg)

        bo.blessing = None
        if sig and pubkey_s:
            pubkey = ecdsa.create_verifying_key_from_string(pubkey_s)
            if not pubkey.verify(msg, sig):
                log.msg("bad signature on %s" % msg,
                        level=log.WEIRD, umid="5FYtFw")
                raise BadSignatureError("bad signature on %s" % (msg,))
            bo.blessing = PrivateKeyBlessing(pubkey_s)

        return bo

    def get_leaf(self):
        """Return the leaf dictionary."""
        return self.leaf
    def get_blessing(self):
        """Return the Blessing object, or None if there was no signature."""
        return self.blessing

    def is_blessed_by(self, blessing_checker):
        """Return True if this object has a blessing that passes the checker,
        False otherwise."""
        return blessing_checker.check(self.blessing)

class PublicKeyBlessingChecker:
    def __init__(self, pubkey_s):
        self.pubkey_s = pubkey_s

    def check(self, blessing):
        if blessing and blessing.get_pubkey_s() == self.pubkey_s:
            return True
        return False
