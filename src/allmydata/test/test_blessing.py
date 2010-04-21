
from twisted.trial import unittest

import simplejson
from allmydata import bless
from allmydata.scripts.admin import make_keypair
from allmydata.util.testutil import flip_bit
from allmydata.util import base32, netstring

class Blessing(unittest.TestCase):
    def test_parse(self):
        priv_vs, pub_vs = make_keypair()
        pub = bless.parse_pubkey_vs(pub_vs)
        priv,pub2,pub2_s = bless.parse_privkey_vs(priv_vs)
        self.failUnlessEqual(pub.serialize(), pub2_s)
        self.failUnlessEqual(pub2.serialize(), pub2_s)
        self.failUnlessEqual(priv.get_verifying_key().serialize(), pub2_s)

    def test_non_blesser(self):
        b = bless.NonBlesser()
        cc = b.bless_now({"a":"b"})
        self.failUnless(isinstance(cc, str))
        self.failUnless(cc.startswith("ach0:1:"), cc)
        d = b.bless({"a":"b"})
        def _check(cc2):
            self.failUnless(isinstance(cc2, str))
            self.failUnless(cc2.startswith("ach0:1:"), cc2)
        d.addCallback(_check)
        return d

    def test_privkey_blesser(self):
        priv_vs, pub_vs = make_keypair()
        pub = bless.parse_pubkey_vs(pub_vs)
        wrong_priv_vs, wrong_pub_vs = make_keypair()
        wrong_pub = bless.parse_pubkey_vs(wrong_pub_vs)

        b = bless.PrivateKeyBlesser(priv_vs)
        msg = {"a": "b"}
        cc = b.bless_now(msg)
        self.failUnless(isinstance(cc, str))
        self.failUnless(cc.startswith("ach0:1:"), cc)
        bo = bless.BlessedObject.from_certificate_chain(cc)
        self.failUnlessEqual(bo.get_leaf(), msg) # modulo unicodeness
        b2 = bo.get_blessing()
        self.failUnless(isinstance(b2, bless.CertChainBlessing))
        self.failUnlessEqual(b2.get_leaf_pubkey().serialize(), pub.serialize())
        self.failUnless(b2.pubkey_in_chain(pub))
        self.failIf(b2.pubkey_in_chain(wrong_pub))
        short = b2.get_short_display()
        self.failUnless(isinstance(short, str)) # TODO: more

        d = b.bless(msg)
        def _check(cc2):
            self.failUnless(isinstance(cc2, str))
            self.failUnless(cc2.startswith("ach0:1:"), cc2)
        d.addCallback(_check)
        return d

    def test_chain_blesser(self):
        priv_vs, pub_vs = make_keypair() # leaf
        pub = bless.parse_pubkey_vs(pub_vs)
        priv2_vs, pub2_vs = make_keypair() # root
        pub2 = bless.parse_pubkey_vs(pub2_vs)
        wrong_priv_vs, wrong_pub_vs = make_keypair()
        wrong_pub = bless.parse_pubkey_vs(wrong_pub_vs)

        b = bless.PrivateKeyBlesser(priv_vs, priv2_vs)
        msg = {"a": "b"}
        cc = b.bless_now(msg)
        self.failUnless(isinstance(cc, str))
        self.failUnless(cc.startswith("ach0:2:"), cc)
        bo = bless.BlessedObject.from_certificate_chain(cc)
        self.failUnlessEqual(bo.get_leaf(), msg) # modulo unicodeness
        b2 = bo.get_blessing()
        self.failUnless(isinstance(b2, bless.CertChainBlessing))
        self.failUnlessEqual(b2.get_leaf_pubkey().serialize(), pub.serialize())
        self.failUnless(b2.pubkey_in_chain(pub))
        self.failUnless(b2.pubkey_in_chain(pub2))
        self.failIf(b2.pubkey_in_chain(wrong_pub))
        short = b2.get_short_display()
        self.failUnless(isinstance(short, str)) # TODO: more

        d = b.bless(msg)
        def _check(cc2):
            self.failUnless(isinstance(cc2, str))
            self.failUnless(cc2.startswith("ach0:2:"), cc2)
        d.addCallback(_check)
        return d

    def test_corrupt_sigs(self):
        # create badly signed/corrupted chains to exercise the error cases
        priv_vs, pub_vs = make_keypair() # leaf
        pub = bless.parse_pubkey_vs(pub_vs)
        priv2_vs, pub2_vs = make_keypair() # root
        pub2 = bless.parse_pubkey_vs(pub2_vs)
        wrong_priv_vs, wrong_pub_vs = make_keypair()
        wrong_pub = bless.parse_pubkey_vs(wrong_pub_vs)

        b = bless.PrivateKeyBlesser(priv_vs)
        msg = {"a": "b"}
        cc = b.bless_now(msg)

        parse = bless.BlessedObject.from_certificate_chain
        self.failUnlessRaises(AssertionError, parse, "BOGUS"+cc)
        cc_bad = "ach1:" + cc[len("ach1:"):]
        self.failUnlessRaises(AssertionError, parse, cc_bad)

        # we happen to know that the "a" in the message is at offset 19. This
        # will change when the pubkey gets smaller.
        assert cc[19] == "a", cc[19]
        self.failUnlessRaises(bless.BadSignatureError, parse, flip_bit(cc, 19))

        # and the 'delegate-to-pubkey' string is at offset 20
        b2 = bless.PrivateKeyBlesser(priv_vs, priv2_vs)
        cc = b2.bless_now(msg)
        assert cc[20] == "d", cc[20]
        self.failUnlessRaises(bless.BadSignatureError, parse, flip_bit(cc, 20))

    def _create_blessing(self, what, privkey, pubkey_s,
                         blesser_privkey, blesser_pubkey_s,
                         delegate_format=0, pubkey_prefix="pub-v0-",
                         delegate_pubkey_s=None):
        assert isinstance(what, dict)
        ann_j = simplejson.dumps(what)
        sig = privkey.sign(ann_j)
        sig_b32 = base32.b2a(sig)
        pubkey_b32 = base32.b2a(pubkey_s)
        NS = netstring.netstring
        leaf_cert = "c0:" + NS(ann_j) + NS(sig_b32) + NS(pubkey_b32) + "\n"

        if blesser_privkey:
            if not delegate_pubkey_s:
                delegate_pubkey_s = pubkey_s
            node_pubkey_vs = pubkey_prefix + base32.b2a(delegate_pubkey_s)
            bless_j = simplejson.dumps({"version": delegate_format,
                                        "delegate-to-pubkey": node_pubkey_vs,
                                        })
            bsig = blesser_privkey.sign(bless_j)
            bsig_b32 = base32.b2a(bsig)
            bpubkey_b32 = base32.b2a(blesser_pubkey_s)
            bcert = "c0:" + NS(bless_j) + NS(bsig_b32) + NS(bpubkey_b32) + "\n"
            certs = [bcert, leaf_cert]
        else:
            certs = [leaf_cert]

        pieces = ["ach0:", str(len(certs)), ":"]
        pieces.extend([NS(c) for c in certs])
        pieces.append("\n")
        chain = "".join(pieces)
        return chain

    def test_bad_certs(self):
        priv_vs, pub_vs = make_keypair() # leaf
        priv, pub, pub_s = bless.parse_privkey_vs(priv_vs)
        priv2_vs, pub2_vs = make_keypair() # root
        priv2, pub2, pub2_s = bless.parse_privkey_vs(priv2_vs)
        privwrong_vs, pubwrong_vs = make_keypair()
        privwrong, pubwrong, pubwrong_s = bless.parse_privkey_vs(privwrong_vs)

        # construct the delegate cert with bad ['version']. This requires
        # some fussing.
        msg = {"a": "b"}
        cc = self._create_blessing(msg, priv, pub_s, priv2, pub2_s,
                                   delegate_format=1)
        parse = bless.BlessedObject.from_certificate_chain
        self.failUnlessRaises(bless.UnknownDelegationFormatError,
                              parse, cc)

        #  and one with pubkey not in 'pub-v0-' format
        cc = self._create_blessing(msg, priv, pub_s, priv2, pub2_s,
                                   pubkey_prefix="pub-v1-")
        parse = bless.BlessedObject.from_certificate_chain
        self.failUnlessRaises(bless.UnknownDelegationFormatError,
                              parse, cc)

        #  and one with the wrong pubkey
        cc = self._create_blessing(msg, priv, pub_s, priv2, pub2_s,
                                   delegate_pubkey_s=pubwrong_s)
        parse = bless.BlessedObject.from_certificate_chain
        self.failUnlessRaises(bless.BadDelegationError,
                              parse, cc)




class Checker(unittest.TestCase):

    def _loop(self, b):
        msg = {"a": "b"}
        cc = b.bless_now(msg)
        return bless.BlessedObject.from_certificate_chain(cc)

    def test_checker(self):
        priv_vs, pub_vs = make_keypair()
        wrong_priv_vs, wrong_pub_vs = make_keypair()

        c = bless.PublicKeyBlessingChecker(pub_vs)

        b = bless.NonBlesser()
        bo = self._loop(b)
        self.failIf(bo.is_blessed_by(c))

        b = bless.PrivateKeyBlesser(priv_vs)
        bo = self._loop(b)
        self.failUnless(bo.is_blessed_by(c))

        b = bless.PrivateKeyBlesser(wrong_priv_vs)
        bo = self._loop(b)
        self.failIf(bo.is_blessed_by(c))

