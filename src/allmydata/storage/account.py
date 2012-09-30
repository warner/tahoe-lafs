
"""
This file contains the client-facing interface for manipulating shares. It
implements RIStorageServer, and contains an embedded owner id which is used
for all operations that touch leases. Initially, clients will receive a
special 'anonymous' instance of this class with ownerid=0. Later, when the
FURLification dance is established, each client will get a different instance
(with a dedicated ownerid).
"""

import time

from foolscap.api import Referenceable

from zope.interface import implements
from allmydata.interfaces import RIStorageServer

from allmydata.storage.leasedb import int_or_none
from allmydata.storage.common import si_b2a


class Account(Referenceable):
    implements(RIStorageServer)

    def __init__(self, owner_num, pubkey_vs, server, leasedb):
        self.owner_num = owner_num
        self.server = server
        self._leasedb = leasedb
        # for static accounts ("starter", "anonymous"), pubkey_vs is None,
        # and the "connected" attributes are unused
        self.pubkey_vs = pubkey_vs
        self.connected = False
        self.connected_since = None
        self.connection = None
        self.can_write = True
        self.can_read = True
        self.can_save = True
        import random
        self.account_message = {
            "message": "free storage! %d" % random.randint(0,10),
            "fancy": "free pony if you knew how to ask",
            }
        self.debug = True

    def is_static(self):
        return self.owner_num in (0,1)

    # these methods are called by StorageServer

    def get_owner_num(self):
        return self.owner_num

    def get_renewal_and_expiration_times(self):
        renewal_time = time.time()
        return (renewal_time, renewal_time + 31*24*60*60)

    # immutable.BucketWriter.close() does:
    #  add_share(), add_lease(), mark_share_as_stable()

    # mutable_writev() does:
    #  deleted shares: mark_share_as_going(), remove_share_and_leases()
    #  new shares: add_share(), add_lease(), mark_share_as_stable()
    #  changed shares: change_share_space(), add_lease()

    def add_share(self, storage_index, shnum, used_space, commit=True):
        if self.debug: print "ADD_SHARE", si_b2a(storage_index), shnum, used_space, commit
        self._leasedb.add_new_share(storage_index, shnum, used_space)
        if commit:
            self._leasedb.commit()

    def add_or_renew_default_lease(self, storage_index, shnum, commit=True):
        renewal_time, expiration_time = self.get_renewal_and_expiration_times()
        return self.add_or_renew_lease(storage_index, shnum, renewal_time, expiration_time, commit=commit)

    def add_or_renew_lease(self, storage_index, shnum, renewal_time, expiration_time, commit=True):
        if self.debug: print "ADD_OR_RENEW_LEASE", si_b2a(storage_index), shnum, commit
        self._leasedb.add_or_renew_leases(storage_index, shnum, self.owner_num,
                                          renewal_time, expiration_time)
        if commit:
            self._leasedb.commit()

    def change_share_space(self, storage_index, shnum, used_space, commit=True):
        # XXX do we actually need this?
        if self.debug: print "CHANGE_SHARE_SPACE", si_b2a(storage_index), shnum, used_space, commit
        self._leasedb.change_share_space(storage_index, shnum, used_space)
        if commit:
            self._leasedb.commit()

    def mark_share_as_stable(self, storage_index, shnum, used_space, commit=True):
        if self.debug: print "MARK_SHARE_AS_STABLE", si_b2a(storage_index), shnum, used_space, commit
        self._leasedb.mark_share_as_stable(storage_index, shnum, used_space)
        if commit:
            self._leasedb.commit()

    def mark_share_as_going(self, storage_index, shnum, commit=True):
        if self.debug: print "MARK_SHARE_AS_GOING", si_b2a(storage_index), shnum, commit
        self._leasedb.mark_share_as_going(storage_index, shnum)
        if commit:
            self._leasedb.commit()

    def remove_share_and_leases(self, storage_index, shnum, commit=True):
        if self.debug: print "REMOVE_SHARE_AND_LEASES", si_b2a(storage_index), shnum, commit
        self._leasedb.remove_deleted_share(storage_index, shnum)
        if commit:
            self._leasedb.commit()

    # remote_add_lease() and remote_renew_lease() do this
    def add_lease_for_bucket(self, storage_index, commit=True):
        if self.debug: print "ADD_LEASE_FOR_BUCKET", si_b2a(storage_index), commit
        renewal_time, expiration_time = self.get_renewal_and_expiration_times()
        self._leasedb.add_or_renew_leases(storage_index, None,
                                          self.owner_num, renewal_time, expiration_time)
        if commit:
            self._leasedb.commit()

    def commit(self):
        self._leasedb.commit()

    # The following RIStorageServer methods are called by remote clients

    def remote_get_version(self):
        return self.server.client_get_version(self)

    # all other RIStorageServer methods should pass through to self.server
    # but (except for remote_advise_corrupt_share) add the account as a final
    # argument.

    def remote_allocate_buckets(self, storage_index, renew_secret, cancel_secret,
                                sharenums, allocated_size, canary):
        if self.debug: print "REMOTE_ALLOCATE_BUCKETS", si_b2a(storage_index)
        return self.server.client_allocate_buckets(storage_index,
                                                   sharenums, allocated_size,
                                                   canary, self)

    def remote_add_lease(self, storage_index, renew_secret, cancel_secret):
        if self.debug: print "REMOTE_ADD_LEASE", si_b2a(storage_index)
        self.add_lease_for_bucket(storage_index)
        return None

    def remote_renew_lease(self, storage_index, renew_secret):
        self.add_lease_for_bucket(storage_index)
        return None

    def remote_get_buckets(self, storage_index):
        return self.server.client_get_buckets(storage_index)

    def remote_slot_testv_and_readv_and_writev(self, storage_index, secrets,
                                               test_and_write_vectors, read_vector):
        write_enabler = secrets[0]
        return self.server.client_slot_testv_and_readv_and_writev(
            storage_index, write_enabler, test_and_write_vectors, read_vector, self)

    def remote_slot_readv(self, storage_index, shares, readv):
        return self.server.client_slot_readv(storage_index, shares, readv, self)

    def remote_advise_corrupt_share(self, share_type, storage_index, shnum, reason):
        # this doesn't use the account.
        return self.server.client_advise_corrupt_share(
            share_type, storage_index, shnum, reason)


    # these are the non-RIStorageServer methods, some remote, some local

    def get_account_attribute(self, name):
        return self._leasedb.get_account_attribute(self.owner_num, name)

    def set_account_attribute(self, name, value):
        self._leasedb.set_account_attribute(self.owner_num, name, value)

    def get_account_creation_time(self):
        return self._leasedb.get_account_creation_time(self.owner_num)

    def remote_get_status(self):
        return self.get_status()

    def get_status(self):
        return { "write": self.can_write,
                 "read":  self.can_read,
                 "save":  self.can_save,
               }

    def remote_get_account_message(self):
        return self.account_message

    def set_nickname(self, nickname):
        if len(nickname) > 1000:
            raise ValueError("nickname too long")
        self.set_account_attribute("nickname", nickname)

    def get_nickname(self):
        n = self.get_account_attribute("nickname")
        if n:
            return n
        return u""

    def get_id(self):
        return self.pubkey_vs

    def remote_get_current_usage(self):
        return self.get_current_usage()

    def get_current_usage(self):
        return self._leasedb.get_account_usage(self.owner_num)

    def get_leases(self, storage_index):
        return self._leasedb.get_leases(storage_index, self.owner_num)

    def connection_from(self, rx):
        self.connected = True
        self.connected_since = time.time()
        self.connection = rx
        rhost = rx.getPeer()
        from twisted.internet import address
        if isinstance(rhost, address.IPv4Address):
            rhost_s = "%s:%d" % (rhost.host, rhost.port)
        elif "LoopbackAddress" in str(rhost):
            rhost_s = "loopback"
        else:
            rhost_s = str(rhost)
        self.set_account_attribute("last_connected_from", rhost_s)
        rx.notifyOnDisconnect(self._disconnected)

    def _disconnected(self):
        self.connected = False
        self.connected_since = None
        self.connection = None
        self.set_account_attribute("last_seen", int(time.time()))
        self.disconnected_since = None

    def _send_status(self):
        self.connection.callRemoteOnly("status", self.get_status())

    def _send_account_message(self):
        self.connection.callRemoteOnly("account_message", self.account_message)

    def set_status(self, write, read, save):
        self.can_write = write
        self.can_read = read
        self.can_save = save
        self._send_status()

    def set_account_message(self, message):
        self.account_message = message
        self._send_account_message()

    def get_connection_status(self):
        # starts as: connected=False, connected_since=None,
        #            last_connected_from=None, last_seen=None
        # while connected: connected=True, connected_since=START,
        #                  last_connected_from=HOST, last_seen=IGNOREME
        # after disconnect: connected=False, connected_since=None,
        #                   last_connected_from=HOST, last_seen=STOP

        last_seen = int_or_none(self.get_account_attribute("last_seen"))
        last_connected_from = self.get_account_attribute("last_connected_from")
        created = int_or_none(self.get_account_creation_time())

        return {"connected": self.connected,
                "connected_since": self.connected_since,
                "last_connected_from": last_connected_from,
                "last_seen": last_seen,
                "created": created,
                }

    # used by tests

    def _get_sharedir(self):
        return self.server.sharedir

    def _iter_share_files(self, storage_index):
        return self.server._iter_share_files(storage_index)

    def _get_bucket_shares(self, storage_index):
        return self.server._get_bucket_shares(storage_index)

    def disownServiceParent(self):
        return self.server.disownServiceParent()
