#! /usr/bin/env python

import os, sys, subprocess, re
from distutils.core import setup, Command
from distutils.command.sdist import sdist as _sdist
from distutils.errors import DistutilsOptionError

assert os.path.exists("Tahoe.home") # must run from source tree

# import the add_and_reexec() function from bin/tahoe
scope = {}
execfile("bin/tahoe", scope) ; add_and_reexec = scope["add_and_reexec"]
add_and_reexec("setup.py")
# beyond here, if we're running from a source tree, then PYTHONPATH (and
# sys.path) will always have our source directory (TREE/src) at the front,
# and our tree-local dependency directories at the back
# (TREE/support/lib/pythonX.Y/site-packages, TREE/tahoe-deps,
# TREE/../tahoe-deps).

VERSION_PY = """
# This file is originally generated from Git information by running
# 'setup.py update-version'. Distribution tarballs contain a pre-generated
# copy of this file.

__version__ = '%s'
"""

def get_version_from_git(prefix):
    if not os.path.isdir(".git"):
        print >>sys.stderr, "This does not appear to be a Git repository."
        return None
    try:
        p = subprocess.Popen(["git", "describe", "--tags", "--dirty", "--always"],
                             stdout=subprocess.PIPE)
    except EnvironmentError:
        print >>sys.stderr, "Unable to run git."
        return None
    stdout = p.communicate()[0]
    if p.returncode != 0:
        print >>sys.stderr, "Error while running git."
        return None
    assert stdout.startswith(prefix), stdout
    ver = stdout[len(prefix):].strip()
    return ver

def update_version_py(verfile="src/allmydata/_version.py",
                      prefix="allmydata-tahoe-"):
    ver = get_version_from_git(prefix)
    if not ver:
        print >>sys.stderr, "Unable to get version, leaving _version.py alone"
        return
    f = open(verfile, "w")
    f.write(VERSION_PY % ver)
    f.close()
    print "set %s to '%s'" % (verfile, ver)

def get_version_from_verfile(verfile="src/allmydata/_version.py"):
    try:
        f = open(verfile)
    except EnvironmentError:
        return None
    for line in f.readlines():
        mo = re.match("__version__ = '([^']+)'", line)
        if mo:
            ver = mo.group(1)
            return ver
    return None

class UpdateVersion(Command):
    description = "update _version.py from Git repo"
    user_options = []
    boolean_options = []
    def initialize_options(self):
        pass
    def finalize_options(self):
        pass
    def run(self):
        update_version_py()
        print "Version is now", get_version_from_verfile()

# this is what we depend upon, recursively. Each element is a tuple of:
#  (name, min_version, tarball_filename)

class D:
    def __init__(self, name, minver, tarball, uses_setuptools=True):
        self.name = name
        self.minver = minver
        self.tarball = tarball
        self.uses_setuptools = uses_setuptools

DEPS = [
    # we want python-2.5 or newer to get sqlite
    # we want python-2.6 or newer to get json
    D("python", "2.6", None),

    # zooko's packages need these
    D("darcsver", "1.2.0", "darcsver-1.6.3.tar.gz"),
    D("setuptools_darcs", "1.1.0", "setuptools_darcs-1.2.11.tar.bz2"),
    D("setuptools_trial", "0.5", "setuptools_trial-0.5.10.tar.gz"),
    D("zbase32", "1.0", "zbase32-1.1.2.tar.gz"),

    D("pyutil", "1.3.19", "pyutil-1.7.12.tar.bz2"), # setuptools-trial
    D("argparse", "0.8", "argparse-1.1.tar.bz2", uses_setuptools=False),
    D("zfec", "1.1.0", "zfec-1.4.7.tar.bz2"), # darcsver, setuptools_darcs, argparse, pyutil
    D("twisted", "2.4.0", "Twisted-10.1.0.tar.bz2"),
    D("zope.interface", "?", "zope.interface-3.6.1.tar.bz2"),
    # foolscap < 0.5.1 had a performance bug which spent O(N**2) CPU for
    # transferring large mutable files of size N.
    D("foolscap", "0.5.1", "foolscap-0.5.1.tar.bz2"),
    D("nevow", "0.6.0", "Nevow-0.10.0.tar.bz2"),

    # non-x86ish could tolerate 0.5.14 . We want 0.5.20 to get bugfixes in
    # SHA-256 and AES on x86/amd64.
    D("pycryptopp", "0.5.20", "pycryptopp-0.5.25.tar.bz2"),

    # sqlite: we require python >= 2.5, so it ought to be in stdlib unless
    # this python was built badly
    D("sqlite", "2.3.2", None), # in py2.5.5

    # json: we require python >= 2.6, so it ought to be in stdlib. We can
    # tolerate the out-of-stdlib simplejson >= 1.4 (which is in feisty), but
    # don't here for simplicity, for now.
    D("json", "1.9", None), # in py2.6.1

    # needed for SFTP
    D("pycrypto", "2.3", "pycrypto-2.3.tar.bz2", uses_setuptools=False), # version??
    D("pyasn1", "0.0.8a", "pyasn1-0.0.11a.tar.bz2"),

    # ticket #1001 webapp testing
    #D("windmill", "1.3", None),
    ]

# to check whether a given dependency is installed, we spawn a new
# misc/build_helpers/check-dep.py process (to let it re-scan PYTHONPATH and
# to avoid tainting our own namespace). It has special code that knows how to
# import each dependency and how to query for its version.

# If the user pressed the
# "automatically build everything for me" button, we then spawn a
# build-dep.py process to unpack a tarball and install its contents to our
# support/ directory.

def check_dep(name, minver):
    cmd = [sys.executable, "misc/build_helpers/check-dep.py",
           name, minver]
    p = subprocess.Popen(cmd)
    rc = p.wait()
    if rc == 0:
        return True
    return False

def find_tarball(tarball):
    for d in ["tahoe-deps", "../tahoe-deps"]:
        fn = os.path.join(d, tarball)
        print fn
        if os.path.isfile(fn):
            return fn
    return None

class CheckDeps(Command):
    description = "Check for all necessary python dependencies"
    user_options = []
    boolean_options = []
    def initialize_options(self):
        pass
    def finalize_options(self):
        pass
    def run(self):
        ok = []
        for d in DEPS:
            ok.append(check_dep(d.name, d.minver))
        if not all(ok):
            print >>sys.stderr, "** some dependencies are missing **"
            sys.exit(1)
        sys.exit(0)

        os.execv(sys.executable,
                 [sys.executable, "misc/build_helpers/check-deps.py"])

class BuildDeps(Command):
    description = "Build any missing dependencies in ./support/lib/"
    user_options = []
    boolean_options = []
    def initialize_options(self):
        pass
    def finalize_options(self):
        pass
    def run(self):
        built_something = False
        for d in DEPS:
            if not check_dep(d.name, d.minver):
                if not d.tarball:
                    print "I need %s, but I don't know how to build it" % d.name
                    sys.exit(1)
                tarball_fn = find_tarball(d.tarball)
                if not tarball_fn:
                    print "I want to build %s, but I can't find a tarball" % d.name
                    sys.exit(1)
                cmd = [sys.executable, "misc/build_helpers/build-dep.py",
                       d.name, tarball_fn]
                if d.uses_setuptools:
                    cmd.append("--setuptools")
                print cmd
                print "Building %s.." % tarball_fn
                p = subprocess.Popen(cmd)
                rc = p.wait()
                if rc != 0:
                    print >>sys.stderr, "unable to build %s" % d.name
                    print >>sys.stderr, "exiting"
                    sys.exit(1)
                print " built %s" % d.name
                built_something = True
        if built_something:
            print "all necessary dependencies built"
        else:
            print "nothing needed to be built. 'setup.py check_deps' should be happy now."

# stripped down version of setuptools_trial
class TrialTest(Command):
    test_args = ["allmydata.test"]
    user_options = [
        ('rterrors', 'e', "Realtime errors: print out tracebacks as soon as they occur."),
        ('debug-stacktraces', 'B', "Report Deferred creation and callback stack traces."),
        ('coverage','c', "Report coverage data."),
        ('reactor=','r', "which reactor to use"),
        ('reporter=', None, "Customize Trial's output with a Reporter plugin."),
        ('until-failure','u', "Repeat test until it fails."),
        ('tests=', 't', "comma-separated list of test cases to run"),
    ]

    boolean_options = ['coverage', 'debug-stacktraces', 'rterrors',
                       'until-failure']

    def initialize_options(self):
        self.coverage = None
        self.debug_stacktraces = None
        self.reactor = None
        self.reporter = None
        self.rterrors = None
        self.until_failure = None
        self.tests = None

    def finalize_options(self):
        if self.tests is not None:
            self.test_args = self.tests.split(",")

    def run(self):
        # We do the import from Twisted inside the function instead of the
        # top of the file (after add_and_reexec()) because setup.py may be
        # used to install Twisted.
        from twisted.scripts import trial

        # Handle parsing the trial options passed through the setup.py
        # trial command.
        cmd_options = ["trial"]
        if self.reactor is not None:
            cmd_options.extend(['--reactor', self.reactor])
        else:
            # Cygwin requires the poll reactor to work at all. Linux requires
            # the poll reactor to avoid twisted bug #3218. In general, the
            # poll reactor is better than the select reactor, but it is not
            # available on all platforms. According to exarkun on IRC, it is
            # available but buggy on some versions of Mac OS X, so just
            # because you can install it doesn't mean we want to use it on
            # every platform. Unfortunately this leads to this error with
            # some combinations of tools: twisted.python.usage.UsageError:
            # The specified reactor cannot be used, failed with error:
            # reactor already installed.
            if sys.platform in ("cygwin"):
                cmd_options.extend(['--reactor', 'poll'])
        if self.reporter is not None:
            cmd_options.extend(['--reporter', self.reporter])
        if self.rterrors is not None:
            cmd_options.append('--rterrors')
        if self.debug_stacktraces is not None:
            cmd_options.append('--debug-stacktraces')
        if self.until_failure is not None:
            cmd_options.append('--until-failure')

        args = self.test_args
        if type(args) == str:
            args = [args,]

        cmd_options.extend(args)

        sys.argv = cmd_options

        # TODO: coverage? maybe handled by reporter?
        trial.run() # does sys.exit unless args are bad
        sys.exit(1)
        return

class sdist(_sdist):
    def run(self):
        update_version_py()
        # unless we update this, the sdist command will keep using the old
        # version
        self.distribution.metadata.version = get_version_from_verfile()
        return _sdist.run(self)

setup(name="tahoe-lafs",
      version=get_version_from_verfile(),
      description="secure, decentralized, fault-tolerant filesystem",
      author="the Tahoe-LAFS project",
      author_email="tahoe-dev@tahoe-lafs.org",
      url="http://tahoe-lafs.org/",
      packages=["allmydata"],
      license="GNU GPL", # see README.txt -- there is an alternative licence
      cmdclass={"update_version": UpdateVersion,
                "check_deps": CheckDeps,
                "build_deps": BuildDeps,
                "test": TrialTest,
                "sdist": sdist,
                },
      )
