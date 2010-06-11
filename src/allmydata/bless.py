
from zope.interface import Interface, implements
import simplejson
from twisted.internet import defer
from allmydata.util import base32, log, netstring
from allmydata.util.assertutil import precondition
from allmydata.util.ecdsa import SigningKey, VerifyingKey, NIST192p, \
     BadSignatureError

class IBlesser(Interface):
    def bless(what):
        """Bless 'what', which must be a dictionary, by signing it with a key.

        Returns a Deferred that fires with a certificate chain (tuple of
        (json, sig, pubkey) tuples).

        The 'what' dictionary must be safe to serialize with JSON, so it
        cannot contain any binary strings.
        """

# When handling public/private keys, we use four different types here:
#  key object: an instance of a class from python-ecdsa,
#              created with ecdsa.SigningKey(), or privkey.get_verifying_key(),
#              or ecdsa.SigningKey.from_string(), or
#              ecdsa.VerifyingKey.from_string()
#  key string: the raw pycryptopp-serialized form of a key object, created
#              with key.to_string(), and fed to create_*_key_from_string()
#  versioned keystring: the base32-encoded key string, prepended with a
#                       version identifier like "priv-v0-" or "pub-v0-",
#                       that indicates EC-DSA, the NIST192p curve and the
#                       serialization scheme.
# We use variables that end in no suffix, "_s", and "_vs" (respectively) to
# hold these various types. We also use variables ending in _b32 to hold the
# base32-encoded keystring (without version information), for display to
# humans.


# Use JSON for serializing nearly-arbitrary data, like the announcement dict.
# We must do this for signing anyways. The result will have lots of quotes,
# but is printable and usually has no newlines.
#
# The signature and pubkey are not complex/nested structures, they are single
# strings, basically fixed-length. Using JSON for (ann_j,sig_b32,pubkey_b32)
# would be ugly (those quotes must be escaped) and overkill. On the other
# hand, we have a fast C-accelerated JSON decoder.
#
# Some alternatives:
#
#  1: v0:NS(ann_j)NS(sig)NS(pubkey)
#  2: v0:NS(ann_j)NS(sig_b32)NS(pubkey_b32)
#  3: v0:NS(ann_j):sig_b32:pubkey_b32\n
#
# Using concatenated netstrings allows the the structure to be parsed without
# previous knowledge of its length (i.e. it could be embedded in some other
# structure without needing a length-indicating container). Using (sig_b32)
# instead of (sig) leaves the result printable, which is kind of nice for
# logging and debugging. Putting a trailing newline helps logging/debugging
# (concatenated certs will print out one-per-line), but we don't depend upon
# it for parsing (so the JSON is not constrained). We can use base32 (instead
# of a slightly-more-compact base64) because a: if we wanted this to be
# concise we'd use binary encoding, and b: we use base32 more than base64
# elsewhere in Tahoe.
#
# Having the entire certchain be a single string (such that publish() uses a
# string instead of a list-of-tuples) reduces our demands on the transport
# level, enabling things like an HTTP-based introducer.
#
# So we use this:
#
#  cert = c0:NS(ann_j)NS(sig_b32)NS(pubkey_b32)\n
#    unsigned certs use empty strings for sig/pubkey. NS('') is '0:,'
#    (this will look like c0:124{...},77:nox..,77:cwi..,\n)
#    the 'c0' means ('c' for cert):
#     certificate (not certchain)
#     ECDSA192, python-ecdsa-style sig
#     message is JSON-encoded dictionary, recipient ignores unknown keys
#  certchain = ach0:NUMCERTS:NS(cert)..NS(leafcert)\n
#    (this will look like
#      ach0:2:596:c0:432{...},77:nox..,77:cwi..,
#      ,596:c0:432{...},77:nox..,77:cwi..,
#      ,
#    )
#   the 'ach0' means ('a' for announcement, 'ch' for chain):
#    'NUMCERTS' with colon-delimiter
#    concatenated netstrings
#
# When this structure is used for introducer announcements, the leaf cert
# (which will appear at the end of the string) will have the keys defined in
# src/allmydata/introducer/interfaces.py . The earlier certs (which delegate
# authority to the key that signs the leaf) will have keys defined there too.

def strip_prefix(s, prefix):
    assert s.startswith(prefix)
    return s[len(prefix):]

def parse_pubkey_vs(pubkey_vs):
    pubkey_vs = pubkey_vs.strip()
    pubkey_b32 = strip_prefix(pubkey_vs, "pub-v0-") # strip the verinfo
    pubkey_s = base32.a2b(pubkey_b32)
    pubkey = VerifyingKey.from_string(pubkey_s, curve=NIST192p)
    return pubkey

def parse_privkey_vs(privkey_vs):
    privkey_vs = privkey_vs.strip()
    privkey_b32 = strip_prefix(privkey_vs, "priv-v0-") # strip the verinfo
    privkey_s = base32.a2b(privkey_b32)
    privkey = SigningKey.from_string(privkey_s, curve=NIST192p)
    pubkey = privkey.get_verifying_key()
    pubkey_s = pubkey.to_string()
    return (privkey, pubkey, pubkey_s)

class NonBlesser:
    implements(IBlesser)

    def bless(self, what):
        return defer.succeed(self.bless_now(what))
    def bless_now(self, what):
        assert isinstance(what, dict)
        ann_j = simplejson.dumps(what)
        NS = netstring.netstring
        cert = "c0:" + NS(ann_j) + NS("") + NS("") + "\n"
        chain = "ach0:1:" + NS(cert) + "\n"
        return chain

class PrivateKeyBlesser:
    # for now, the blessing contains a local private key (the 'nodekey') and
    # an optional blessing key: the resulting cert-chain is length 1 or 2. In
    # the future, it may be a combination of a private key and a
    # variable-length cert-chain which delegates some authority to it.
    implements(IBlesser)

    def __init__(self, node_privkey_vs, blesser_privkey_vs=None):
        # privkey_vs looks like "priv-v0-abcde123"
        (self.node_privkey,
         ign,
         self.node_pubkey_s) = parse_privkey_vs(node_privkey_vs)
        self.blesser_privkey = None
        if blesser_privkey_vs:
            (self.blesser_privkey,
             ign,
             self.blesser_pubkey_s) = parse_privkey_vs(blesser_privkey_vs)

    def bless(self, what):
        return defer.succeed(self.bless_now(what))

    def bless_now(self, what):
        assert isinstance(what, dict)
        ann_j = simplejson.dumps(what)
        sig = self.node_privkey.sign(ann_j)
        sig_b32 = base32.b2a(sig)
        pubkey_b32 = base32.b2a(self.node_pubkey_s)
        NS = netstring.netstring
        leaf_cert = "c0:" + NS(ann_j) + NS(sig_b32) + NS(pubkey_b32) + "\n"
        if self.blesser_privkey:
            node_pubkey_vs = "pub-v0-" + base32.b2a(self.node_pubkey_s)
            bless_j = simplejson.dumps({"version": 0,
                                        "delegate-to-pubkey": node_pubkey_vs,
                                        })
            bsig = self.blesser_privkey.sign(bless_j)
            bsig_b32 = base32.b2a(bsig)
            bpubkey_b32 = base32.b2a(self.blesser_pubkey_s)
            bcert = "c0:" + NS(bless_j) + NS(bsig_b32) + NS(bpubkey_b32) + "\n"
            certs = [bcert, leaf_cert]
        else:
            certs = [leaf_cert]

        pieces = ["ach0:", str(len(certs)), ":"]
        pieces.extend([NS(c) for c in certs])
        pieces.append("\n")
        chain = "".join(pieces)
        return chain


class CertChainBlessing:
    def __init__(self, chain, leaf_pubkey):
        # 'chain' is a list (possibly empty) of (dict, pubkey) tuples,
        # starting with the root, which provide the unpacked delegation chain
        # to the leaf.
        self.chain = list(chain)
        assert isinstance(leaf_pubkey, VerifyingKey)
        self.leaf_pubkey = leaf_pubkey

    def get_short_display(self):
        """Return a short printable string summarizing the pubkey"""
        # use the first 8 chars of the base32 representation of the key

        # TODO: show the chain
        pubkey_b32 = base32.b2a(self.leaf_pubkey.to_string())
        return pubkey_b32[:8]

    def get_leaf_pubkey(self):
        return self.leaf_pubkey

    def pubkey_in_chain(self, query_pubkey):
        query_pubkey_s = query_pubkey.to_string()
        if self.leaf_pubkey.to_string() == query_pubkey_s:
            return True
        for (d,pubkey) in self.chain:
            if pubkey.to_string() == query_pubkey_s:
                return True
        return False

class UnknownDelegationFormatError(Exception):
    pass
class BadDelegationError(Exception):
    pass

class BlessedObject:
    """I parse and validate a signed certificate chain.

    This class provides certificate chains with the following properties:
     * chain is rendered as a single string, printable
       * the container must provide the length of this string (non-streaming)
       * the string contains newlines and quotes, so further serialization
         or escaping would be somewhat ugly
       * the string is almost human readable, but rather verbose.
     * each certificate (including the leaf) contains a dictionary of
       JSON-serializable data

    You might want to create a subclass to provide other properties. To
    achieve conciseness, you might give up readability and the open-ended
    flexibility of using JSON dictionaries. Fixed-layout fields and binary
    strings (which can't be serialized in JSON) would reduce the size of the
    certificates.
    """

    @classmethod
    def from_certificate_chain(cls, chain_s):
        """Given a certificate chain (an ach0- string), create a new
        BlessedObject instance. If any of the signatures are invalid or do
        not match the claimed pubkey, BadSignatureError will be raised.
        """
        bo = cls()

        precondition(isinstance(chain_s, str),
                     "certchains must be strings", chain_s)
        certs = bo.split_certs(chain_s)
        chain = certs[:-1]
        leaf_cert = certs[-1]

        validated_chain = [] # list of (msg_d, msg_pubkey)
        for c in chain:
            # validate all certs
            (cert_j, cert_sig_s, cert_pubkey_s) = bo.parse_cert(c)
            precondition(cert_sig_s != "", "cert chains must be signed")
            precondition(cert_pubkey_s != "", "cert chains must be signed")
            cert_pubkey = VerifyingKey.from_string(cert_pubkey_s)
            try:
                cert_pubkey.verify(cert_sig_s, cert_j)
            except BadSignatureError:
                log.msg("bad signature in certchain on %s" % cert_j,
                        level=log.WEIRD, umid="cMc10w")
                raise
            cert_d = simplejson.loads(cert_j)
            validated_chain.append( (cert_d, cert_pubkey) )

        # and validate the leaf, if it is signed
        (msg_j, sig_s, pubkey_s) = bo.parse_cert(leaf_cert)
        if chain:
            precondition(sig_s != "", "cert chains require a leaf signature")
            precondition(pubkey_s != "", "cert chains require a leaf signature")
        leaf_pubkey = None
        if sig_s and pubkey_s:
            pubkey = VerifyingKey.from_string(pubkey_s)
            try:
                pubkey.verify(sig_s, msg_j)
            except BadSignatureError:
                log.msg("bad signature on %s" % msg_j,
                        level=log.WEIRD, umid="5FYtFw")
                raise
            leaf_pubkey = pubkey
        leaf_d = simplejson.loads(msg_j)
        validated_chain.append( (leaf_d, leaf_pubkey) )

        # now process the certs
        state = None
        for i in range(len(validated_chain)-1):
            parent_d, parent_pubkey = validated_chain[i]
            child_d, child_pubkey = validated_chain[i+1]
            state = bo.process_delegation(parent_d, child_d, child_pubkey,
                                          state)
        # and the leaf
        bo.leaf = bo.process_leaf(leaf_d, state)

        bo.blessing = None
        if leaf_pubkey:
            bo.blessing = CertChainBlessing(validated_chain[:-1], leaf_pubkey)

        return bo

    # these methods are meant to be overridden by subclasses that use
    # different certificate-formatting mechanisms

    def split_certs(self, chain_s):
        precondition(chain_s.startswith("ach0:"),
                     "not a version-0 certificate chain: %s" % chain_s[:4])
        data = chain_s[len("ach0:"):]
        colon = data.find(":")
        num_certs = int(data[:colon])
        data = data[colon+1:]
        certs = netstring.split_netstring(data, num_certs,
                                          required_trailer="\n")[0]
        return certs

    def parse_cert(self, data):
        precondition(data.startswith("c0:"), "not a v0 cert")
        data = data[len("c0:"):]
        (ann_j,
         sig_b32,
         pubkey_b32) = netstring.split_netstring(data, 3,
                                                 required_trailer="\n")[0]
        return ann_j, base32.a2b(sig_b32), base32.a2b(pubkey_b32)

    def process_delegation(self, parent_d, child_d, child_pubkey, state=None):
        """Handle links in the certificate chain. This will be called once
        for each non-leaf cert in the chain, starting with the root, ending
        with the one closest the the leaf. So if we have a chain in which
        msg_A signs msg_B, and msg_B signs msg_C, and msg_C is the leaf, the
        this will be called twice::

         process_delegation(msg_A, msg_B, pubkey_B, None) -> state1
         process_delegation(msg_B, msg_C, pubkey_C, state2) -> state2

        'parent_d' and 'child_d' are dictionaries, and 'child_pubkey' is an
        instance of VerifyingKey. When process_delegation() is called, the
        next cert will have been validated (signature checked against
        child_pubkey) and unpacked (message is JSON-decoded to get child_d).

        This method does not need to do any cryptographic work, except to
        confirm that any ['delegate-to-pubkey'] elements in parent_d actually
        match 'child_pubkey'.

        The return value of this method will be passed to the next invocation
        of process_delegation(), in the 'state=' argument. This can be used
        to implement a certificate chain in which each link attenuates the
        authority being delegated to the next key.

        The default implementation (meant to be overridden by subclasses)
        checks ['delegate-to-pubkey'] but does no other attenuation.
        """

        if parent_d["version"] != 0:
            raise UnknownDelegationFormatError("version is %s, not 0"
                                               % (parent_d["version"],))
        delg_pubkey_vs = str(parent_d["delegate-to-pubkey"])
        if not delg_pubkey_vs.startswith("pub-v0-"):
            msg = ("delegated pubkey in bad format,"
                   " want pub-v0-[base32..], got %s" % delg_pubkey_vs)
            raise UnknownDelegationFormatError(msg)
        delg_pubkey = parse_pubkey_vs(delg_pubkey_vs)
        if delg_pubkey.to_string() != child_pubkey.to_string():
            msg = ("chain delegates to wrong key: %s, but next cert is %s"
                   % (base32.b2a(delg_pubkey.to_string()),
                      base32.b2a(child_pubkey.to_string())))
            raise BadDelegationError(msg)
        return None

    def process_leaf(self, child_d, state=None):
        """Handle the final link of the certificate chain. This will be
        called once, with the 'state' return value from the last call to
        process_delegation(), or None if the chain was of length one.

        The return value of this method is stored as the 'leaf' of this
        BlessedObject, which can be retrieved through the get_leaf() method.
        """
        return child_d

    # These methods are meant for application code to use, to access the
    # object that was signed.

    def get_leaf(self):
        """Return the leaf dictionary."""
        return self.leaf
    def get_blessing(self):
        """Return the Blessing object, or None if there was no signature."""
        return self.blessing

    def is_blessed_by(self, blessing_checker, logparent=None):
        """Return True if this object has a blessing that passes the checker,
        False otherwise."""
        return blessing_checker.check(self.blessing, logparent)

class PublicKeyBlessingChecker:
    def __init__(self, pubkey_vs):
        # pubkey_vs looks like "pub-v0-abcde123"
        self.pubkey = parse_pubkey_vs(pubkey_vs)

    def check(self, blessing, lp=None):
        if not blessing:
            log.msg("no blessing",
                    facility="tahoe.bless", parent=lp, level=log.NOISY)
            return False
        if blessing.pubkey_in_chain(self.pubkey):
            log.msg("good blessing",
                    facility="tahoe.bless", parent=lp, level=log.NOISY)
            return True

        my_s = self.pubkey.to_string()
        blessing_s = blessing.get_leaf_pubkey().to_string()
        log.msg("wrong blessing: want %s, got %s" % (base32.b2a(my_s),
                                                     base32.b2a(blessing_s)),
                facility="tahoe.bless", parent=lp, level=log.NOISY)
        return False
