
"""
This file manages the lease database, and runs the crawler which recovers
from lost-db conditions (both initial boot, DB failures, and shares being
added/removed out-of-band) by adding temporary 'starter leases'. It queries
the storage backend to enumerate existing shares (for each one it needs SI,
shnum, and used space). It can also instruct the storage backend to delete
a share that has expired.
"""

import os, time, re, simplejson

from twisted.python.filepath import FilePath

from allmydata.util.assertutil import _assert
from allmydata.util import dbutil
from allmydata.util.fileutil import get_used_space
from allmydata.storage.crawler import ShareCrawler
from allmydata.storage.common import si_a2b, si_b2a


class BadAccountName(Exception):
    pass

class NonExistentShareError(Exception):
    pass

class NonExistentLeaseError(Exception):
    pass

class LeaseInfo(object):
    def __init__(self, owner_num, renewal_time, expiration_time):
        self.owner_num = owner_num
        self.renewal_time = renewal_time
        self.expiration_time = expiration_time


def int_or_none(s):
    if s is None:
        return s
    return int(s)


STATE_COMING = 0
STATE_STABLE = 1
STATE_GOING = 2


LEASE_SCHEMA_V1 = """
CREATE TABLE version
(
 version INTEGER -- contains one row, set to 1
);

CREATE TABLE shares
(
 `storage_index` VARCHAR(26) not null,
 `shnum` INTEGER not null,
 `prefix` VARCHAR(2) not null,
 `used_space` INTEGER not null,
 `state` INTEGER not null, -- 0=coming, 1=stable, 2=going
 PRIMARY KEY (`storage_index`, `shnum`)
);

CREATE INDEX `prefix` ON `shares` (`prefix`);
-- CREATE UNIQUE INDEX `share_id` ON `shares` (`storage_index`,`shnum`);

CREATE TABLE leases
(
 `id` INTEGER PRIMARY KEY AUTOINCREMENT,
 `storage_index` VARCHAR(26) not null,
 `shnum` INTEGER not null,
 `account_id` INTEGER not null,
 `renewal_time` INTEGER not null, -- duration is implicit: expiration-renewal
 `expiration_time` INTEGER not null, -- seconds since epoch
 FOREIGN KEY (`storage_index`, `shnum`) REFERENCES `shares` (`storage_index`, `shnum`),
 FOREIGN KEY (`account_id`) REFERENCES `accounts` (`id`)
);

CREATE INDEX `account_id` ON `leases` (`account_id`);
CREATE INDEX `expiration_time` ON `leases` (`expiration_time`);

CREATE TABLE accounts
(
 `id` INTEGER PRIMARY KEY AUTOINCREMENT,
 -- do some performance testing. Z+DS propose using pubkey_vs as the primary
 -- key. That would increase the size of the DB and the index (repeated
 -- pubkeys instead of repeated small integers), right? Also, I think we
 -- actually want to retain the account.id as an abstraction barrier: you
 -- might have sub-accounts which are controlled by signed messages, for
 -- which there is no single pubkey associated with the account.
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

CREATE TABLE crawler_history
(
 `cycle` INTEGER,
 `json` TEXT
);
CREATE UNIQUE INDEX `cycle` ON `crawler_history` (`cycle`);
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
        self.debug = False

    # share management

    def get_shares_for_prefix(self, prefix):
        self._cursor.execute("SELECT `storage_index`,`shnum`"
                             " FROM `shares`"
                             " WHERE `prefix` == ?",
                             (prefix,))
        db_shares = set([(si,shnum) for (si,shnum) in self._cursor.fetchall()])
        return db_shares

    def add_new_share(self, storage_index, shnum, used_space):
        si_s = si_b2a(storage_index)
        prefix = si_s[:2]
        if self.debug: print "ADD_NEW_SHARE", prefix, si_s, shnum, used_space
        self._dirty = True
        try:
            self._cursor.execute("INSERT INTO `shares`"
                                 " VALUES (?,?,?,?,?)",
                                 (si_s, shnum, prefix, used_space, STATE_COMING))
        except dbutil.IntegrityError:
            # XXX: when test_repairer.Repairer.test_repair_from_deletion_of_1
            # runs, it deletes the share from disk, then the repairer replaces it
            # (in the same place). The add_new_share() code needs to tolerate
            # surprises like this: the share might have been manually deleted,
            # and the crawler may not have noticed it yet, so test for an existing
            # entry and use it if present (and check the code paths carefully to
            # make sure that doesn't get too weird).
            raise

    def add_starter_lease(self, storage_index, shnum):
        si_s = si_b2a(storage_index)
        if self.debug: print "ADD_STARTER_LEASE", si_s, shnum
        self._dirty = True
        renewal_time = time.time()
        self._cursor.execute("INSERT INTO `leases`"
                             " VALUES (?,?,?,?,?,?)",
                             (None, si_s, shnum, self.STARTER_LEASE_ACCOUNTID,
                              int(renewal_time), int(renewal_time + self.STARTER_LEASE_DURATION)))
    def remove_deleted_shares(self, shareids):
        #print "REMOVE_DELETED_SHARES", shareids
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



    def change_share_space(self, storage_index, shnum, used_space):
        si_s = si_b2a(storage_index)
        if self.debug: print "CHANGE_SHARE_SPACE", si_s, shnum, used_space
        self._dirty = True
        self._cursor.execute("UPDATE `shares` SET `used_space`=?"
                             " WHERE `storage_index`=? AND `shnum`=?",
                             (used_space, si_s, shnum))
        if self._cursor.rowcount < 1:
            raise NonExistentShareError()

    # lease management

    def add_or_renew_leases(self, storage_index, shnum, ownerid,
                            renewal_time, expiration_time):
        # shnum=None means renew leases on all shares
        si_s = si_b2a(storage_index)
        if self.debug: print "ADD_OR_RENEW_LEASES", si_s, shnum, ownerid, renewal_time, expiration_time
        self._dirty = True
        if shnum is None:
            self._cursor.execute("SELECT `storage_index`, `shnum` FROM `shares`"
                                 " WHERE `storage_index`=?",
                                 (si_s,))
        else:
            self._cursor.execute("SELECT `storage_index`, `shnum` FROM `shares`"
                                 " WHERE `storage_index`=? AND `shnum`=?",
                                 (si_s, shnum))
        rows = self._cursor.fetchall()
        if not rows:
            raise NonExistentShareError("can't find SI=%r shnum=%r in `shares` table"
                                        % (si_s, shnum))
        for (found_si_s, found_shnum) in rows:
            _assert(si_s == found_si_s, si_s=si_s, found_si_s=found_si_s)
            self._cursor.execute("SELECT `id` FROM `leases`"
                                 " WHERE `storage_index`=? AND `shnum`=? AND `account_id`=?",
                                 (si_s, found_shnum, ownerid))
            row = self._cursor.fetchone()
            if row:
                leaseid = row[0]
                self._cursor.execute("UPDATE `leases` SET `renewal_time`=?, `expiration_time`=?"
                                     " WHERE `id`=?",
                                     (renewal_time, expiration_time, leaseid))
            else:
                self._cursor.execute("INSERT INTO `leases` VALUES (?,?,?,?,?,?)",
                                     (None, si_s, shnum, ownerid, renewal_time, expiration_time))

    def get_leases(self, storage_index, ownerid):
        si_s = si_b2a(storage_index)
        self._cursor.execute("SELECT `id` FROM `leases`"
                             " WHERE `storage_index`=? AND `account_id`=?",
                             (si_s, ownerid))
        rows = self._cursor.fetchall()
        def _to_LeaseInfo(row):
            print "row:", row
            (_id, _storage_index, _shnum, account_id, renewal_time, expiration_time) = tuple(row)
            return LeaseInfo(account_id, renewal_time, expiration_time)
        return map(_to_LeaseInfo, rows)

    # history

    def add_history_entry(self, cycle, entry):
        if self.debug: print "ADD_HISTORY_ENTRY", cycle, entry
        json = simplejson.dumps(entry)
        self._cursor.execute("SELECT `cycle` FROM `crawler_history`")
        rows = self._cursor.fetchall()
        if len(rows) > 9:
            first_cycle_to_retain = list(sorted(rows))[-9]
            self._cursor.execute("DELETE FROM `crawler_history` WHERE cycle < ?",
                                 (first_cycle_to_retain,))

        self._cursor.execute("INSERT OR REPLACE INTO `crawler_history` VALUES (?,?)",
                             (cycle, json))
        self.commit(always=True)

    def get_history(self):
        self._cursor.execute("SELECT `cycle`,`json` FROM `crawler_history`")
        rows = self._cursor.fetchall()
        return dict(rows)

    # account management

    def get_account_usage(self, accountid):
        self._cursor.execute("SELECT SUM(`used_space`) FROM shares"
                             " WHERE `storage_index`, `shnum` IN"
                             "  (SELECT DISTINCT `storage_index`, `shnum` FROM `leases`"
                             "   WHERE `account_id`=?)",
                             (accountid,))
        row = self._cursor.fetchone()
        if not row or not row[0]: # XXX why did I need the second clause?
            return 0
        return row[0]

    def get_account_attribute(self, accountid, name):
        self._cursor.execute("SELECT `value` FROM `account_attributes`"
                             " WHERE `account_id`=? AND `name`=?",
                             (accountid, name))
        row = self._cursor.fetchone()
        if row:
            return row[0]
        return None

    def set_account_attribute(self, accountid, name, value):
        if self.debug: print "SET_ACCOUNT_ATTRIBUTE", accountid, name, value
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
        self._do_expire = False
        self._expire_time = None

    def process_prefixdir(self, cycle, prefix, prefixdir, buckets, start_slice):
        # assume that we can list every bucketdir in this prefix quickly.
        # Otherwise we have to retain more state between timeslices.

        # we define "shareid" as (SI string, shnum)
        disk_shares = set() # shareid
        for si_s in buckets:
            bucketdir = os.path.join(prefixdir, si_s)
            for sharefile in os.listdir(bucketdir):
                try:
                    shnum = int(sharefile)
                except ValueError:
                    continue # non-numeric means not a sharefile
                shareid = (si_s, shnum)
                disk_shares.add(shareid)

        # now check the database for everything in this prefix
        db_shares = self._leasedb.get_shares_for_prefix(prefix)

        # add new shares to the DB
        new_shares = (disk_shares - db_shares)
        for (si_s, shnum) in new_shares:
            fp = FilePath(prefixdir).child(si_s).child(str(shnum))
            used_space = get_used_space(fp)
            sid = self._leasedb.add_new_share(prefix, si_a2b(si_s), shnum, used_space)
            self._leasedb.add_starter_lease(sid)

        # remove deleted shares
        deleted_shares = (db_shares - disk_shares)
        for (si_s, shnum) in deleted_shares:
            self._leasedb.remove_deleted_share(si_a2b(si_s), shnum)

        self._leasedb.commit()


    # these methods are for outside callers to use

    def set_expiration_policy(self, policy):
        self._expiration_policy = policy

    def get_expiration_policy(self):
        return self._expiration_policy

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

    def is_expiration_enabled(self):
        return self._do_expire

    def convert_lease_age_histogram(self, lah):
        # convert { (minage,maxage) : count } into [ (minage,maxage,count) ]
        # since the former is not JSON-safe (JSON dictionaries must have
        # string keys).
        json_safe_lah = []
        for k in sorted(lah):
            (minage,maxage) = k
            json_safe_lah.append( (minage, maxage, lah[k]) )
        return json_safe_lah

    def add_initial_state(self):
        # we fill ["cycle-to-date"] here (even though they will be reset in
        # self.started_cycle) just in case someone grabs our state before we
        # get started: unit tests do this
        so_far = self.create_empty_cycle_dict()
        self.state.setdefault("cycle-to-date", so_far)
        # in case we upgrade the code while a cycle is in progress, update
        # the keys individually
        for k in so_far:
            self.state["cycle-to-date"].setdefault(k, so_far[k])

    def create_empty_cycle_dict(self):
        recovered = self.create_empty_recovered_dict()
        so_far = {"corrupt-shares": [],
                  "space-recovered": recovered,
                  "lease-age-histogram": {}, # (minage,maxage)->count
                  "leases-per-share-histogram": {}, # leasecount->numshares
                  }
        return so_far

    def create_empty_recovered_dict(self):
        recovered = {}
        for a in ("actual", "original", "configured", "examined"):
            for b in ("buckets", "shares", "sharebytes", "diskbytes"):
                recovered[a+"-"+b] = 0
                recovered[a+"-"+b+"-mutable"] = 0
                recovered[a+"-"+b+"-immutable"] = 0
        return recovered

    def started_cycle(self, cycle):
        self.state["cycle-to-date"] = self.create_empty_cycle_dict()

    def finished_cycle(self, cycle):
        # add to our history state, prune old history
        h = {}

        start = self.state["current-cycle-start-time"]
        now = time.time()
        h["cycle-start-finish-times"] = (start, now)
        h["expiration-enabled"] = self._do_expire
        h["configured-expiration-mode"] = (self._mode,
                                           self._override_lease_duration,
                                           self._cutoff_date,
                                           self._sharetypes_to_expire)

        s = self.state["cycle-to-date"]

        # state["lease-age-histogram"] is a dictionary (mapping
        # (minage,maxage) tuple to a sharecount), but we report
        # self.get_state()["lease-age-histogram"] as a list of
        # (min,max,sharecount) tuples, because JSON can handle that better.
        # We record the list-of-tuples form into the history for the same
        # reason.
        lah = self.convert_lease_age_histogram(s["lease-age-histogram"])
        h["lease-age-histogram"] = lah
        h["leases-per-share-histogram"] = s["leases-per-share-histogram"].copy()
        h["corrupt-shares"] = s["corrupt-shares"][:]
        # note: if ["shares-recovered"] ever acquires an internal dict, this
        # copy() needs to become a deepcopy
        h["space-recovered"] = s["space-recovered"].copy()

        self._leasedb.add_history_entry(cycle, h)

    def get_state(self):
        """In addition to the crawler state described in
        ShareCrawler.get_state(), I return the following keys which are
        specific to the lease-checker/expirer. Note that the non-history keys
        (with 'cycle' in their names) are only present if a cycle is currently
        running. If the crawler is between cycles, it is appropriate to show
        the latest item in the 'history' key instead. Also note that each
        history item has all the data in the 'cycle-to-date' value, plus
        cycle-start-finish-times.

         cycle-to-date:
          expiration-enabled
          configured-expiration-mode
          lease-age-histogram (list of (minage,maxage,sharecount) tuples)
          leases-per-share-histogram
          corrupt-shares (list of (si_b32,shnum) tuples, minimal verification)
          space-recovered

         estimated-remaining-cycle:
          # Values may be None if not enough data has been gathered to
          # produce an estimate.
          space-recovered

         estimated-current-cycle:
          # cycle-to-date plus estimated-remaining. Values may be None if
          # not enough data has been gathered to produce an estimate.
          space-recovered

         history: maps cyclenum to a dict with the following keys:
          cycle-start-finish-times
          expiration-enabled
          configured-expiration-mode
          lease-age-histogram
          leases-per-share-histogram
          corrupt-shares
          space-recovered

         The 'space-recovered' structure is a dictionary with the following
         keys:
          # 'examined' is what was looked at
          examined-buckets, examined-buckets-mutable, examined-buckets-immutable
          examined-shares, -mutable, -immutable
          examined-sharebytes, -mutable, -immutable
          examined-diskbytes, -mutable, -immutable

          # 'actual' is what was actually deleted
          actual-buckets, -mutable, -immutable
          actual-shares, -mutable, -immutable
          actual-sharebytes, -mutable, -immutable
          actual-diskbytes, -mutable, -immutable

          # would have been deleted, if the original lease timer was used
          original-buckets, -mutable, -immutable
          original-shares, -mutable, -immutable
          original-sharebytes, -mutable, -immutable
          original-diskbytes, -mutable, -immutable

          # would have been deleted, if our configured max_age was used
          configured-buckets, -mutable, -immutable
          configured-shares, -mutable, -immutable
          configured-sharebytes, -mutable, -immutable
          configured-diskbytes, -mutable, -immutable

        """
        progress = self.get_progress()

        state = ShareCrawler.get_state(self) # does a shallow copy
        state["history"] = self._leasedb.get_history()

        if not progress["cycle-in-progress"]:
            del state["cycle-to-date"]
            return state

        so_far = state["cycle-to-date"].copy()
        state["cycle-to-date"] = so_far

        lah = so_far["lease-age-histogram"]
        so_far["lease-age-histogram"] = self.convert_lease_age_histogram(lah)
        so_far["expiration-enabled"] = self.expiration_enabled
        so_far["configured-expiration-mode"] = (self.mode,
                                                self.override_lease_duration,
                                                self.cutoff_date,
                                                self.sharetypes_to_expire)

        so_far_sr = so_far["space-recovered"]
        remaining_sr = {}
        remaining = {"space-recovered": remaining_sr}
        cycle_sr = {}
        cycle = {"space-recovered": cycle_sr}

        if progress["cycle-complete-percentage"] > 0.0:
            pc = progress["cycle-complete-percentage"] / 100.0
            m = (1-pc)/pc
            for a in ("actual", "original", "configured", "examined"):
                for b in ("buckets", "shares", "sharebytes", "diskbytes"):
                    for c in ("", "-mutable", "-immutable"):
                        k = a+"-"+b+c
                        remaining_sr[k] = m * so_far_sr[k]
                        cycle_sr[k] = so_far_sr[k] + remaining_sr[k]
        else:
            for a in ("actual", "original", "configured", "examined"):
                for b in ("buckets", "shares", "sharebytes", "diskbytes"):
                    for c in ("", "-mutable", "-immutable"):
                        k = a+"-"+b+c
                        remaining_sr[k] = None
                        cycle_sr[k] = None

        state["estimated-remaining-cycle"] = remaining
        state["estimated-current-cycle"] = cycle
        return state
