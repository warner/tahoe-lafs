
import unittest
import os, shutil
import subprocess
from hashlib import sha1

from keys import SigningKey, VerifyingKey
from util import hashfunc_truncate, sig_to_der, infunc_der
from curves import NIST192p, NIST224p, NIST384p, NIST521p

class SubprocessError(Exception):
    pass

def run(cmd):
    p = subprocess.Popen(cmd.split(),
                         stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT)
    stdout, ignored = p.communicate()
    if p.returncode != 0:
        raise SubprocessError("cmd '%s' failed: rc=%s, stdout/err was %s" %
                              (cmd, p.returncode, stdout))

class OpenSSL(unittest.TestCase):
    # test interoperability with OpenSSL tools
    # openssl ecparam -name secp224r1 -genkey -out privkey.pem
    # openssl ec -in privkey.pem -text -noout # get the priv/pub keys
    # openssl dgst -ecdsa-with-SHA1 -sign privkey.pem -out data.sig data.txt
    # openssl asn1parse -in data.sig -inform DER
    #  data.sig is 64 bytes, probably 56b plus ASN1 overhead
    # openssl dgst -ecdsa-with-SHA1 -prverify privkey.pem -signature data.sig data.txt ; echo $?
    # openssl ec -in privkey.pem -pubout -out pubkey.pem
    # openssl ec -in privkey.pem -pubout -outform DER -out pubkey.der

    # sk: 1:OpenSSL->python  2:python->OpenSSL
    # vk: 3:OpenSSL->python  4:python->OpenSSL
    # sig: 5:OpenSSL->python 6:python->OpenSSL

    def test_from_openssl_nist192p(self):
        return self.do_test_from_openssl(NIST192p, "prime192v1")
    def test_from_openssl_nist224p(self):
        return self.do_test_from_openssl(NIST224p, "secp224r1")
    def test_from_openssl_nist384p(self):
        return self.do_test_from_openssl(NIST384p, "secp384r1")
    def test_from_openssl_nist521p(self):
        return self.do_test_from_openssl(NIST521p, "secp521r1")

    def do_test_from_openssl(self, curve, curvename):
        # OpenSSL: create sk, vk, sign.
        # Python: read vk(3), checksig(5), read sk(1), sign, check
        if os.path.isdir("t"):
            shutil.rmtree("t")
        os.mkdir("t")
        run("openssl ecparam -name %s -genkey -out t/privkey.pem" % curvename)
        run("openssl ec -in t/privkey.pem -pubout -out t/pubkey.pem")
        data = "data"
        open("t/data.txt","wb").write(data)
        run("openssl dgst -ecdsa-with-SHA1 -sign t/privkey.pem -out t/data.sig t/data.txt")
        run("openssl dgst -ecdsa-with-SHA1 -verify t/pubkey.pem -signature t/data.sig t/data.txt")
        pubkey_pem = open("t/pubkey.pem").read()
        vk = VerifyingKey.from_pem(pubkey_pem) # 3
        sig_der = open("t/data.sig","rb").read()
        self.failUnless(vk.verify(sig_der, data, # 5
                                  hashfunc=hashfunc_truncate(sha1),
                                  infunc=infunc_der))

        sk = SigningKey.from_pem(open("t/privkey.pem").read()) # 1
        sig = sk.sign(data)
        self.failUnless(vk.verify(sig, data))

    def test_to_openssl_nist192p(self):
        self.do_test_to_openssl(NIST192p, "prime192v1")
    def test_to_openssl_nist224p(self):
        self.do_test_to_openssl(NIST224p, "secp224r1")
    def test_to_openssl_nist384p(self):
        self.do_test_to_openssl(NIST384p, "secp384r1")
    def test_to_openssl_nist521p(self):
        self.do_test_to_openssl(NIST521p, "secp521r1")

    def do_test_to_openssl(self, curve, curvename):
        # Python: create sk, vk, sign.
        # OpenSSL: read vk(4), checksig(6), read sk(2), sign, check
        if os.path.isdir("t"):
            shutil.rmtree("t")
        os.mkdir("t")
        sk = SigningKey.generate(curve=curve)
        vk = sk.get_verifying_key()
        data = "data"
        open("t/pubkey.der","wb").write(vk.to_der()) # 4
        open("t/pubkey.pem","wb").write(vk.to_pem()) # 4
        sig_der = sk.sign(data, hashfunc=hashfunc_truncate(sha1),
                          outfunc=sig_to_der)
        open("t/data.sig","wb").write(sig_der) # 6
        open("t/data.txt","wb").write(data)
        open("t/baddata.txt","wb").write(data+"corrupt")

        self.failUnlessRaises(SubprocessError, run,
                              "openssl dgst -ecdsa-with-SHA1 -verify t/pubkey.der -keyform DER -signature t/data.sig t/baddata.txt")
        run("openssl dgst -ecdsa-with-SHA1 -verify t/pubkey.der -keyform DER -signature t/data.sig t/data.txt")

        open("t/privkey.pem","wb").write(sk.to_pem()) # 2
        run("openssl dgst -ecdsa-with-SHA1 -sign t/privkey.pem -out t/data.sig2 t/data.txt")
        run("openssl dgst -ecdsa-with-SHA1 -verify t/pubkey.pem -signature t/data.sig2 t/data.txt")

del OpenSSL # subprocess.Popen conflicts with twisted's reactor

if __name__ == "__main__":
    unittest.main()
