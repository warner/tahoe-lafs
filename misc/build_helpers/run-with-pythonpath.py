#!/usr/bin/env python

"""Run an arbitrary command with a PYTHONPATH that will include the Tahoe
code, including dependent libraries. Run this like:

 python misc/build_helpers/run-with-pythonpath.py python foo.py
  or
 python misc/build_helpers/run-with-pythonpath.py trial --reporter=bwverbose allmydata.test.test_cli

Note that $PATH will be searched for the command being executed ('python' and
'trial' in these examples), and will use the first one found. To execute
foo.py with a non-default python, use a distinct command name or an absolute
path:

 python2.6 misc/build_helpers/run-with-pythonpath.py python2.6 foo.py
 /usr/bin/python2.6 misc/build_helpers/run-with-pythonpath.py /usr/bin/python2.6 foo.py

"""

import os, sys, subprocess

assert os.path.exists("Tahoe.home") # must run from source tree root

# import the add_and_reexec() function from bin/tahoe
scope = {}
execfile("bin/tahoe", scope)
scope["add_and_reexec"]("misc/build_helpers/run-with-pythonpath.py")
# beyond here, if we're running from a source tree, then PYTHONPATH (and
# sys.path) will always have our source directory (TREE/src) at the front,
# and our tree-local dependency directories at the back
# (TREE/support/lib/pythonX.Y/site-packages, TREE/tahoe-deps,
# TREE/../tahoe-deps).

command = sys.argv[1:]
os.execvp(command[0], command)
