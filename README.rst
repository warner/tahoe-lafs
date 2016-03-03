==========
Tahoe-LAFS
==========

Tahoe-LAFS is a Free and Open decentralized cloud storage system. It distributes
your data across multiple servers. Even if some of the servers fail or are taken
over by an attacker, the entire file store continues to function correctly,
preserving your privacy and security.

INSTALLING
==========

Pre-packaged versions are available for several operating systems:

* Debian and Ubuntu users can `apt-get install tahoe-lafs`
* NixOS, NetBSD (pkgsrc), ArchLinux, Slackware, and Gentoo have packages
  available, see `OSPackages`_ for details
* Mac and Windows installers are in development.

If you don't use an OS package, you'll need python2.7 and `pip`. You may also
need a C compiler, and the development headers for python, libffi, and
OpenSSL. On a Debian-like system, use `apt-get install build-essential
python-dev libffi-dev libssl-dev python-virtualenv`.

Then, to install the most recent release, just run:

* `pip install tahoe-lafs`

To install from source (either so you can hack on it, or just to run
pre-release code), you should create a virtualenv and install into that:

* `virtualenv tahoe-ve`
* `source tahoe-ve/bin/activate`
* `pip install --editable .`

To run the unit test suite:

* `tox`

For more details, see the docs directory.

Once `tahoe --version` works, see `docs/running.rst`_ to learn how to set up
your first Tahoe-LAFS node.

LICENCE
=======

Copyright 2006-2015 The Tahoe-LAFS Software Foundation

You may use this package under the GNU General Public License, version 2 or, at
your option, any later version.  You may use this package under the Transitive
Grace Period Public Licence, version 1.0, or at your option, any later
version. (You may choose to use this package under the terms of either licence,
at your option.)  See the file `COPYING.GPL`_ for the terms of the GNU General
Public License, version 2.  See the file `COPYING.TGPPL.rst`_ for the terms of
the Transitive Grace Period Public Licence, version 1.0.

See `TGPPL.PDF`_ for why the TGPPL exists, graphically illustrated on three slides.

.. _OSPackages: https://tahoe-lafs.org/trac/tahoe-lafs/wiki/OSPackages
.. _docs/running.rst: docs/running.rst
.. _quickstart.rst: https://github.com/tahoe-lafs/tahoe-lafs/blob/master/docs/quickstart.rst
.. _COPYING.GPL: https://github.com/tahoe-lafs/tahoe-lafs/blob/master/COPYING.GPL
.. _COPYING.TGPPL.rst: https://github.com/tahoe-lafs/tahoe-lafs/blob/master/COPYING.TGPPL.rst
.. _TGPPL.PDF: https://tahoe-lafs.org/~zooko/tgppl.pdf

----

.. image:: https://travis-ci.org/tahoe-lafs/tahoe-lafs.png?branch=master
  :target: https://travis-ci.org/tahoe-lafs/tahoe-lafs

.. image:: https://coveralls.io/repos/tahoe-lafs/tahoe-lafs/badge.png?branch=master
  :target: https://coveralls.io/r/tahoe-lafs/tahoe-lafs?branch=master
