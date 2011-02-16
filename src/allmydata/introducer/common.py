
import re, simplejson
from base64 import b32decode
from allmydata.util.ecdsa import VerifyingKey
from allmydata.util import base32, hashutil

def make_index(ann_d, key):
    """Return something that can be used as an index (e.g. a tuple of
    strings), such that two messages that refer to the same 'thing' will have
    the same index. For introducer announcements, this is a tuple of
    (service-name, signing-key), or (service-name, tubid) if the announcement
    is not signed."""

    service_name = str(ann_d["service-name"])
    if key:
        index = (service_name, key.to_string())
    else:
        # otherwise, use the FURL to get a tubid
        furl = str(ann_d["FURL"])
        m = re.match(r'pb://(\w+)@', furl)
        assert m
        tubid = b32decode(m.group(1).upper())
        index = (service_name, tubid)
    return index

def convert_announcement_v1_to_v2(ann_t):
    (furl, service_name, ri_name, nickname, ver, oldest) = ann_t
    assert type(furl) is str
    assert type(service_name) is str
    assert type(ri_name) is str
    assert type(nickname) is str
    assert type(ver) is str
    assert type(oldest) is str
    ann_d = {"version": 0,
             "service-name": service_name,
             "FURL": furl,
             "remoteinterface-name": ri_name,

             "nickname": nickname.decode("utf-8"),
             "app-versions": {},
             "my-version": ver,
             "oldest-supported": oldest,
             }
    return simplejson.dumps( (simplejson.dumps(ann_d), None, None) )

def convert_announcement_v2_to_v1(ann_v2):
    (msg, sig, pubkey) = simplejson.loads(ann_v2)
    ann_d = simplejson.loads(msg)
    assert ann_d["version"] == 0
    ann_t = (str(ann_d["FURL"]), str(ann_d["service-name"]),
             str(ann_d["remoteinterface-name"]),
             ann_d["nickname"].encode("utf-8"),
             str(ann_d["my-version"]),
             str(ann_d["oldest-supported"]),
             )
    return ann_t


def sign(ann_d, sk):
    # returns (bytes, None, None) or (bytes, str, str)
    msg = simplejson.dumps(ann_d).encode("utf-8")
    if not sk:
        return (msg, None, None)
    vk = sk.get_verifying_key()
    sig = sk.sign(msg, hashfunc=hashutil.SHA256)
    return (msg, "v0-"+base32.b2a(sig), "v0-"+base32.b2a(vk.to_string()))

class UnknownKeyError(Exception):
    pass

def unsign(ann_s):
    (msg_s, sig_vs, key_vs) = simplejson.loads(ann_s.decode("utf-8"))
    key = None
    if sig_vs and key_vs:
        if not sig_vs.startswith("v0-"):
            raise UnknownKeyError("only v0- signatures recognized")
        if not key_vs.startswith("v0-"):
            raise UnknownKeyError("only v0- keys recognized")
        key = VerifyingKey.from_string(base32.a2b(key_vs[3:]))
        key.verify(base32.a2b(sig_vs[3:]), msg_s, hashfunc=hashutil.SHA256)
    msg = simplejson.loads(msg_s.decode("utf-8"))
    return (msg, key)
