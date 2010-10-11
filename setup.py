#! /usr/bin/env python

import os, sys, subprocess, re
from distutils.core import setup, Command
from distutils.command.sdist import sdist as _sdist

assert os.path.exists("Tahoe.home") # must run from source tree

# import the add_and_reexec() function from bin/tahoe
scope = {}
execfile("bin/tahoe", scope)
scope["add_and_reexec"]("setup.py")
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
                #"test": Test,
                "sdist": sdist,
                },
      )
