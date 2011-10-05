
import os
from twisted.application import service
from foolscap.api import Referenceable

class Account(Referenceable):
    def __init__(self, owner_num, server):
        self.owner_num = owner_num
        self.server = server

    def remote_get_version(self):
        return self.server.remote_get_version()
    def remote_get_status(self):
        return {"write": True, "read": True, "save": True}
    def remote_get_client_message(self):
        return {"message": "CLIENT MESSAGE WOO!"}
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

class Accountant(service.MultiService):
    def __init__(self, basedir, create_if_missing):
        service.MultiService.__init__(self)
        self.accountsdir = os.path.join(basedir, "accounts")
        if not os.path.isdir(self.accountsdir):
            os.mkdir(self.accountsdir)
            self._write_int(2, "next_ownernum")
        self.create_if_missing = create_if_missing

    def _read_int(self, *paths):
        fn = os.path.join(self.accountsdir, *paths)
        return int(open(fn).read().strip())
    def _write_int(self, num, *paths):
        fn = os.path.join(self.accountsdir, *paths)
        tmpfn = fn + ".tmp"
        f = open(tmpfn, "w")
        f.write("%d\n" % num)
        f.close()
        os.rename(tmpfn, fn)

    def get_account(self, pubkey_vs, storage_server):
        ownernum = self.get_ownernum_by_pubkey(pubkey_vs)
        return Account(ownernum, storage_server)

    def get_ownernum_by_pubkey(self, pubkey_vs):
        assert ("." not in pubkey_vs and "/" not in pubkey_vs)
        accountdir = os.path.join(self.accountsdir, pubkey_vs)
        if not os.path.isdir(accountdir):
            if not self.create_if_missing:
                return None
            next_ownernum = self._read_int("next_ownernum")
            self._write_int(next_ownernum+1, "next_ownernum")
            os.mkdir(accountdir)
            self._write_int(next_ownernum, pubkey_vs, "ownernum")
        ownernum = self._read_int(pubkey_vs, "ownernum")
        return ownernum
