
import os
from twisted.trial import unittest
from allmydata.util import fileutil
from allmydata.storage.accountant import LeaseDB

BASE_ACCOUNTS = set([(0,u"anonymous"), (1,u"starter")])

class DB(unittest.TestCase):
    def make(self, testname):
        basedir = os.path.join("accountant", "DB", testname)
        fileutil.make_dirs(basedir)
        dbfilename = os.path.join(basedir, "leasedb.sqlite")
        return dbfilename
        
    def test_create(self):
        dbfilename = self.make("create")
        l = LeaseDB(dbfilename)
        self.failUnlessEqual(set(l.get_all_accounts()), BASE_ACCOUNTS)

        # should be able to open an existing one too
        l2 = LeaseDB(dbfilename)
        self.failUnlessEqual(set(l2.get_all_accounts()), BASE_ACCOUNTS)

    def test_accounts(self):
        dbfilename = self.make("accounts")
        l = LeaseDB(dbfilename)
        one = l.get_or_allocate_ownernum("one")
        self.failUnlessEqual(one, 2)
        one_a = l.get_or_allocate_ownernum("one")
        self.failUnlessEqual(one_a, 2)
        two = l.get_or_allocate_ownernum("two")
        self.failUnlessEqual(two, 3)
        anon = l.get_or_allocate_ownernum("anonymous")
        self.failUnlessEqual(anon, 0)
        anon = l.get_or_allocate_ownernum("starter")
        self.failUnlessEqual(anon, 1)
        self.failUnlessEqual(set(l.get_all_accounts()),
                             BASE_ACCOUNTS.union(set([(2, u"one"), (3, u"two")])))

        l.set_account_attribute(one, "name", u"value")
        # This column only stores unicode.
        self.failUnlessEqual(l.get_account_attribute(one, "name"), u"value")

        l.set_account_attribute(one, "name", u"updated")
        self.failUnlessEqual(l.get_account_attribute(one, "name"), u"updated")
        self.failUnlessEqual(l.get_account_attribute(one, "missing"), None)

        self.failUnlessEqual(l.get_account_attribute(two, "name"), None)
