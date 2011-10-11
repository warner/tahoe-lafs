
import simplejson
import os, time, weakref, re
from zope.interface import implements
from twisted.application import service
from foolscap.api import Referenceable
from allmydata.interfaces import RIStorageServer
from allmydata.util import log, keyutil, dbutil
from allmydata.storage.crawler import ShareCrawler

class BadAccountName(Exception):
    pass
class BadShareID(Exception):
    pass

def int_or_none(s):
    if s is None:
        return s
    return int(s)

LEASE_SCHEMA_V1 = """
CREATE TABLE version
(
 version INTEGER -- contains one row, set to 1
);

CREATE TABLE shares
(
 `id` INTEGER PRIMARY KEY AUTOINCREMENT,
 `prefix` VARCHAR(2),
 `storage_index` VARCHAR(26),
 `shnum` INTEGER,
 `size` INTEGER
);

CREATE INDEX `prefix` ON shares (`prefix`);
CREATE UNIQUE INDEX `share_id` ON shares (`storage_index`,`shnum`);

CREATE TABLE leases
(
 `id` INTEGER PRIMARY KEY AUTOINCREMENT,
 -- FOREIGN KEY (`share_id`) REFERENCES shares(id), -- not enabled?
 -- FOREIGN KEY (`account_id`) REFERENCES accounts(id),
 `share_id` INTEGER,
 `account_id` INTEGER,
 `expiration_time` INTEGER
);

CREATE INDEX `account_id` ON `leases` (`account_id`);
CREATE INDEX `expiration_time` ON `leases` (`expiration_time`);

CREATE TABLE accounts
(
 `id` INTEGER PRIMARY KEY AUTOINCREMENT,
 `pubkey_vs` VARCHAR(52),
 `creation_time` INTEGER
);
CREATE UNIQUE INDEX `pubkey_vs` ON `accounts` (`pubkey_vs`);

CREATE TABLE account_attributes
(
 `id` INTEGER PRIMARY KEY AUTOINCREMENT,
 `account_id` INTEGER,
 `name` VARCHAR(20),
 `value` VARCHAR(20) -- actually anything: usually string, unicode, integer
 );
CREATE UNIQUE INDEX `account_attr` ON `account_attributes` (`account_id`, `name`);

INSERT INTO `accounts` VALUES (0, "anonymous", 0);
INSERT INTO `accounts` VALUES (1, "starter", 0);

"""

DAY = 24*60*60
MONTH = 30*DAY

class LeaseDB:
    STARTER_LEASE_ACCOUNTID = 1
    STARTER_LEASE_DURATION = 2*MONTH

    # for all methods that start by setting self._dirty=True, be sure to call
    # .commit() when you're done

    def __init__(self, dbfile):
        (self._sqlite,
         self._db) = dbutil.get_db(dbfile, create_version=(LEASE_SCHEMA_V1, 1))
        self._cursor = self._db.cursor()
        self._dirty = False

    # share management

    def get_shares_for_prefix(self, prefix):
        self._cursor.execute("SELECT `storage_index`,`shnum`"
                             " FROM `shares`"
                             " WHERE `prefix` == ?",
                             (prefix,))
        db_shares = set([(si,shnum) for (si,shnum) in self._cursor.fetchall()])
        return db_shares

    def add_new_share(self, prefix, storage_index, shnum, size):
        self._dirty = True
        self._cursor.execute("INSERT INTO `shares`"
                             " VALUES (?,?,?,?,?)",
                             (None, prefix, storage_index, shnum, size))
        shareid = self._cursor.lastrowid
        return shareid

    def add_starter_lease(self, shareid):
        self._dirty = True
        self._cursor.execute("INSERT INTO `leases`"
                             " VALUES (?,?,?,?)",
                             (None, shareid, self.STARTER_LEASE_ACCOUNTID,
                              int(time.time()+self.STARTER_LEASE_DURATION)))
        leaseid = self._cursor.lastrowid
        return leaseid

    def remove_deleted_shares(self, shareids):
        # TODO: replace this with a sensible DELETE, join, and sub-SELECT
        shareids2 = []
        for deleted_shareid in shareids:
            storage_index, shnum = deleted_shareid
            self._cursor.execute("SELECT `id` FROM `shares`"
                                 " WHERE `storage_index`=? AND `shnum`=?",
                                 (storage_index, shnum))
            row = self._cursor.fetchone()
            if row:
                shareids2.append(row[0])
        for shareid2 in shareids2:
            self._dirty = True
            self._cursor.execute("DELETE FROM `leases`"
                                 " WHERE `share_id`=?",
                                 (shareid2,))

    def change_share_size(self, storage_index, shnum, size):
        self._dirty = True
        self._cursor.execute("UPDATE `shares` SET `size`=?"
                             " WHERE storage_index=? AND shnum=?",
                             (size, storage_index, shnum))

    # lease management

    def add_or_renew_leases(self, storage_index, shnum, ownerid,
                            expiration_time):
        # shnum=None means renew leases on all shares
        self._dirty = True
        if shnum is None:
            self._cursor.execute("SELECT `id` FROM `shares`"
                                 " WHERE `storage_index`=?",
                                 (storage_index,))
        else:
            self._cursor.execute("SELECT `id` FROM `shares`"
                                 " WHERE `storage_index`=? AND `shnum`=?",
                                 (storage_index, shnum))
        rows = self._cursor.fetchall()
        if not rows:
            raise BadShareID("can't find SI=%s shnum=%s in `shares` table"
                             % (storage_index, shnum))
        for (shareid,) in rows:
            self._cursor.execute("SELECT `id` FROM `leases`"
                                 " WHERE `share_id`=? AND `account_id`=?",
                                 (shareid, ownerid))
            row = self._cursor.fetchone()
            if row:
                leaseid = row[0]
                self._cursor.execute("UPDATE `leases` SET expiration_time=?"
                                     " WHERE `id`=?",
                                     (expiration_time, leaseid))
            else:
                self._cursor.execute("INSERT INTO `leases` VALUES (?,?,?,?)",
                                     (None, shareid, ownerid, expiration_time))

    # account management

    def get_account_usage(self, accountid):
        self._cursor.execute("SELECT SUM(`size`) FROM shares"
                             " WHERE `id` IN"
                             "  (SELECT DISTINCT `share_id` FROM `leases`"
                             "   WHERE `account_id`=?)",
                             (accountid,))
        row = self._cursor.fetchone()
        if not row or not row[0]: # XXX why did I need the second clause?
            return 0
        return row[0]

    def get_account_attribute(self, accountid, name):
        self._cursor.execute("SELECT `value` FROM `account_attributes`"
                             " WHERE account_id=? AND name=?",
                             (accountid, name))
        row = self._cursor.fetchone()
        if row:
            return row[0]
        return None

    def set_account_attribute(self, accountid, name, value):
        self._cursor.execute("SELECT `id` FROM `account_attributes`"
                             " WHERE `account_id`=? AND `name`=?",
                             (accountid, name))
        row = self._cursor.fetchone()
        if row:
            attrid = row[0]
            self._cursor.execute("UPDATE `account_attributes`"
                                 " SET `value`=?"
                                 " WHERE `id`=?",
                                 (value, attrid))
        else:
            self._cursor.execute("INSERT INTO `account_attributes`"
                                 " VALUES (?,?,?,?)",
                                 (None, accountid, name, value))
        self._db.commit()

    def get_or_allocate_ownernum(self, pubkey_vs):
        if not re.search(r'^[a-zA-Z0-9+-_]+$', pubkey_vs):
            raise BadAccountName("unacceptable characters in pubkey")
        self._cursor.execute("SELECT `id` FROM `accounts` WHERE `pubkey_vs`=?",
                             (pubkey_vs,))
        row = self._cursor.fetchone()
        if row:
            return row[0]
        self._cursor.execute("INSERT INTO `accounts` VALUES (?,?,?)",
                             (None, pubkey_vs, int(time.time())))
        accountid = self._cursor.lastrowid
        self._db.commit()
        return accountid

    def get_account_creation_time(self, owner_num):
        self._cursor.execute("SELECT `creation_time` from `accounts`"
                             " WHERE `id`=?",
                             (owner_num,))
        row = self._cursor.fetchone()
        if row:
            return row[0]
        return None

    def get_all_accounts(self):
        self._cursor.execute("SELECT `id`,`pubkey_vs`"
                             " FROM `accounts` ORDER BY `id` ASC")
        return self._cursor.fetchall()

    def commit(self):
        if self._dirty:
            self._db.commit()
            self._dirty = False


def size_of_disk_file(filename):
    s = os.stat(filename)
    sharebytes = s.st_size
    try:
        # note that stat(2) says that st_blocks is 512 bytes, and that
        # st_blksize is "optimal file sys I/O ops blocksize", which is
        # independent of the block-size that st_blocks uses.
        diskbytes = s.st_blocks * 512
    except AttributeError:
        # the docs say that st_blocks is only on linux. I also see it on
        # MacOS. But it isn't available on windows.
        diskbytes = sharebytes
    return diskbytes


class BaseAccount(Referenceable):
    def __init__(self, owner_num, server, leasedb):
        self.owner_num = owner_num
        self.server = server
        self._leasedb = leasedb

    # these methods are called by StorageServer

    def get_owner_num(self):
        return self.owner_num

    def get_expiration_time(self):
        return time.time() + 31*24*60*60

    # immutable.BucketWriter.close() does add_share() and add_lease()

    # mutable_writev() does:
    #  deleted shares: remove_share_and_leases()
    #  new shares: add_share(), add_lease()
    #  changed shares: update_share(), add_lease()

    def add_share(self, prefix, storage_index, shnum, filename, commit=True):
        size = size_of_disk_file(filename)
        self._leasedb.add_new_share(prefix, storage_index, shnum, size)
        if commit:
            self._leasedb.commit()

    def add_lease(self, storage_index, shnum, commit=True):
        expire_time = self.get_expiration_time()
        self._leasedb.add_or_renew_leases(storage_index, shnum,
                                          self.owner_num, expire_time)
        if commit:
            self._leasedb.commit()

    def update_share(self, storage_index, shnum, filename, commit=True):
        size = size_of_disk_file(filename)
        self._leasedb.change_share_size(storage_index, shnum, size)
        if commit:
            self._leasedb.commit()

    def remove_share_and_leases(self, storage_index, shnum):
        self._leasedb.remove_deleted_shares([storage_index, shnum])

    # remote_add_lease() and remote_renew_lease() do this
    def add_lease_for_bucket(self, storage_index, commit=True):
        expire_time = self.get_expiration_time()
        self._leasedb.add_or_renew_leases(storage_index, None,
                                          self.owner_num, expire_time)
        if commit:
            self._leasedb.commit()

    def commit(self):
        self._leasedb.commit()

    # The following RIStorageServer methods are called by remote clients

    def remote_get_version(self):
        return self.server.client_get_version(self)
    # all other RIStorageServer methods should pass through to self.server
    # but add owner_num=

    def remote_allocate_buckets(self, storage_index,
                                renew_secret, cancel_secret,
                                sharenums, allocated_size,
                                canary):
        return self.server.client_allocate_buckets(storage_index,
                                                   sharenums, allocated_size,
                                                   canary, self)
    def remote_add_lease(self, storage_index, renew_secret, cancel_secret):
        self.add_lease_for_bucket(storage_index)
        return None
    def remote_renew_lease(self, storage_index, renew_secret):
        self.add_lease_for_bucket(storage_index)
        return None
    #def remote_cancel_lease(self, storage_index, cancel_secret):
    #    raise NotImplementedError
    def remote_get_buckets(self, storage_index):
        return self.server.client_get_buckets(storage_index, self)
    def remote_slot_testv_and_readv_and_writev(self, storage_index,
                                               secrets,
                                               test_and_write_vectors,
                                               read_vector):
        (write_enabler, renew_secret, cancel_secret) = secrets
        meth = self.server.client_slot_testv_and_readv_and_writev
        return meth(storage_index, write_enabler,
                    test_and_write_vectors, read_vector, self)
    def remote_slot_readv(self, storage_index, shares, readv):
        return self.server.client_slot_readv(storage_index, shares, readv, self)
    def remote_advise_corrupt_share(self, share_type, storage_index, shnum,
                                    reason):
        return self.server.client_advise_corrupt_share(
            share_type, storage_index, shnum, reason, self)

class AnonymousAccount(BaseAccount):
    implements(RIStorageServer)

class Account(BaseAccount):
    def __init__(self, owner_num, pubkey_vs, server, leasedb):
        BaseAccount.__init__(self, owner_num, server, leasedb)
        self.pubkey_vs = pubkey_vs
        self.connected = False
        self.connected_since = None
        self.connection = None
        import random
        def maybe(): return bool(random.randint(0,1))
        self.status = {"write": maybe(),
                       "read": maybe(),
                       "save": maybe(),
                       }
        self.account_message = {
            "message": "free storage! %d" % random.randint(0,10),
            "fancy": "free pony if you knew how to ask",
            }

    def get_account_attribute(self, name):
        return self._leasedb.get_account_attribute(self.owner_num, name)
    def set_account_attribute(self, name, value):
        self._leasedb.set_account_attribute(self.owner_num, name, value)
    def get_account_creation_time(self):
        return self._leasedb.get_account_creation_time(self.owner_num)

    def remote_get_status(self):
        return self.status
    def remote_get_account_message(self):
        return self.account_message

    # these are the non-RIStorageServer methods, some remote, some local

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
        self.connection.callRemoteOnly("status", self.status)
    def _send_account_message(self):
        self.connection.callRemoteOnly("account_message", self.account_message)

    def set_status(self, write, read, save):
        self.status = { "write": write,
                        "read": read,
                        "save": save,
                        }
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


class AccountingCrawler(ShareCrawler):
    """I manage a SQLite table of which leases are owned by which ownerid, to
    support efficient calculation of total space used per ownerid. The
    sharefiles (and their leaseinfo fields) is the canonical source: the
    database is merely a speedup, generated/corrected periodically by this
    crawler. The crawler both handles the initial DB creation, and fixes the
    DB when changes have been made outside the storage-server's awareness
    (e.g. when the admin deletes a sharefile with /bin/rm).
    """

    slow_start = 7 # XXX #*60 # wait 7 minutes after startup
    minimum_cycle_time = 12*60*60 # not more than twice per day

    def __init__(self, server, statefile, leasedb):
        ShareCrawler.__init__(self, server, statefile)
        self._leasedb = leasedb
        self._expire_time = None

    def process_prefixdir(self, cycle, prefix, prefixdir, buckets, start_slice):
        # assume that we can list every bucketdir in this prefix quickly.
        # Otherwise we have to retain more state between timeslices.

        # we define "shareid" as (SI,shnum)
        disk_shares = set() # shareid
        for storage_index in buckets:
            bucketdir = os.path.join(prefixdir, storage_index)
            for sharefile in os.listdir(bucketdir):
                try:
                    shnum = int(sharefile)
                except ValueError:
                    continue # non-numeric means not a sharefile
                shareid = (storage_index, shnum)
                disk_shares.add(shareid)

        # now check the database for everything in this prefix
        db_shares = self._leasedb.get_shares_for_prefix(prefix)

        # add new shares to the DB
        new_shares = (disk_shares - db_shares)
        for shareid in new_shares:
            storage_index, shnum = shareid
            filename = os.path.join(prefixdir, storage_index, str(shnum))
            size = size_of_disk_file(filename)
            sid = self._leasedb.add_new_share(prefix, storage_index,shnum, size)
            self._leasedb.add_starter_lease(sid)

        # remove deleted shares
        deleted_shares = (db_shares - disk_shares)
        self._leasedb.remove_deleted_shares(deleted_shares)

        self._leasedb.commit()


    # these methods are for outside callers to use

    def set_lease_expiration(self, enable, expire_time=None):
        """Arrange to remove all leases that are currently expired, and to
        delete all shares without remaining leases. The actual removals will
        be done later, as the crawler finishes each prefix."""
        self._do_expire = enable
        self._expire_time = expire_time

    def db_is_incomplete(self):
        # don't bother looking at the sqlite database: it's certainly not
        # complete.
        return self.state["last-cycle-finished"] is None

class Accountant(service.MultiService):
    def __init__(self, storage_server, dbfile, statefile):
        service.MultiService.__init__(self)
        self.storage_server = storage_server
        self._leasedb = LeaseDB(dbfile)
        self._active_accounts = weakref.WeakValueDictionary()
        self._accountant_window = None
        self._anonymous_account = AnonymousAccount(0, self.storage_server,
                                                   self._leasedb)

        crawler = AccountingCrawler(storage_server, statefile, self._leasedb)
        self.accounting_crawler = crawler
        crawler.setServiceParent(self)

    def get_accountant_window(self, tub):
        if not self._accountant_window:
            self._accountant_window = AccountantWindow(self, tub)
        return self._accountant_window

    def get_leasedb(self):
        return self._leasedb

    def set_expiration_policy(self,
                              expiration_enabled=False,
                              expiration_mode="age",
                              expiration_override_lease_duration=None,
                              expiration_cutoff_date=None,
                              expiration_sharetypes=("mutable", "immutable")):
        pass # TODO

    # methods used by AccountantWindow

    def get_account(self, pubkey_vs):
        if pubkey_vs not in self._active_accounts:
            ownernum = self._leasedb.get_or_allocate_ownernum(pubkey_vs)
            a = Account(ownernum, pubkey_vs, self.storage_server, self._leasedb)
            self._active_accounts[pubkey_vs] = a
            # the client's RemoteReference will keep the Account alive. When
            # it disconnects, that reference will lapse, and it will be
            # removed from the _active_accounts WeakValueDictionary
        return self._active_accounts[pubkey_vs] # note: a is still alive

    def get_anonymous_account(self):
        return self._anonymous_account

    # methods used by admin interfaces
    def get_all_accounts(self):
        for ownerid, pubkey_vs in self._leasedb.get_all_accounts():
            if pubkey_vs in self._active_accounts:
                yield self._active_accounts[pubkey_vs]
            else:
                yield Account(ownerid, pubkey_vs,
                              self.storage_server, self._leasedb)


class AccountantWindow(Referenceable):
    def __init__(self, accountant, tub):
        self.accountant = accountant
        self.tub = tub

    def remote_get_account(self, msg, sig, pubkey_vs):
        print "GETTING ACCOUNT", msg
        vk = keyutil.parse_pubkey(pubkey_vs)
        vk.verify(sig, msg)
        account = self.accountant.get_account(pubkey_vs)
        msg_d = simplejson.loads(msg.decode("utf-8"))
        rxFURL = msg_d["please-give-Account-to-rxFURL"].encode("ascii")
        account.set_nickname(msg_d["nickname"])
        d = self.tub.getReference(rxFURL)
        def _got_rx(rx):
            account.connection_from(rx)
            d = rx.callRemote("account", account)
            d.addCallback(lambda ign: account._send_status())
            d.addCallback(lambda ign: account._send_account_message())
            return d
        d.addCallback(_got_rx)
        d.addErrback(log.err, umid="nFYfcA")
        return d


# XXX TODO new idea: move all leases into the DB. Do not store leases in
# shares at all. The crawler will exist solely to discover shares that
# have been manually added to disk (via 'scp' or some out-of-band means),
# and will add 30- or 60- day "migration leases" to them, to keep them
# alive until their original owner does a deep-add-lease and claims them
# properly. Better migration tools ('tahoe storage export'?) will create
# export files that include both the share data and the lease data, and
# then an import tool will both put the share in the right place and
# update the recipient node's lease DB.
#
# I guess the crawler will also be responsible for deleting expired
# shares, since it will be looking at both share files on disk and leases
# in the DB.
#
# So the DB needs a row per share-on-disk, and a separate table with
# leases on each bucket. When it sees a share-on-disk that isn't in the
# first table, it adds the migration-lease. When it sees a share-on-disk
# that is in the first table but has no leases in the second table (i.e.
# expired), it deletes both the share and the first-table row. When it
# sees a row in the first table but no share-on-disk (i.e. manually
# deleted share), it deletes the row (and any leases).
