#! /usr/bin/env python

import sys, textwrap

# this must be run from setup.py, which provides a $PYTHONPATH that includes
# our dependencies

def to_int(x):
    try:
        return int(x)
    except ValueError:
        return x

class Checker:
    def __init__(self, verbose, build):
        self.ok = True
        self.instructions = {}
        self.verbose = verbose
        self.build = build

    def at_least(self, name, v, required):
        # start with simple dotted-decimal
        v_bits = v.split(".")
        required_bits = required.split(".")
        if v_bits < required_bits:
            print "%s (%s) is too old: we want at least %s" % (name, v,
                                                               required)
            self.ok = False

    def fail(self, name, instructions):
        self.ok = False
        if instructions:
            self.instructions[name] = instructions

    def check(self, name, import_code, version_code=None, required=None,
              instructions=None):
        scope = {}
        try:
            exec import_code in scope
        except ImportError:
            print "%s: missing" % name
            return self.fail(name, instructions)
        if required is None:
            return
        version = eval(version_code, scope)

        # start with simple dotted-decimal
        v_bits = tuple([to_int(x) for x in str(version).split(".")])
        required_bits = tuple([to_int(x) for x in required.split(".")])
        if v_bits < required_bits:
            print "%s (%s) is too old: we want at least %s" % (name, version,
                                                               required)
            return self.fail(name, instructions)
        if self.verbose:
            print " %s: %s" % (name, str(version))
        return version

    def exit(self):
        if self.ok:
            print "All dependencies are present!"
            sys.exit(0)
        print "** some dependencies are missing **"
        for name in sorted(self.instructions.keys()):
            print "%s:" % name
            for line in textwrap.wrap(self.instructions[name]):
                print " "*5 + line
        for line in textwrap.wrap(INSTRUCTIONS):
            print " " + line
        sys.exit(1)

INSTRUCTIONS = """\
All dependencies should be available on PYTHONPATH. Tahoe will automatically
add three directories from its source tree to PYTHONPATH:
support/lib/pythonX.Y/site-packages, ./tahoe-deps, and ../tahoe-deps .
"""

verbose = False
if len(sys.argv) > 1 and sys.argv[1] in ("-v", "--verbose"):
    verbose = True
build = False
if len(sys.argv) > 1 and sys.argv[1] == "build":
    build = True
c = Checker(verbose, build)

# we want python-2.5 or newer to get sqlite
# we want python-2.6 or newer to get json
c.check("python", "import sys", "sys.version_info", "2.6",
        """Tahoe-LAFS requires python-2.5 or newer.
        Please run setup.py with a newer version.""")


# Nevow and Twisted have a number of DeprecationWarnings. Hush them.
import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning,
    message="object.__new__\(\) takes no parameters",
    append=True)
warnings.filterwarnings("ignore", category=DeprecationWarning,
    message="The popen2 module is deprecated.  Use the subprocess module.",
    append=True)
warnings.filterwarnings("ignore", category=DeprecationWarning,
    message="the md5 module is deprecated; use hashlib instead",
    append=True)
warnings.filterwarnings("ignore", category=DeprecationWarning,
    message="the sha module is deprecated; use the hashlib module instead",
    append=True)
warnings.filterwarnings("ignore", category=DeprecationWarning,
    message="twisted.web.error.NoResource is deprecated since Twisted 9.0.  See twisted.web.resource.NoResource.",
    append=True)

c.check("zfec", "import zfec", "zfec.__version__", "1.1.0")
c.check("twisted", "import twisted", "twisted.__version__", "2.4.0")
c.check("zope.interface", "import zope.interface")
c.check("foolscap", "import foolscap", "foolscap.__version__", "0.5.1",
        """Please install Foolscap (version 0.5.1 or later) with
        'easy_install foolscap', or by downloading the latest version from
        http://foolscap.lothar.com/ and following the instructions.""")
# foolscap < 0.5.1 had a performance bug which spent O(N**2) CPU for
# transferring large mutable files of size N.
from foolscap.pb import crypto_available
if not crypto_available:
    print "foolscap is lacking crypto (you probably need pyOpenSSL)"
    ok = False
c.check("nevow", "import nevow", "nevow.__version__", "0.6.0",
        """Please install Nevow (version 0.6.0 or later) with 'easy_install
        nevow', or by downloading the most recent release from ... and
        following its instructions.""")

if 0: # really_want_sftp
    v = c.check("pycrypto", "import Crypto", "Crypto.__version__", None)
    # pycrypto 2.2 doesn't work due to
    # https://bugs.launchpad.net/pycrypto/+bug/620253
    if v == "2.0.1" or v == "2.1":
        pass # these are ok
    else:
        at_least("pycrypto", v, "2.3")
    # pyasn1 is needed by twisted.conch in Twisted >= 9.0
    c.check("pyasn1", "import pyasn1", "pyasn1.__version__", "0.0.8a")

if 0: # "needed to test web apps, but not yet. See #1001"
    c.check("windmill", "import windmill", "windmill.__version__", "1.3")

# non-x86ish could tolerate 0.5.14 . We want 0.5.20 to get bugfixes in
# SHA-256 and AES on x86/amd64.
c.check("pycryptopp", "import pycryptopp", "pycryptopp.__version__", "0.5.20")

# sqlite: we require python >= 2.5, so it ought to be in stdlib unless this
# python was built badly
c.check("sqlite", "import sqlite3", "sqlite3.version", "2.3.2") # in py2.5.5
# json: we require python >= 2.6, so it ought to be in stdlib. We can
# tolerate the out-of-stdlib simplejson >= 1.4 (which is in feisty), but
# don't here for simplicity, for now.
c.check("json", "import json", "json.__version__", "1.9") # in py2.6.1

c.exit()
