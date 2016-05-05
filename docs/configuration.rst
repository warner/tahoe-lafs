﻿.. -*- coding: utf-8-with-signature -*-

=============================
Configuring a Tahoe-LAFS node
=============================

1.  `Node Types`_
2.  `Overall Node Configuration`_
3.  `Client Configuration`_
4.  `Storage Server Configuration`_
5.  `Frontend Configuration`_
6.  `Running A Helper`_
7.  `Running An Introducer`_
8.  `Other Files in BASEDIR`_
9.  `Other files`_
10. `Example`_

A Tahoe-LAFS node is configured by writing to files in its base directory.
These files are read by the node when it starts, so each time you change
them, you need to restart the node.

The node also writes state to its base directory, so it will create files on
its own.

This document contains a complete list of the config files that are examined
by the client node, as well as the state files that you'll observe in its
base directory.

The main file is named "``tahoe.cfg``", and is an ".INI"-style configuration
file (parsed by the Python stdlib 'ConfigParser' module: "``[name]``" section
markers, lines with "``key.subkey: value``", rfc822-style
continuations). There are also other files containing information that does
not easily fit into this format. The "``tahoe create-node``" or "``tahoe
create-client``" command will create an initial ``tahoe.cfg`` file for
you. After creation, the node will never modify the ``tahoe.cfg`` file: all
persistent state is put in other files.

The item descriptions below use the following types:

``boolean``

    one of (True, yes, on, 1, False, off, no, 0), case-insensitive

``strports string``

    a Twisted listening-port specification string, like "``tcp:80``" or
    "``tcp:3456:interface=127.0.0.1``". For a full description of the format,
    see `the Twisted strports documentation`_.  Please note, if interface= is
    not specified, Tahoe-LAFS will attempt to bind the port specified on all
    interfaces.

``endpoint specification string``

    a Twisted Endpoint specification string, like "``tcp:80``" or
    "``tcp:3456:interface=127.0.0.1``". These are replacing strports strings.
    For a full description of the format, see `the Twisted Endpoints
    documentation`_. Please note, if interface= is not specified, Tahoe-LAFS
    will attempt to bind the port specified on all interfaces. Also note that
    ``tub.port`` only works with TCP endpoints right now.

``FURL string``

    a Foolscap endpoint identifier, like
    ``pb://soklj4y7eok5c3xkmjeqpw@192.168.69.247:44801/eqpwqtzm``

.. _the Twisted strports documentation: https://twistedmatrix.com/documents/current/api/twisted.application.strports.html
.. _the Twisted Endpoints documentation: http://twistedmatrix.com/documents/current/core/howto/endpoints.html#endpoint-types-included-with-twisted

Node Types
==========

A node can be a client, or a server, or both, or an introducer, or a
statistics gatherer.

Client/server nodes provide one or more of the following services:

* web-API service
* SFTP service
* FTP service
* drop-upload service
* helper service
* storage service

A client/server that provides storage service (i.e. storing shares for
clients) is called a "storage server". If it provides any of the other
services, it is a "storage client" (a node can be both a storage server and a
storage client). A client/server node that provides web-API service is called
a "gateway".


Overall Node Configuration
==========================

This section controls the network behavior of the node overall: which ports
and IP addresses are used, when connections are timed out, etc. This
configuration applies to all node types and is independent of the services
that the node is offering.

If your node is behind a firewall or NAT device and you want other clients to
connect to it, you'll need to open a port in the firewall or NAT, and specify
that port number in the tub.port option. If behind a NAT, you *may* need to
set the ``tub.location`` option described below.

``[node]``

``nickname = (UTF-8 string, optional)``

    This value will be displayed in management tools as this node's
    "nickname". If not provided, the nickname will be set to "<unspecified>".
    This string shall be a UTF-8 encoded Unicode string.

``web.port = (strports string, optional)``

    This controls where the node's web server should listen, providing node
    status and, if the node is a client/server, providing web-API service as
    defined in :doc:`frontends/webapi`.

    This file contains a Twisted "strports" specification such as "``3456``"
    or "``tcp:3456:interface=127.0.0.1``". The "``tahoe create-node``" or
    "``tahoe create-client``" commands set the ``web.port`` to
    "``tcp:3456:interface=127.0.0.1``" by default; this is overridable by the
    ``--webport`` option. You can make it use SSL by writing
    "``ssl:3456:privateKey=mykey.pem:certKey=cert.pem``" instead.

    If this is not provided, the node will not run a web server.

``web.static = (string, optional)``

    This controls where the ``/static`` portion of the URL space is
    served. The value is a directory name (``~username`` is allowed, and
    non-absolute names are interpreted relative to the node's basedir), which
    can contain HTML and other files. This can be used to serve a
    Javascript-based frontend to the Tahoe-LAFS node, or other services.

    The default value is "``public_html``", which will serve
    ``BASEDIR/public_html`` .  With the default settings,
    ``http://127.0.0.1:3456/static/foo.html`` will serve the contents of
    ``BASEDIR/public_html/foo.html`` .

``tub.port = (endpoint specification string, optional)``

    This controls which port the node uses to accept Foolscap connections
    from other nodes. It is parsed as a Twisted "server endpoint descriptor",
    which accepts values like ``tcp:12345`` and
    ``tcp:23456:interface=127.0.0.1``.

    For backwards compatibility, if this contains a simple integer, it will
    be used as a TCP port number, like ``tcp:%d`` (which will accept
    connections on all interfaces). However ``tub.port`` cannot be ``0`` or
    ``tcp:0`` (older versions accepted this, but the node is no longer
    willing to ask Twisted to allocate port numbers in this way). To
    automatically allocate a TCP port, leave ``tub.port`` blank.

    If the ``tub.port`` config key is not provided, the node will look in
    ``BASEDIR/client.port`` (or ``BASEDIR/introducer.port``, for introducers)
    for the descriptor that was used last time.

    If neither is available, the node will ask the kernel for any available
    port (the moral equivalent of ``tcp:0``). The allocated port number will
    be written into a descriptor string in ``BASEDIR/client.port`` (or
    ``introducer.port``), so that subsequent runs will re-use the same port.

``tub.location = (string, optional)``

    In addition to running as a client, each Tahoe-LAFS node can also run as
    a server, listening for connections from other Tahoe-LAFS clients. The
    node announces its location by publishing a "FURL" (a string with some
    connection hints) to the Introducer. The string it publishes can be found
    in ``BASEDIR/private/storage.furl`` . The ``tub.location`` configuration
    controls what location is published in this announcement.

    If your node is meant to run as a server, you should fill this in, using
    a hostname or IP address that is reachable from your intended clients.

    If you don't provide ``tub.location``, the node will try to figure out a
    useful one by itself, by using tools like "``ifconfig``" to determine the
    set of IP addresses on which it can be reached from nodes both near and
    far. It will also include the TCP port number on which it is listening
    (either the one specified by ``tub.port``, or whichever port was assigned
    by the kernel when ``tub.port`` is left unspecified). However this
    automatic address-detection is discouraged, and will probably be removed
    from a future release. It will include the ``127.0.0.1`` "localhost"
    address (which is only useful to clients running on the same computer),
    and RFC1918 private-network addresses like ``10.*.*.*`` and
    ``192.168.*.*`` (which are only useful to clients on the local LAN). In
    general, the automatically-detected IP addresses will only be useful if
    the node has a public IP address, such as a VPS or colo-hosted server.

    You will certainly need to set ``tub.location`` if your node lives behind
    a firewall that is doing inbound port forwarding, or if you are using
    other proxies such that the local IP address or port number is not the
    same one that remote clients should use to connect. You might also want
    to control this when using a Tor proxy to avoid revealing your actual IP
    address through the Introducer announcement.

    If ``tub.location`` is specified, by default it entirely replaces the
    automatically determined set of IP addresses. To include the automatically
    determined addresses as well as the specified ones, include the uppercase
    string "``AUTO``" in the list.

    The value is a comma-separated string of method:host:port location hints,
    like this::

      tcp:123.45.67.89:8098,tcp:tahoe.example.com:8098,tcp:127.0.0.1:8098

    A few examples:

    * Use a DNS name so you can change the IP address more easily::

        tub.port = tcp:8098
        tub.location = tcp:tahoe.example.com:8098

    * Run a node behind a firewall (which has an external IP address) that
      has been configured to forward external port 7912 to our internal
      node's port 8098::

        tub.port = tcp:8098
        tub.location = tcp:external-firewall.example.com:7912

    * Emulate default behavior, assuming your host has public IP address of
      123.45.67.89, and the kernel-allocated port number was 8098::

        tub.port = tcp:8098
        tub.location = tcp:123.45.67.89:8098,tcp:127.0.0.1:8098

    * Use a DNS name but also include the default set of addresses::

        tub.port = tcp:8098
        tub.location = tcp:tahoe.example.com:8098,AUTO

    * Run a node behind a Tor proxy (perhaps via ``torsocks``), in
      client-only mode (i.e. we can make outbound connections, but other
      nodes will not be able to connect to us). The literal
      '``unreachable.example.org``' will not resolve, but will serve as a
      reminder to human observers that this node cannot be reached. "Don't
      call us.. we'll call you"::

        tub.port = tcp:8098
        tub.location = tcp:unreachable.example.org:0

    * Run a node behind a Tor proxy, and make the server available as a Tor
      "hidden service". (This assumes that other clients are running their
      node with ``torsocks``, such that they are prepared to connect to a
      ``.onion`` address.) The hidden service must first be configured in
      Tor, by giving it a local port number and then obtaining a ``.onion``
      name, using something in the ``torrc`` file like::

        HiddenServiceDir /var/lib/tor/hidden_services/tahoe
        HiddenServicePort 29212 127.0.0.1:8098

      once Tor is restarted, the ``.onion`` hostname will be in
      ``/var/lib/tor/hidden_services/tahoe/hostname``. Then set up your
      ``tahoe.cfg`` like::

        tub.port = tcp:8098
        tub.location = tor:ualhejtq2p7ohfbb.onion:29212

``log_gatherer.furl = (FURL, optional)``

    If provided, this contains a single FURL string that is used to contact a
    "log gatherer", which will be granted access to the logport. This can be
    used to gather operational logs in a single place. Note that in previous
    releases of Tahoe-LAFS, if an old-style ``BASEDIR/log_gatherer.furl``
    file existed it would also be used in addition to this value, allowing
    multiple log gatherers to be used at once. As of Tahoe-LAFS v1.9.0, an
    old-style file is ignored and a warning will be emitted if one is
    detected. This means that as of Tahoe-LAFS v1.9.0 you can have at most
    one log gatherer per node. See ticket `#1423`_ about lifting this
    restriction and letting you have multiple log gatherers.

    .. _`#1423`: https://tahoe-lafs.org/trac/tahoe-lafs/ticket/1423

``timeout.keepalive = (integer in seconds, optional)``

``timeout.disconnect = (integer in seconds, optional)``

    If ``timeout.keepalive`` is provided, it is treated as an integral number
    of seconds, and sets the Foolscap "keepalive timer" to that value. For
    each connection to another node, if nothing has been heard for a while,
    we will attempt to provoke the other end into saying something. The
    duration of silence that passes before sending the PING will be between
    KT and 2*KT. This is mainly intended to keep NAT boxes from expiring idle
    TCP sessions, but also gives TCP's long-duration keepalive/disconnect
    timers some traffic to work with. The default value is 240 (i.e. 4
    minutes).

    If timeout.disconnect is provided, this is treated as an integral number
    of seconds, and sets the Foolscap "disconnect timer" to that value. For
    each connection to another node, if nothing has been heard for a while,
    we will drop the connection. The duration of silence that passes before
    dropping the connection will be between DT-2*KT and 2*DT+2*KT (please see
    ticket `#521`_ for more details). If we are sending a large amount of
    data to the other end (which takes more than DT-2*KT to deliver), we
    might incorrectly drop the connection. The default behavior (when this
    value is not provided) is to disable the disconnect timer.

    See ticket `#521`_ for a discussion of how to pick these timeout values.
    Using 30 minutes means we'll disconnect after 22 to 68 minutes of
    inactivity. Receiving data will reset this timeout, however if we have
    more than 22min of data in the outbound queue (such as 800kB in two
    pipelined segments of 10 shares each) and the far end has no need to
    contact us, our ping might be delayed, so we may disconnect them by
    accident.

    .. _`#521`: https://tahoe-lafs.org/trac/tahoe-lafs/ticket/521

``tempdir = (string, optional)``

    This specifies a temporary directory for the web-API server to use, for
    holding large files while they are being uploaded. If a web-API client
    attempts to upload a 10GB file, this tempdir will need to have at least
    10GB available for the upload to complete.

    The default value is the ``tmp`` directory in the node's base directory
    (i.e. ``BASEDIR/tmp``), but it can be placed elsewhere. This directory is
    used for files that usually (on a Unix system) go into ``/tmp``. The
    string will be interpreted relative to the node's base directory.


Client Configuration
====================

``[client]``

``introducer.furl = (FURL string, mandatory)``

    This FURL tells the client how to connect to the introducer. Each
    Tahoe-LAFS grid is defined by an introducer. The introducer's FURL is
    created by the introducer node and written into its private base
    directory when it starts, whereupon it should be published to everyone
    who wishes to attach a client to that grid

``helper.furl = (FURL string, optional)``

    If provided, the node will attempt to connect to and use the given helper
    for uploads. See :doc:`helper` for details.

``stats_gatherer.furl = (FURL string, optional)``

    If provided, the node will connect to the given stats gatherer and
    provide it with operational statistics.

``shares.needed = (int, optional) aka "k", default 3``

``shares.total = (int, optional) aka "N", N >= k, default 10``

``shares.happy = (int, optional) 1 <= happy <= N, default 7``

    These three values set the default encoding parameters. Each time a new
    file is uploaded, erasure-coding is used to break the ciphertext into
    separate shares. There will be ``N`` (i.e. ``shares.total``) shares
    created, and the file will be recoverable if any ``k``
    (i.e. ``shares.needed``) shares are retrieved. The default values are
    3-of-10 (i.e.  ``shares.needed = 3``, ``shares.total = 10``). Setting
    ``k`` to 1 is equivalent to simple replication (uploading ``N`` copies of
    the file).

    These values control the tradeoff between storage overhead and
    reliability. To a first approximation, a 1MB file will use (1MB *
    ``N``/``k``) of backend storage space (the actual value will be a bit
    more, because of other forms of overhead). Up to ``N``-``k`` shares can
    be lost before the file becomes unrecoverable.  So large ``N``/``k``
    ratios are more reliable, and small ``N``/``k`` ratios use less disk
    space. ``N`` cannot be larger than 256, because of the 8-bit
    erasure-coding algorithm that Tahoe-LAFS uses. ``k`` can not be greater
    than ``N``. See :doc:`performance` for more details.

    ``shares.happy`` allows you control over how well to "spread out" the
    shares of an immutable file. For a successful upload, shares are
    guaranteed to be initially placed on at least ``shares.happy`` distinct
    servers, the correct functioning of any ``k`` of which is sufficient to
    guarantee the availability of the uploaded file. This value should not be
    larger than the number of servers on your grid.

    A value of ``shares.happy`` <= ``k`` is allowed, but this is not
    guaranteed to provide any redundancy if some servers fail or lose shares.
    It may still provide redundancy in practice if ``N`` is greater than
    the number of connected servers, because in that case there will typically
    be more than one share on at least some storage nodes. However, since a
    successful upload only guarantees that at least ``shares.happy`` shares
    have been stored, the worst case is still that there is no redundancy.

    (Mutable files use a different share placement algorithm that does not
    currently consider this parameter.)

``mutable.format = sdmf or mdmf``

    This value tells Tahoe-LAFS what the default mutable file format should
    be. If ``mutable.format=sdmf``, then newly created mutable files will be
    in the old SDMF format. This is desirable for clients that operate on
    grids where some peers run older versions of Tahoe-LAFS, as these older
    versions cannot read the new MDMF mutable file format. If
    ``mutable.format`` is ``mdmf``, then newly created mutable files will use
    the new MDMF format, which supports efficient in-place modification and
    streaming downloads. You can overwrite this value using a special
    mutable-type parameter in the webapi. If you do not specify a value here,
    Tahoe-LAFS will use SDMF for all newly-created mutable files.

    Note that this parameter applies only to files, not to directories.
    Mutable directories, which are stored in mutable files, are not
    controlled by this parameter and will always use SDMF. We may revisit
    this decision in future versions of Tahoe-LAFS.

    See :doc:`specifications/mutable` for details about mutable file formats.

``peers.preferred = (string, optional)``

    This is an optional comma-separated list of Node IDs of servers that will
    be tried first when selecting storage servers for reading or writing.

    Servers should be identified here by their Node ID as it appears in the web
    ui, underneath the server's nickname. For storage servers running tahoe
    versions >=1.10 (if the introducer is also running tahoe >=1.10) this will
    be a "Node Key" (which is prefixed with 'v0-'). For older nodes, it will be
    a TubID instead. When a preferred server (and/or the introducer) is
    upgraded to 1.10 or later, clients must adjust their configs accordingly.

    Every node selected for upload, whether preferred or not, will still
    receive the same number of shares (one, if there are ``N`` or more servers
    accepting uploads). Preferred nodes are simply moved to the front of the
    server selection lists computed for each file.

    This is useful if a subset of your nodes have different availability or
    connectivity characteristics than the rest of the grid. For instance, if
    there are more than ``N`` servers on the grid, and ``K`` or more of them
    are at a single physical location, it would make sense for clients at that
    location to prefer their local servers so that they can maintain access to
    all of their uploads without using the internet.


Frontend Configuration
======================

The Tahoe client process can run a variety of frontend file-access protocols.
You will use these to create and retrieve files from the virtual filesystem.
Configuration details for each are documented in the following
protocol-specific guides:

HTTP

    Tahoe runs a webserver by default on port 3456. This interface provides a
    human-oriented "WUI", with pages to create, modify, and browse
    directories and files, as well as a number of pages to check on the
    status of your Tahoe node. It also provides a machine-oriented "WAPI",
    with a REST-ful HTTP interface that can be used by other programs
    (including the CLI tools). Please see :doc:`frontends/webapi` for full
    details, and the ``web.port`` and ``web.static`` config variables above.
    :doc:`frontends/download-status` also describes a few WUI status pages.

CLI

    The main ``tahoe`` executable includes subcommands for manipulating the
    filesystem, uploading/downloading files, and creating/running Tahoe
    nodes. See :doc:`frontends/CLI` for details.

SFTP, FTP

    Tahoe can also run both SFTP and FTP servers, and map a username/password
    pair to a top-level Tahoe directory. See :doc:`frontends/FTP-and-SFTP`
    for instructions on configuring these services, and the ``[sftpd]`` and
    ``[ftpd]`` sections of ``tahoe.cfg``.

Drop-Upload

    As of Tahoe-LAFS v1.9.0, a node running on Linux can be configured to
    automatically upload files that are created or changed in a specified
    local directory. See :doc:`frontends/drop-upload` for details.


Storage Server Configuration
============================

``[storage]``

``enabled = (boolean, optional)``

    If this is ``True``, the node will run a storage server, offering space
    to other clients. If it is ``False``, the node will not run a storage
    server, meaning that no shares will be stored on this node. Use ``False``
    for clients who do not wish to provide storage service. The default value
    is ``True``.

``readonly = (boolean, optional)``

    If ``True``, the node will run a storage server but will not accept any
    shares, making it effectively read-only. Use this for storage servers
    that are being decommissioned: the ``storage/`` directory could be
    mounted read-only, while shares are moved to other servers. Note that
    this currently only affects immutable shares. Mutable shares (used for
    directories) will be written and modified anyway. See ticket `#390`_ for
    the current status of this bug. The default value is ``False``.

``reserved_space = (str, optional)``

    If provided, this value defines how much disk space is reserved: the
    storage server will not accept any share that causes the amount of free
    disk space to drop below this value. (The free space is measured by a
    call to ``statvfs(2)`` on Unix, or ``GetDiskFreeSpaceEx`` on Windows, and
    is the space available to the user account under which the storage server
    runs.)

    This string contains a number, with an optional case-insensitive scale
    suffix, optionally followed by "B" or "iB". The supported scale suffixes
    are "K", "M", "G", "T", "P" and "E", and a following "i" indicates to use
    powers of 1024 rather than 1000. So "100MB", "100 M", "100000000B",
    "100000000", and "100000kb" all mean the same thing. Likewise, "1MiB",
    "1024KiB", "1024 Ki", and "1048576 B" all mean the same thing.

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
    :doc:`garbage-collection` for full details.

.. _#390: https://tahoe-lafs.org/trac/tahoe-lafs/ticket/390


Running A Helper
================

A "helper" is a regular client node that also offers the "upload helper"
service.

``[helper]``

``enabled = (boolean, optional)``

    If ``True``, the node will run a helper (see :doc:`helper` for details).
    The helper's contact FURL will be placed in ``private/helper.furl``, from
    which it can be copied to any clients that wish to use it. Clearly nodes
    should not both run a helper and attempt to use one: do not create
    ``helper.furl`` and also define ``[helper]enabled`` in the same node. The
    default is ``False``.


Running An Introducer
=====================

The introducer node uses a different ``.tac`` file (named
"``introducer.tac``"), and pays attention to the ``[node]`` section, but not
the others.

The Introducer node maintains some different state than regular client nodes.

``BASEDIR/private/introducer.furl``

  This is generated the first time the introducer node is started, and used
  again on subsequent runs, to give the introduction service a persistent
  long-term identity. This file should be published and copied into new
  client nodes before they are started for the first time.


Other Files in BASEDIR
======================

Some configuration is not kept in ``tahoe.cfg``, for the following reasons:

* it is generated by the node at startup, e.g. encryption keys. The node
  never writes to ``tahoe.cfg``.
* it is generated by user action, e.g. the "``tahoe create-alias``" command.

In addition, non-configuration persistent state is kept in the node's base
directory, next to the configuration knobs.

This section describes these other files.

``private/node.pem``

  This contains an SSL private-key certificate. The node generates this the
  first time it is started, and re-uses it on subsequent runs. This
  certificate allows the node to have a cryptographically-strong identifier
  (the Foolscap "TubID"), and to establish secure connections to other nodes.

``storage/``

  Nodes that host StorageServers will create this directory to hold shares of
  files on behalf of other clients. There will be a directory underneath it
  for each StorageIndex for which this node is holding shares. There is also
  an "incoming" directory where partially-completed shares are held while
  they are being received.

``tahoe-client.tac``

  This file defines the client, by constructing the actual Client instance
  each time the node is started. It is used by the "``twistd``" daemonization
  program (in the ``-y`` mode), which is run internally by the "``tahoe
  start``" command. This file is created by the "``tahoe create-node``" or
  "``tahoe create-client``" commands.

``tahoe-introducer.tac``

  This file is used to construct an introducer, and is created by the
  "``tahoe create-introducer``" command.

``tahoe-stats-gatherer.tac``

  This file is used to construct a statistics gatherer, and is created by the
  "``tahoe create-stats-gatherer``" command.

``private/control.furl``

  This file contains a FURL that provides access to a control port on the
  client node, from which files can be uploaded and downloaded. This file is
  created with permissions that prevent anyone else from reading it (on
  operating systems that support such a concept), to insure that only the
  owner of the client node can use this feature. This port is intended for
  debugging and testing use.

``private/logport.furl``

  This file contains a FURL that provides access to a 'log port' on the
  client node, from which operational logs can be retrieved. Do not grant
  logport access to strangers, because occasionally secret information may be
  placed in the logs.

``private/helper.furl``

  If the node is running a helper (for use by other clients), its contact
  FURL will be placed here. See :doc:`helper` for more details.

``private/root_dir.cap`` (optional)

  The command-line tools will read a directory cap out of this file and use
  it, if you don't specify a '--dir-cap' option or if you specify
  '--dir-cap=root'.

``private/convergence`` (automatically generated)

  An added secret for encrypting immutable files. Everyone who has this same
  string in their ``private/convergence`` file encrypts their immutable files
  in the same way when uploading them. This causes identical files to
  "converge" -- to share the same storage space since they have identical
  ciphertext -- which conserves space and optimizes upload time, but it also
  exposes file contents to the possibility of a brute-force attack by people
  who know that string. In this attack, if the attacker can guess most of the
  contents of a file, then they can use brute-force to learn the remaining
  contents.

  So the set of people who know your ``private/convergence`` string is the
  set of people who converge their storage space with you when you and they
  upload identical immutable files, and it is also the set of people who
  could mount such an attack.

  The content of the ``private/convergence`` file is a base-32 encoded
  string.  If the file doesn't exist, then when the Tahoe-LAFS client starts
  up it will generate a random 256-bit string and write the base-32 encoding
  of this string into the file. If you want to converge your immutable files
  with as many people as possible, put the empty string (so that
  ``private/convergence`` is a zero-length file).


Other files
===========

``logs/``

  Each Tahoe-LAFS node creates a directory to hold the log messages produced
  as the node runs. These logfiles are created and rotated by the
  "``twistd``" daemonization program, so ``logs/twistd.log`` will contain the
  most recent messages, ``logs/twistd.log.1`` will contain the previous ones,
  ``logs/twistd.log.2`` will be older still, and so on. ``twistd`` rotates
  logfiles after they grow beyond 1MB in size. If the space consumed by
  logfiles becomes troublesome, they should be pruned: a cron job to delete
  all files that were created more than a month ago in this ``logs/``
  directory should be sufficient.

``my_nodeid``

  this is written by all nodes after startup, and contains a base32-encoded
  (i.e. human-readable) NodeID that identifies this specific node. This
  NodeID is the same string that gets displayed on the web page (in the
  "which peers am I connected to" list), and the shortened form (the first
  few characters) is recorded in various log messages.

``access.blacklist``

  Gateway nodes may find it necessary to prohibit access to certain
  files. The web-API has a facility to block access to filecaps by their
  storage index, returning a 403 "Forbidden" error instead of the original
  file. For more details, see the "Access Blacklist" section of
  :doc:`frontends/webapi`.


Example
=======

The following is a sample ``tahoe.cfg`` file, containing values for some of
the keys described in the previous section. Note that this is not a
recommended configuration (most of these are not the default values), merely
a legal one.

::

  [node]
  nickname = Bob's Tahoe-LAFS Node
  tub.port = 34912
  tub.location = 123.45.67.89:8098,44.55.66.77:8098
  web.port = 3456
  log_gatherer.furl = pb://soklj4y7eok5c3xkmjeqpw@192.168.69.247:44801/eqpwqtzm
  timeout.keepalive = 240
  timeout.disconnect = 1800
  
  [client]
  introducer.furl = pb://ok45ssoklj4y7eok5c3xkmj@tahoe.example:44801/ii3uumo
  helper.furl = pb://ggti5ssoklj4y7eok5c3xkmj@helper.tahoe.example:7054/kk8lhr
  
  [storage]
  enabled = True
  readonly = True
  reserved_space = 10000000000
  
  [helper]
  enabled = True


Old Configuration Files
=======================

Tahoe-LAFS releases before v1.3.0 had no ``tahoe.cfg`` file, and used
distinct files for each item. This is no longer supported and if you have
configuration in the old format you must manually convert it to the new
format for Tahoe-LAFS to detect it. See :doc:`historical/configuration`.
