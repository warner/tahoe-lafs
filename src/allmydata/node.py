import datetime, os.path, re, types, ConfigParser, tempfile
from base64 import b32decode, b32encode

from twisted.python import log as twlog
from twisted.application import service
from twisted.internet import defer, reactor
from foolscap.api import Tub, eventually, app_versions
import foolscap.logging.log
import allmydata
from allmydata.util import log
from allmydata.util import fileutil, iputil, observer
from allmydata.util.assertutil import precondition, _assert
from allmydata.util.fileutil import abspath_expanduser_unicode
from allmydata.util.encodingutil import get_filesystem_encoding, quote_output

# Add our application versions to the data that Foolscap's LogPublisher
# reports.
app_versions.add_version("tahoe", allmydata.__version__)

# group 1 will be addr (dotted quad string), group 3 if any will be portnum (string)
ADDR_RE=re.compile("^([1-9][0-9]*\.[1-9][0-9]*\.[1-9][0-9]*\.[1-9][0-9]*)(:([1-9][0-9]*))?$")


def formatTimeTahoeStyle(self, when):
    # we want UTC timestamps that look like:
    #  2007-10-12 00:26:28.566Z [Client] rnp752lz: 'client running'
    d = datetime.datetime.utcfromtimestamp(when)
    if d.microsecond:
        return d.isoformat(" ")[:-3]+"Z"
    else:
        return d.isoformat(" ") + ".000Z"

PRIV_README="""
This directory contains files which contain private data for the Tahoe node,
such as private keys.  On Unix-like systems, the permissions on this directory
are set to disallow users other than its owner from reading the contents of
the files.   See the 'configuration.rst' documentation file for details."""

class _None: # used as a marker in get_config()
    pass

class MissingConfigEntry(Exception):
    """ A required config entry was not found. """

class OldConfigError(Exception):
    """ An obsolete config file was found. See
    docs/historical/configuration.rst. """
    def __str__(self):
        return ("Found pre-Tahoe-LAFS-v1.3 configuration file(s):\n"
                "%s\n"
                "See docs/historical/configuration.rst."
                % "\n".join([quote_output(fname) for fname in self.args[0]]))

class OldConfigOptionError(Exception):
    pass

class UnescapedHashError(Exception):
    def __str__(self):
        return ("The configuration entry %s contained an unescaped '#' character."
                % quote_output("[%s]%s = %s" % self.args))


class Node(service.MultiService):
    # this implements common functionality of both Client nodes and Introducer
    # nodes.
    NODETYPE = "unknown NODETYPE"
    PORTNUMFILE = None
    CERTFILE = "node.pem"
    GENERATED_FILES = []

    def __init__(self, basedir=u"."):
        service.MultiService.__init__(self)
        self.basedir = abspath_expanduser_unicode(unicode(basedir))
        self._portnumfile = os.path.join(self.basedir, self.PORTNUMFILE)
        self._tub_ready_observerlist = observer.OneShotObserverList()
        fileutil.make_dirs(os.path.join(self.basedir, "private"), 0700)
        open(os.path.join(self.basedir, "private", "README"), "w").write(PRIV_README)

        # creates self.config
        self.read_config()
        nickname_utf8 = self.get_config("node", "nickname", "<unspecified>")
        self.nickname = nickname_utf8.decode("utf-8")
        assert type(self.nickname) is unicode

        self.init_tempdir()
        self.create_tub()
        self.logSource="Node"

        self.setup_ssh()
        self.setup_logging()
        self.log("Node constructed. " + allmydata.__version__)
        iputil.increase_rlimits()

    def init_tempdir(self):
        tempdir_config = self.get_config("node", "tempdir", "tmp").decode('utf-8')
        tempdir = abspath_expanduser_unicode(tempdir_config, base=self.basedir)
        if not os.path.exists(tempdir):
            fileutil.make_dirs(tempdir)
        tempfile.tempdir = tempdir
        # this should cause twisted.web.http (which uses
        # tempfile.TemporaryFile) to put large request bodies in the given
        # directory. Without this, the default temp dir is usually /tmp/,
        # which is frequently too small.
        test_name = tempfile.mktemp()
        _assert(os.path.dirname(test_name) == tempdir, test_name, tempdir)

    @staticmethod
    def _contains_unescaped_hash(item):
        characters = iter(item)
        for c in characters:
            if c == '\\':
                characters.next()
            elif c == '#':
                return True

        return False

    def get_config(self, section, option, default=_None, boolean=False):
        try:
            if boolean:
                return self.config.getboolean(section, option)

            item = self.config.get(section, option)
            if option.endswith(".furl") and self._contains_unescaped_hash(item):
                raise UnescapedHashError(section, option, item)

            return item
        except (ConfigParser.NoOptionError, ConfigParser.NoSectionError):
            if default is _None:
                fn = os.path.join(self.basedir, u"tahoe.cfg")
                raise MissingConfigEntry("%s is missing the [%s]%s entry"
                                         % (quote_output(fn), section, option))
            return default

    def set_config(self, section, option, value):
        if not self.config.has_section(section):
            self.config.add_section(section)
        self.config.set(section, option, value)
        assert self.config.get(section, option) == value

    def read_config(self):
        self.error_about_old_config_files()
        self.config = ConfigParser.SafeConfigParser()

        tahoe_cfg = os.path.join(self.basedir, "tahoe.cfg")
        try:
            f = open(tahoe_cfg, "rb")
            try:
                # Skip any initial Byte Order Mark. Since this is an ordinary file, we
                # don't need to handle incomplete reads, and can assume seekability.
                if f.read(3) != '\xEF\xBB\xBF':
                    f.seek(0)
                self.config.readfp(f)
            finally:
                f.close()
        except EnvironmentError:
            if os.path.exists(tahoe_cfg):
                raise

        cfg_tubport = self.get_config("node", "tub.port", "")
        if not cfg_tubport:
            # For 'tub.port', tahoe.cfg overrides the individual file on
            # disk. So only read self._portnumfile if tahoe.cfg doesn't
            # provide a value.
            try:
                file_tubport = fileutil.read(self._portnumfile).strip()
                self.set_config("node", "tub.port", file_tubport)
            except EnvironmentError:
                if os.path.exists(self._portnumfile):
                    raise

    def error_about_old_config_files(self):
        """ If any old configuration files are detected, raise OldConfigError. """

        oldfnames = set()
        for name in [
            'nickname', 'webport', 'keepalive_timeout', 'log_gatherer.furl',
            'disconnect_timeout', 'advertised_ip_addresses', 'introducer.furl',
            'helper.furl', 'key_generator.furl', 'stats_gatherer.furl',
            'no_storage', 'readonly_storage', 'sizelimit',
            'debug_discard_storage', 'run_helper']:
            if name not in self.GENERATED_FILES:
                fullfname = os.path.join(self.basedir, name)
                if os.path.exists(fullfname):
                    oldfnames.add(fullfname)
        if oldfnames:
            e = OldConfigError(oldfnames)
            twlog.msg(e)
            raise e

    def create_tub(self):
        certfile = os.path.join(self.basedir, "private", self.CERTFILE)
        self.tub = Tub(certFile=certfile)
        self.tub.setOption("logLocalFailures", True)
        self.tub.setOption("logRemoteFailures", True)
        self.tub.setOption("expose-remote-exception-types", False)

        # see #521 for a discussion of how to pick these timeout values.
        keepalive_timeout_s = self.get_config("node", "timeout.keepalive", "")
        if keepalive_timeout_s:
            self.tub.setOption("keepaliveTimeout", int(keepalive_timeout_s))
        disconnect_timeout_s = self.get_config("node", "timeout.disconnect", "")
        if disconnect_timeout_s:
            # N.B.: this is in seconds, so use "1800" to get 30min
            self.tub.setOption("disconnectTimeout", int(disconnect_timeout_s))

        self.nodeid = b32decode(self.tub.tubID.upper()) # binary format
        self.write_config("my_nodeid", b32encode(self.nodeid).lower() + "\n")
        self.short_nodeid = b32encode(self.nodeid).lower()[:8] # ready for printing

        tubport = self.get_config("node", "tub.port", "tcp:0")
        self.tub.listenOn(tubport)
        # we must wait until our service has started before we can find out
        # our IP address and thus do tub.setLocation, and we can't register
        # any services with the Tub until after that point
        self.tub.setServiceParent(self)

    def setup_ssh(self):
        ssh_port = self.get_config("node", "ssh.port", "")
        if ssh_port:
            ssh_keyfile_config = self.get_config("node", "ssh.authorized_keys_file").decode('utf-8')
            ssh_keyfile = abspath_expanduser_unicode(ssh_keyfile_config, base=self.basedir)
            from allmydata import manhole
            m = manhole.AuthorizedKeysManhole(ssh_port, ssh_keyfile)
            m.setServiceParent(self)
            self.log("AuthorizedKeysManhole listening on %s" % (ssh_port,))

    def get_app_versions(self):
        # TODO: merge this with allmydata.get_package_versions
        return dict(app_versions.versions)

    def get_config_from_file(self, name, required=False):
        """Get the (string) contents of a config file, or None if the file
        did not exist. If required=True, raise an exception rather than
        returning None. Any leading or trailing whitespace will be stripped
        from the data."""
        fn = os.path.join(self.basedir, name)
        try:
            return fileutil.read(fn).strip()
        except EnvironmentError:
            if not required:
                return None
            raise

    def write_private_config(self, name, value):
        """Write the (string) contents of a private config file (which is a
        config file that resides within the subdirectory named 'private'), and
        return it.
        """
        privname = os.path.join(self.basedir, "private", name)
        open(privname, "w").write(value)

    def get_private_config(self, name, default=_None):
        """Read the (string) contents of a private config file (which is a
        config file that resides within the subdirectory named 'private'),
        and return it. Return a default, or raise an error if one was not
        given.
        """
        privname = os.path.join(self.basedir, "private", name)
        try:
            return fileutil.read(privname)
        except EnvironmentError:
            if os.path.exists(privname):
                raise
            if default is _None:
                raise MissingConfigEntry("The required configuration file %s is missing."
                                         % (quote_output(privname),))
            return default

    def get_or_create_private_config(self, name, default=_None):
        """Try to get the (string) contents of a private config file (which
        is a config file that resides within the subdirectory named
        'private'), and return it. Any leading or trailing whitespace will be
        stripped from the data.

        If the file does not exist, and default is not given, report an error.
        If the file does not exist and a default is specified, try to create
        it using that default, and then return the value that was written.
        If 'default' is a string, use it as a default value. If not, treat it
        as a zero-argument callable that is expected to return a string.
        """
        privname = os.path.join(self.basedir, "private", name)
        try:
            value = fileutil.read(privname)
        except EnvironmentError:
            if os.path.exists(privname):
                raise
            if default is _None:
                raise MissingConfigEntry("The required configuration file %s is missing."
                                         % (quote_output(privname),))
            if isinstance(default, basestring):
                value = default
            else:
                value = default()
            fileutil.write(privname, value)
        return value.strip()

    def write_config(self, name, value, mode="w"):
        """Write a string to a config file."""
        fn = os.path.join(self.basedir, name)
        try:
            fileutil.write(fn, value, mode)
        except EnvironmentError, e:
            self.log("Unable to write config file '%s'" % fn)
            self.log(e)

    def startService(self):
        # Note: this class can be started and stopped at most once.
        self.log("Node.startService")
        # Record the process id in the twisted log, after startService()
        # (__init__ is called before fork(), but startService is called
        # after). Note that Foolscap logs handle pid-logging by itself, no
        # need to send a pid to the foolscap log here.
        twlog.msg("My pid: %s" % os.getpid())
        try:
            os.chmod("twistd.pid", 0644)
        except EnvironmentError:
            pass
        # Delay until the reactor is running.
        eventually(self._startService)

    def _startService(self):
        precondition(reactor.running)
        self.log("Node._startService")

        service.MultiService.startService(self)
        d = defer.succeed(None)
        d.addCallback(self._setup_tub)
        def _ready(res):
            self.log("%s running" % self.NODETYPE)
            self._tub_ready_observerlist.fire(self)
            return self
        d.addCallback(_ready)
        d.addErrback(self._service_startup_failed)

    def _service_startup_failed(self, failure):
        self.log('_startService() failed')
        log.err(failure)
        print "Node._startService failed, aborting"
        print failure
        #reactor.stop() # for unknown reasons, reactor.stop() isn't working.  [ ] TODO
        self.log('calling os.abort()')
        twlog.msg('calling os.abort()') # make sure it gets into twistd.log
        print "calling os.abort()"
        os.abort()

    def stopService(self):
        self.log("Node.stopService")
        d = self._tub_ready_observerlist.when_fired()
        def _really_stopService(ignored):
            self.log("Node._really_stopService")
            return service.MultiService.stopService(self)
        d.addCallback(_really_stopService)
        return d

    def shutdown(self):
        """Shut down the node. Returns a Deferred that fires (with None) when
        it finally stops kicking."""
        self.log("Node.shutdown")
        return self.stopService()

    def setup_logging(self):
        # we replace the formatTime() method of the log observer that
        # twistd set up for us, with a method that uses our preferred
        # timestamp format.
        for o in twlog.theLogPublisher.observers:
            # o might be a FileLogObserver's .emit method
            if type(o) is type(self.setup_logging): # bound method
                ob = o.im_self
                if isinstance(ob, twlog.FileLogObserver):
                    newmeth = types.UnboundMethodType(formatTimeTahoeStyle, ob, ob.__class__)
                    ob.formatTime = newmeth
        # TODO: twisted >2.5.0 offers maxRotatedFiles=50

        lgfurl_file = os.path.join(self.basedir, "private", "logport.furl").encode(get_filesystem_encoding())
        self.tub.setOption("logport-furlfile", lgfurl_file)
        lgfurl = self.get_config("node", "log_gatherer.furl", "")
        if lgfurl:
            # this is in addition to the contents of log-gatherer-furlfile
            self.tub.setOption("log-gatherer-furl", lgfurl)
        self.tub.setOption("log-gatherer-furlfile",
                           os.path.join(self.basedir, "log_gatherer.furl"))
        self.tub.setOption("bridge-twisted-logs", True)
        incident_dir = os.path.join(self.basedir, "logs", "incidents")
        foolscap.logging.log.setLogDir(incident_dir.encode(get_filesystem_encoding()))

    def log(self, *args, **kwargs):
        return log.msg(*args, **kwargs)

    def _setup_tub(self, ign):
        # we can't get a dynamically-assigned portnum until our Tub is
        # running, which means after startService.
        l = self.tub.getListeners()[0]
        portnum = l.getPortnum()
        # record which port we're listening on, so we can grab the same one
        # next time
        fileutil.write_atomically(self._portnumfile, "%d\n" % portnum, mode="")

        location = self.get_config("node", "tub.location", "AUTO")

        # Replace the location "AUTO", if present, with the detected local addresses.
        split_location = location.split(",")
        if "AUTO" in split_location:
            d = iputil.get_local_addresses_async()
            def _add_local(local_addresses):
                while "AUTO" in split_location:
                    split_location.remove("AUTO")

                split_location.extend([ "%s:%d" % (addr, portnum)
                                        for addr in local_addresses ])
                return ",".join(split_location)
            d.addCallback(_add_local)
        else:
            d = defer.succeed(location)

        def _got_location(location):
            self.log("Tub location set to %s" % (location,))
            self.tub.setLocation(location)
            return self.tub
        d.addCallback(_got_location)
        return d

    def when_tub_ready(self):
        return self._tub_ready_observerlist.when_fired()

    def add_service(self, s):
        s.setServiceParent(self)
        return s
