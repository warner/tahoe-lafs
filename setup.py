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

class CheckDeps(Command):
    description = "Check for all necessary python dependencies"
    user_options = []
    boolean_options = []
    def initialize_options(self):
        pass
    def finalize_options(self):
        pass
    def run(self):
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
        print "build deps"
        os.execv(sys.executable,
                 [sys.executable, "misc/build_helpers/check-deps.py", "build"])

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
