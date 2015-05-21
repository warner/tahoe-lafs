#! /usr/bin/env python
# -*- coding: utf-8 -*-
import sys; assert sys.version_info < (3,), ur"Tahoe-LAFS does not run under Python 3. Please use a version of Python between 2.6 and 2.7.x inclusive."

# Tahoe-LAFS -- secure, distributed storage grid
#
# Copyright © 2006-2012 The Tahoe-LAFS Software Foundation
#
# This file is part of Tahoe-LAFS.
#
# See the docs/about.rst file for licensing information.


from setuptools import setup

trove_classifiers=[
    "Development Status :: 5 - Production/Stable",
    "Environment :: Console",
    "Environment :: Web Environment",
    "License :: OSI Approved :: GNU General Public License (GPL)",
    "License :: DFSG approved",
    "License :: Other/Proprietary License",
    "Intended Audience :: Developers",
    "Intended Audience :: End Users/Desktop",
    "Intended Audience :: System Administrators",
    "Operating System :: Microsoft",
    "Operating System :: Microsoft :: Windows",
    "Operating System :: Unix",
    "Operating System :: POSIX :: Linux",
    "Operating System :: POSIX",
    "Operating System :: MacOS :: MacOS X",
    "Operating System :: OS Independent",
    "Natural Language :: English",
    "Programming Language :: C",
    "Programming Language :: Python",
    "Programming Language :: Python :: 2",
    "Programming Language :: Python :: 2.6",
    "Programming Language :: Python :: 2.7",
    "Topic :: Utilities",
    "Topic :: System :: Systems Administration",
    "Topic :: System :: Filesystems",
    "Topic :: System :: Distributed Computing",
    "Topic :: Software Development :: Libraries",
    "Topic :: System :: Archiving :: Backup",
    "Topic :: System :: Archiving :: Mirroring",
    "Topic :: System :: Archiving",
    ]

install_requires = [
    "setuptools >= 0.6c6",
    "zfec >= 1.1.0",
    "simplejson >= 1.4",
    "Twisted >= 13.0.0",
    "Nevow >= 0.11.1",
    "foolscap >= 0.8.0",
    "pycrypto >= 2.6.1", # Needed for SFTP.
    "mock >= 0.8.0",
    "pycryptopp >= 0.6.0", # pycryptopp-0.6.0 includes ed25519
]

setup(name="allmydata-tahoe",
      description='secure, decentralized, fault-tolerant filesystem',
      long_description=open('README.rst', 'rU').read(),
      author='the Tahoe-LAFS project',
      author_email='tahoe-dev@tahoe-lafs.org',
      url='https://tahoe-lafs.org/',
      license='GNU GPL', # see README.rst -- there is an alternative licence
      package_dir = {'':'src'},
      packages=['allmydata',
                'allmydata.frontends',
                'allmydata.immutable',
                'allmydata.immutable.downloader',
                'allmydata.introducer',
                'allmydata.mutable',
                'allmydata.scripts',
                'allmydata.storage',
                'allmydata.test',
                'allmydata.util',
                'allmydata.web',
                'allmydata.windows',
                'buildtest'],
      classifiers=trove_classifiers,
      test_suite="allmydata.test",
      install_requires=install_requires,
      package_data={"allmydata.web": ["*.xhtml",
                                      "static/*.js", "static/*.png", "static/*.css",
                                      "static/img/*.png",
                                      "static/css/*.css",
                                      ]
                    },
      entry_points = { 'console_scripts':
                       [ 'tahoe = allmydata.scripts.runner:run' ] },
      )
