
``reserved_space = (str, optional)``

    If provided, this value defines how much disk space is reserved: the
    storage server will not accept any share that causes the amount of free
    disk space to drop below this value. (The free space is measured by a
    call to statvfs(2) on Unix, or GetDiskFreeSpaceEx on Windows, and is the
    space available to the user account under which the storage server runs.)

    This string contains a number, with an optional case-insensitive scale
    suffix like "K" or "M" or "G", and an optional "B" or "iB" suffix. So
    "100MB", "100M", "100000000B", "100000000", and "100000kb" all mean the
    same thing. Likewise, "1MiB", "1024KiB", and "1048576B" all mean the same
    thing.

    "``tahoe create-node``" generates a tahoe.cfg with
    "``reserved_space=1G``", but you may wish to raise, lower, or remove the
    reservation to suit your needs.

``expire.enabled =``

``expire.mode =``

``expire.override_lease_duration =``

``expire.cutoff_date =``

``expire.immutable =``

``expire.mutable =``

    These settings control garbage collection, in which the server will
    delete shares that no longer have an up-to-date lease on them. Please see
    `<garbage-collection.rst>`_ for full details.
