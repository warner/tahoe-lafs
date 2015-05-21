"""
Decentralized storage grid.

community web site: U{https://tahoe-lafs.org/}
"""

__version__ = "unknown"
try:
    from allmydata._version import __version__
except ImportError:
    # We're running in a tree that hasn't run update_version, and didn't
    # come with a _version.py, so we don't know what our version is.
    # This should not happen very often.
    pass

__appname__ = "allmydata-tahoe"

# __full_version__ is the one that you ought to use when identifying yourself in the
# "application" part of the Tahoe versioning scheme:
# https://tahoe-lafs.org/trac/tahoe-lafs/wiki/Versioning
__full_version__ = __appname__ + '/' + str(__version__)
