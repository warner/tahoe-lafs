#! /usr/bin/env python

import os, sys, textwrap

# this must be run from setup.py, which provides a $PYTHONPATH that includes
# our dependencies

name, minver = sys.argv[1:]

def to_int(x):
    try:
        return int(x)
    except ValueError:
        return x

def at_least(name, v, required):
    # start with simple dotted-decimal
    v_bits = v.split(".")
    required_bits = required.split(".")
    if v_bits < required_bits:
        print " %s (%s) is too old: we want at least %s" % (name, v, required)
        sys.exit(1)

def check(name, import_code, version_code=None, required=None):
    scope = {}
    try:
        exec import_code in scope
    except ImportError, e:
        print " %s: MISSING" % name
        print "  ", e
        sys.exit(1)
    if version_code is None:
        print " %s: present" % name
        return
    try:
        version = eval(version_code, scope)
    except:
        print " %s: ERROR" % name
        raise

    if required is None:
        print " %s: %s" % (name, version)
        return version

    # start with simple dotted-decimal
    v_bits = tuple([to_int(x) for x in str(version).split(".")])
    required_bits = tuple([to_int(x) for x in required.split(".")])
    if v_bits < required_bits:
        print " %s (%s) is too old: we want at least %s" % (name, version,
                                                            required)
        sys.exit(1)
    print " %s: %s (>= %s)" % (name, str(version), required)
    return version

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

if name == "python":
    check("python", "import sys", "sys.version_info", minver)
elif name == "pyutil":
    check("pyutil", "import pyutil", "pyutil.__version__", minver)
elif name == "argparse":
    check("argparse", "import argparse", "argparse.__version__", minver)
elif name == "setuptools_trial":
    check("setuptools_trial", "import setuptools_trial._version",
          "setuptools_trial._version.__version__", minver)
elif name == "zbase32":
    check("zbase32", "import zbase32._version",
          "zbase32._version.__version__", minver)
elif name == "zfec":
    check("zfec", "import zfec", "zfec.__version__", minver)
elif name == "twisted":
    check("twisted", "import twisted", "twisted.__version__", minver)
elif name == "zope.interface":
    check("zope.interface", "import zope.interface")
elif name == "foolscap":
    check("foolscap", "import foolscap", "foolscap.__version__", minver)
    from foolscap.pb import crypto_available
    if not crypto_available:
        print " foolscap is lacking crypto (you probably need pyOpenSSL)"
        sys.exit(1)
elif name == "nevow":
    check("nevow", "import nevow", "nevow.__version__", minver)

# if really_want_sftp
elif name == "pycrypto":
    v = check("pycrypto", "import Crypto", "Crypto.__version__", None)
    # pycrypto 2.2 doesn't work due to
    # https://bugs.launchpad.net/pycrypto/+bug/620253
    if v == "2.0.1" or v == "2.1":
        pass # these are ok
    else:
        at_least("pycrypto", v, "2.3")
elif name == "pyasn1":
    # pyasn1 is needed by twisted.conch in Twisted >= 9.0 . We want 0.0.8a,
    # but pyasn1.majorVersionId is all the introspection it offers.
    check("pyasn1", "import pyasn1", None, None)
elif name == "windmill":
    check("windmill", "import windmill", "windmill.__version__", minver)
elif name == "pycryptopp":
    check("pycryptopp", "import pycryptopp", "pycryptopp.__version__", minver)
elif name == "sqlite":
    check("sqlite", "import sqlite3", "sqlite3.version", minver)
elif name == "json":
    check("json", "import json", "json.__version__", minver)

elif name == "darcsver":
    check("darcsver", "import darcsver", "darcsver.__version__", minver)

elif name == "setuptools_darcs":
    check("setuptools_darcs", "import setuptools_darcs",
          "setuptools_darcs.__version__", minver)

else:
    print " I don't know how to check the version of '%s'" % name
    sys.exit(1)

sys.exit(0)
