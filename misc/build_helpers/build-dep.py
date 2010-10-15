#! /usr/bin/env python

import sys, os, shutil, tarfile

install = os.path.abspath("support")
name, tarball = sys.argv[1], sys.argv[2]
uses_setuptools = False
if len(sys.argv) > 3 and sys.argv[3] == "--setuptools":
    uses_setuptools = True
print "building", name, "from", tarball
print "into", install
tarball = os.path.abspath(tarball)

workdir = os.path.join("support", "build", name)
if os.path.isdir(workdir):
    shutil.rmtree(workdir)
os.makedirs(workdir)
os.chdir(workdir)

# unpack the tarball
tar = tarfile.open(tarball)
tar.extractall()
tar.close()
src = os.path.abspath([n for n in os.listdir(".") if os.path.isdir(n)][0])
print "building in", src
os.chdir(src)

cmd = [sys.executable, "setup.py", "install", "--prefix", install]
if uses_setuptools:
    cmd.extend(["--single-version-externally-managed", "--record", "files.txt"])
os.execv(cmd[0], cmd)
# never returns

# ugh, that fails too, wants to download setuptools-darcs

# setting PYTHONPATH to point at an .egg of setuptools-darcs and darcsver
# lets it succeed. Even if I'm using python2.5 and those eggs are named -2.6

# also, I can fill support/ with those tools ahead of time.

# ah, that works. Run it from setup.py . Just need tool to do both
# check-version and maybe-install . Need to re-scan PYTHONPATH each time,
# since the installed darcsver should be available to zfec.

"""

python misc/build_helpers/build-dep.py darcsver ../tahoe-deps/darcsver-1.2.1.tar
python misc/build_helpers/build-dep.py setuptools_darcs ../tahoe-deps/setuptools_darcs-1.2.8.tar
python misc/build_helpers/build-dep.py zfec ../tahoe-deps/tahoe-deps/zfec-1.4.7.tar.bz2

"""

# in unpacked zfec-1.4.7:
#  python setup.py install --prefix TOP/support --single-version-externally-managed --record stfu.txt

# with easy_install:
#  easy_install --svem --prefix TOP/support zfec-1.4.7.tar.bz2
#   easy_install has no --svem
#  PYTHONPATH=TOP/support/lib/pythonX.Y/site-packages easy_install --prefix TOP/support zfec-1.4.7.tar.bz2
#   zfec wants to download setuptools-darcs
#   maybe --find-links DIR
#  PYTHONPATH=TOP/support/lib/pythonX.Y/site-packages easy_install --prefix TOP/support --find-links TOP/../tahoe-deps/tahoe-deps zfec-1.4.7.tar.bz2
#   maybe add --build-directory=./something , keep it local

# can't seem to get that to work. I believe that --find-links=.tar.bz2 is
# finding and parsing the name correctly, but for some reason it's then being
# ignored later.

