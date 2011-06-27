
import os
from allmydata.util import base32

class FileProhibited(Exception):
    """This client has been configured to prohibit access to this object."""
    def __init__(self, reason):
        self.reason = reason


class Blacklist:
    def __init__(self, blacklist_fn):
        self.blacklist_fn = blacklist_fn
        self.last_mtime = None
        self.entries = {}
        self.read_blacklist() # sets .last_mtime and .entries

    def read_blacklist(self):
        current_mtime = os.stat(self.blacklist_fn).st_mtime
        if self.last_mtime is None or current_mtime > self.last_mtime:
            self.entries = {}
            for line in open(self.blacklist_fn, "r").readlines():
                si_s, reason = line.split()[:2]
                assert base32.a2b(si_s) # must be valid base32
                self.entries[si_s] = reason
            self.last_mtime = current_mtime

    def check_storageindex(self, si):
        self.read_blacklist()
        reason = self.entries.get(base32.b2a(si), None)
        if reason:
            raise FileProhibited(reason)
