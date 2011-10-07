
import os, time, weakref
from twisted.application import service
from foolscap.api import Referenceable
class BadAccountName(Exception):
    pass

class Account(Referenceable):
    def __init__(self, owner_num, server, accountdir):
        self.owner_num = owner_num
        self.server = server
        self.accountdir = accountdir
        self.connected = False
        self.connected_since = None

    def remote_get_version(self):
        return self.server.remote_get_version()
    def remote_get_status(self):
        import random
        def maybe(): return bool(random.randint(0,1))
        return {"write": maybe(), "read": maybe(), "save": maybe()}
    def remote_get_account_message(self):
        import random
        return {"message": "free storage! %d" % random.randint(0,10),
                "fancy": "free pony if you knew how to ask",
                }
    # all other RIStorageServer methods should pass through to self.server
    # but add owner_num=

    def remote_allocate_buckets(self, storage_index,
                                renew_secret, cancel_secret,
                                sharenums, allocated_size,
                                canary, owner_num=0):
        return self.server.remote_allocate_buckets(
            storage_index,
            renew_secret, cancel_secret,
            sharenums, allocated_size,
            canary, owner_num=self.owner_num)
    def remote_add_lease(self, storage_index, renew_secret, cancel_secret,
                         owner_num=1):
        return self.server.remote_add_lease(
            storage_index, renew_secret, cancel_secret,
            owner_num=self.owner_num)
    def remote_renew_lease(self, storage_index, renew_secret):
        return self.server.remote_renew_lease(storage_index, renew_secret)
    def remote_cancel_lease(self, storage_index, cancel_secret):
        return self.server.remote_cancel_lease(storage_index, cancel_secret)
    def remote_get_buckets(self, storage_index):
        return self.server.remote_get_buckets(storage_index)
    # TODO: add leases and ownernums to mutable shares
    def remote_slot_testv_and_readv_and_writev(self, storage_index,
                                               secrets,
                                               test_and_write_vectors,
                                               read_vector):
        return self.server.remote_slot_testv_and_readv_and_writev(
            storage_index,
            secrets,
            test_and_write_vectors,
            read_vector) # TODO: ownernum=
    def remote_slot_readv(self, storage_index, shares, readv):
        return self.server.remote_slot_readv(storage_index, shares, readv)
    def remote_advise_corrupt_share(self, share_type, storage_index, shnum,
                                    reason):
        return self.server.remote_advise_corrupt_share(
            share_type, storage_index, shnum, reason)

    # these are the non-RIStorageServer methods, some remote, some local

    def _read(self, *paths):
        fn = os.path.join(self.accountdir, *paths)
        try:
            return open(fn).read().strip()
        except EnvironmentError:
            return None
    def _write(self, s, *paths):
        fn = os.path.join(self.accountdir, *paths)
        tmpfn = fn + ".tmp"
        f = open(tmpfn, "w")
        f.write(s+"\n")
        f.close()
        os.rename(tmpfn, fn)

    def remote_set_nickname(self, nickname):
        if len(nickname) > 1000:
            raise ValueError("nickname too long")
        self._write(nickname.encode("utf-8"), "nickname")

    def get_nickname(self):
        n = self._read("nickname")
        if n is not None:
            return n.decode("utf-8")
        return u""

    def remote_get_current_usage(self):
        return self.get_current_usage()

    def get_current_usage(self):
        # read something out of a database, or something. For now, fake it.
        from random import random, randint
        return int(random() * (10**randint(1, 12)))

    def connection_from(self, rx):
        self.connected = True
        self.connected_since = time.time()
        rhost = rx.getPeer()
        from twisted.internet import address
        if isinstance(rhost, address.IPv4Address):
            rhost_s = "%s:%d" % (rhost.host, rhost.port)
        elif "LoopbackAddress" in str(rhost):
            rhost_s = "loopback"
        else:
            rhost_s = str(rhost)
        self._write(rhost_s, "last_connected_from")
        rx.notifyOnDisconnect(self._disconnected)

    def _disconnected(self):
        self.connected = False
        self.connected_since = None
        self._write(str(int(time.time())), "last_seen")
        self.disconnected_since = None

    def get_connection_status(self):
        # starts as: connected=False, connected_since=None,
        #            last_connected_from=None, last_seen=None
        # while connected: connected=True, connected_since=START,
        #                  last_connected_from=HOST, last_seen=IGNOREME
        # after disconnect: connected=False, connected_since=None,
        #                   last_connected_from=HOST, last_seen=STOP

        last_seen = self._read("last_seen")
        if last_seen is not None:
            last_seen = int(last_seen)
        return {"connected": self.connected,
                "connected_since": self.connected_since,
                "last_connected_from": self._read("last_connected_from"),
                "last_seen": last_seen,
                "created": int(self._read("created")),
                }

class Accountant(service.MultiService):
    def __init__(self, basedir, create_if_missing):
        service.MultiService.__init__(self)
        self.accountsdir = os.path.join(basedir, "accounts")
        if not os.path.isdir(self.accountsdir):
            os.mkdir(self.accountsdir)
            self._write("2", "next_ownernum")
        self.create_if_missing = create_if_missing
        self._active_accounts = weakref.WeakValueDictionary()

    def _read(self, *paths):
        fn = os.path.join(self.accountsdir, *paths)
        return open(fn).read().strip()
    def _write(self, s, *paths):
        fn = os.path.join(self.accountsdir, *paths)
        tmpfn = fn + ".tmp"
        f = open(tmpfn, "w")
        f.write(s+"\n")
        f.close()
        os.rename(tmpfn, fn)

    # methods used by StorageServer

    def get_account(self, pubkey_vs, storage_server):
        ownernum = self.get_ownernum_by_pubkey(pubkey_vs)
        if pubkey_vs not in self._active_accounts:
            a = Account(ownernum, storage_server,
                        os.path.join(self.accountsdir, pubkey_vs))
            self._active_accounts[pubkey_vs] = a
        return self._active_accounts[pubkey_vs] # a is still alive

    def get_ownernum_by_pubkey(self, pubkey_vs):
        if not re.search(r'^[a-zA-Z0-9+-_]+$', pubkey_vs):
            raise BadAccountName("unacceptable characters in pubkey")
        assert ("." not in pubkey_vs and "/" not in pubkey_vs)
        accountdir = os.path.join(self.accountsdir, pubkey_vs)
        if not os.path.isdir(accountdir):
            if not self.create_if_missing:
                return None
            next_ownernum = int(self._read("next_ownernum"))
            self._write(str(next_ownernum+1), "next_ownernum")
            os.mkdir(accountdir)
            self._write(str(next_ownernum), pubkey_vs, "ownernum")
            self._write(str(int(time.time())), pubkey_vs, "created")
        ownernum = int(self._read(pubkey_vs, "ownernum"))
        return ownernum

    # methods used by admin interfaces
    def get_all_accounts(self):
        for d in os.listdir(self.accountsdir):
            if d.startswith("pub-v0-"):
                yield (d, self.get_account(d, None)) # TODO: None is weird
