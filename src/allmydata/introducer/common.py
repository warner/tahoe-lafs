
import re, simplejson
from base64 import b32decode
from allmydata.util.ecdsa import VerifyingKey

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
    msg = simplejson.dumps(ann_d)
    if not sk:
        return (msg, None, None)
    vk = sk.get_verifying_key()
    return (msg, sk.sign(msg).encode("hex"), vk.to_string().encode("hex"))

def unsign(ann_s):
    (msg_s, sig_s, key_s) = simplejson.loads(ann_s)
    key = None
    if sig_s and key_s:
        key = VerifyingKey.from_string(key_s.decode("hex"))
        key.verify(sig_s.decode("hex"), msg_s)
    msg = simplejson.loads(msg_s)
    return (msg, key)
