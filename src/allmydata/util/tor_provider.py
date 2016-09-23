# -*- coding: utf-8 -*-

from __future__ import absolute_import
from __future__ import print_function
from __future__ import with_statement

from twisted.internet import reactor, defer
from twisted.internet.defer import inlineCallbacks

from .observer import OneShotObserverList

import txtorcon
from txtorcon import TorConfig, launch_tor

@inlineCallbacks
def _connect_to_tor(reactor, endpoint_desc=None):
    # fires with (control_endpoint_desc, tor_control_protocol)
    if endpoint_desc:
        ep = endpoints.clientFromString(reactor, endpoint_desc)
        tor_state = yield txtorcon.build_tor_connection(ep)
        
        tor_state = yield txtorcon.build_tor_connection(
    try:
        tor_state = yield txtorcon
        returnValue(txtorcon.

@inlineCallbacks
def create_onion(reactor, cli_config):
    private_dir = os.path.join(cli_config["basedir"], "private")
    data_directory = os.path.join(private_dir, "tor")
    tahoe_config_tor = {} # written into tahoe.cfg:[tor]
    if cli_config["tor-launch"]:
        tahoe_config_tor["launch"] = "true"
        control_port = allocate_tcp_port()
        tor_binary = cli_config["tor-executable"]
        tor_confg = txtorcon.TorConfig()
        tor_confg.DataDirectory = data_directory
        tor_confg.ControlPort = control_port
        tpp = yield txtorcon.launch_tor(tor_confg, reactor,
                                        tor_binary=tor_binary)
        tcp = tpp.tor_protocol

        # now tor is launched and ready to be spoken to
        # TODO: how/when to shut down?
    else:
        # we assume tor is already running
        tor_state = yield txtorcon.build_local_tor_connection(reactor..)
        tcp = tor_state.protocol

    # from what I can tell, txtorcon ignores local_port, and always
    # assigns its own. We could fix this if/when there's a txtorcon
    # version that doesn't do that, or we could just always let txtorcon
    # allocate for us.
    #local_port = allocate_tcp_port()
    local_port = None
    onion_port = 3457

    # this allocates the onion service and waits for it to be published
    hs_ep = txtorcon.TCPHiddenServiceEndpoint.system_tor(
        reactor, control_ep, public_port, hs_dir, local_port)
    lp = yield hs_ep.listen(EMPTY_FACTORY)

    privkey = hs_ep.onion_private_key
    assert privkey is not None
    addr = lp.getHost()
    location = "tor:%s:%d" % (addr.onion_uri, addr.onion_port)

    tahoe_config_tor["onion.external_port"] = str(external_port)
    tahoe_config_tor["onion.local_port"] = str(local_port)
    tahoe_config_tor["onion.private_key_file"] = "private/tor_onion.privkey"
    privkeyfile = os.path.join(private_dir, "tor_onion.privkey")
    with open(privkeyfile, "wb") as f:
        f.write(privkey)

    # * tahoe_config_tor is a dictionary of keys/values to add to the "[tor]"
    #   section of tahoe.cfg, which tells the new node how to launch Tor in
    #   the right way.
    # * privkey is a string, which will be written into a file, and then
    #   passed back into the new (tahoe-start) -time onion endpoint
    # * external_port is an integer, which we record and pass back in
    # * local_port is a server endpoint string, which is added to
    #   tub.port=, and also parsed to tell Tor where it should send
    #   inbound connections. It will probably start as tcp:%d, but could
    #   usefully be a unix-domain socket in BASEDIR/private/
    # * location is a foolscap connection hint, "tor:ONION:EXTERNAL_PORT"

    tahoe_config_tor = {"launch": "True"}
    if self._tor_binary:
        # TODO: it might be a good idea to find exactly which Tor we
        # used, and record it's absolute path into tahoe.cfg . This would
        # protect us against one Tor being on $PATH at create-node time,
        # but then a different Tor being present at node startup. OTOH,
        # maybe we don't need to worry about it.
        tahoe_config_tor["tor.executable"] = os.path.abspath(self._tor_binary)
    # We assume/require that the Node gives us the same data_directory=
    # at both create-node and startup time. The data directory is not
    # recorded in tahoe.cfg

    returnValue(tahoe_config_tor, tor_port, tor_location)

def _import_tor():
    # this exists to be overridden by unit tests
    try:
        from foolscap.connections import tor
        return tor
    except ImportError: # pragma: no cover
        return None

def _import_txtorcon():
    try:
        import txtorcon
        return txtorcon
    except ImportError: # pragma: no cover
        return None

class Provider(service.MultiService):
    def __init__(self, tahoe_config_tor):
        service.MultiService.__init__(self)
        self._tahoe_config_tor = tahoe_config_tor

    def get_tor_handler(self):
        enabled = get_config("tor", "enabled", True, boolean=True)
        if not enabled:
            return None
        tor = _import_tor()
        if not tor:
            return None

        # this changes, to share the launched Tor with an onion listener
        if get_config("tor", "launch", False, boolean=True):
            executable = get_config("tor", "tor.executable", None)
            datadir = os.path.join(self.basedir, "private", "tor-statedir")
            self._tor_provider = tor_provider.launch(tor_binary=executable,
                                                     data_directory=datadir)
            self._tor_provider.setServiceParent(self)
            return self._tor_provider.get_foolscap_handler()

        # this stays the same
        socks_endpoint_desc = get_config("tor", "socks.port", None)
        if socks_endpoint_desc:
            socks_ep = endpoints.clientFromString(reactor, socks_endpoint_desc)
            return tor.socks_endpoint(socks_ep)

        # this stays the same
        controlport = get_config("tor", "control.port", None)
        if controlport:
            ep = endpoints.clientFromString(reactor, controlport)
            self._tor_provider = tor_provider.control_endpoint(ep)
            self._tor_provider.setServiceParent(self)
            return self._tor_provider.get_foolscap_handler()

        return tor.default_socks()

    def startService(self):
        # launch tor, if necessary
        # start onion service, if necessary
        pass
    def stopService(self):
        # stop tor??
        pass

##### ignore past here

@defer.inlineCallbacks
def CreateOnion(tor_provider, key_file, onion_port):
    local_port = yield txtorcon.util.available_tcp_port(reactor)
    # XXX in the future we need to make it use UNIX domain sockets instead of TCP
    hs_string = '%s 127.0.0.1:%d' % (onion_port, local_port)
    service = txtorcon.EphemeralHiddenService([hs_string])
    tor_protocol = yield tor_provider.get_control_protocol()
    yield service.add_to_tor(tor_protocol)

# control_endpoint:
#  init with control_endpoint
#  * get_foolscap_handler: return tor.control_endpoint(control_endpoint)
#  * XX control_protocol: torcontrolprotocol(control_endpoint)
#  * get_tub_listener: return listening endpoint
#  init with launch parameters
#  * foolscap: return tor.control_endpoint_maker
#              wrapped around: launch, wait, get control_endpoint, return
#  * control_protocol: launch, wait, get control_endpoint,
#                      return torcontrolprotocol(control_endpoint)
# node:

class _Common(service.MultiService):
    def __init__(self):
        service.MultiService.__init__(self)
        self._when_control_endpoint = None
        self._when_protocol = None
        self._need_running = False

    def get_control_endpoint(self):
        self._need_running = True
        if not self._when_control_endpoint:
            self._when_control_endpoint = OneShotObserverList()
            d = self._connectXXX()
            d.addBoth(self._when_control_endpoint.fire)
        return self._when_control_endpoint.whenFired()

    def get_control_protocol(self):
        self._need_running = True
        if not self._when_protocol:
            self._when_protocol = OneShotObserverList()
            d = self._connect()
            d.addBoth(self._when_protocol.fire)
        return self._when_protocol.whenFired()

    # subclass must implement _connect() and get_foolscap_handler() and
    # get_tub_listener()

class _Launch(_Common):
    def __init__(self, tor_binary=None, data_directory=None):
        _Common.__init__(self)
        self._data_directory = data_directory
        self._tor_binary = tor_binary
        self.tor_control_protocol = None
        self._when_launched = None

    def _maybe_launch(self):
        if not self._when_launched:
            self._when_launched = OneShotObserverList()
            d = self._launch()
            d.addBoth(self._when_launched.fire)
        return self._when_launched.whenFired()

    @inlineCallbacks
    def _launch(self, reactor):
        # create a new Tor
        config = self.config = txtorcon.TorConfig()
        if self._data_directory:
            # The default is for launch_tor to create a tempdir itself, and
            # delete it when done. We only need to set a DataDirectory if we
            # want it to be persistent. This saves some startup time, because
            # we cache the descriptors from last time. On one of my hosts,
            # this reduces connect from 20s to 15s.
            if not os.path.exists(self._data_directory):
                # tor will mkdir this, but txtorcon wants to chdir to it
                # before spawning the tor process, so (for now) we need to
                # mkdir it ourselves. TODO: txtorcon should take
                # responsibility for this.
                os.mkdir(self._data_directory)
            config.DataDirectory = self._data_directory

        #config.ControlPort = allocate_tcp_port() # defaults to 9052
        config.SocksPort = allocate_tcp_port()
        socks_desc = "tcp:127.0.0.1:%d" % config.SocksPort
        self._socks_desc = socks_desc # stash for tests
        self._socks_endpoint = clientFromString(reactor, socks_desc)

        #print "launching tor"
        tpp = yield txtorcon.launch_tor(config, reactor,
                                        tor_binary=self._tor_binary)
        #print "launched"
        # gives a TorProcessProtocol with .tor_protocol
        self._tor_protocol = tpp.tor_protocol
        returnValue(socks_endpoint)

    def _make_control_endpoint(self, reactor):
        yield self._maybe_launch()
        returnValue(self._control_endpoint)

    def get_foolscap_handler(self):
        return tor.control_endpoint_maker(self._make_control_endpoint)

    def _connect(self):
        
            if self.control_endpoint is None:
                config = torconfig.TorConfig()
                if self.data_directory is not None:
                    config['DataDirectory'] = self.data_directory
                d = torconfig.launch_tor(config, reactor, tor_binary=self.tor_binary)
                d.addCallback(lambda result: result.tor_protocol)
            else:
                d = torcontrolprotocol.connect(self.control_endpoint)
            def remember_tor_protocol(result):
                self.tor_control_protocol = result
                return result
            d.addCallback(remember_tor_protocol)
        return d

def launch(tor_binary=None, data_directory=None):
    return _launch(tor_binary=tor_binary, data_directory=data_directory)


class _ControlEndpoint(_Common):
    def __init__(self, control_endpoint):
        _Common.__init__(self)
        self._control_endpoint = control_endpoint

    def get_foolscap_handler(self):
        return tor.control_endpoint(self._control_endpoint)

    def _connect(self):
        return txtorcon.torcontrolprotocol(self._control_endpoint)

    def get_control_protocol(self):
        """
        Returns a deferred which fires with the txtorcon tor control port object
        """
        if self.tor_control_protocol is not None:
            return defer.succeed(self.tor_control_protocol)
        else:
            if self.control_endpoint is None:
                config = torconfig.TorConfig()
                if self.data_directory is not None:
                    config['DataDirectory'] = self.data_directory
                d = torconfig.launch_tor(config, reactor, tor_binary=self.tor_binary)
                d.addCallback(lambda result: result.tor_protocol)
            else:
                d = torcontrolprotocol.connect(self.control_endpoint)
            def remember_tor_protocol(result):
                self.tor_control_protocol = result
                return result
            d.addCallback(remember_tor_protocol)
        return d

def control_endpoint(control_endpoint):
    return _TorProvider(control_endpoint=control_endpoint)
