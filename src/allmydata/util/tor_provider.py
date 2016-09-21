# -*- coding: utf-8 -*-

from __future__ import absolute_import
from __future__ import print_function
from __future__ import with_statement

from twisted.internet import reactor, defer

from .observer import OneShotObserverList

import txtorcon
from txtorcon import torconfig
from txtorcon import torcontrolprotocol

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

    @inlineCallbacks
    def allocate_onion(self, hs_dir):
        control_ep = yield self.get_control_endpoint() # launches Tor

        # from what I can tell, txtorcon ignores local_port, and always
        # assigns its own. We could fix this if/when there's a txtorcon
        # version that doesn't do that, or we could just always let txtorcon
        # allocate for us.
        #local_port = allocate_tcp_port()
        local_port = None

        # this allocates the onion service and waits for it to be published
        hs_ep = txtorcon.TCPHiddenServiceEndpoint.system_tor(
            reactor, control_ep, public_port, hs_dir, local_port)
        lp = yield hs_ep.listen(EMPTY_FACTORY)

        privkey = hs_ep.onion_private_key
        assert privkey is not None
        addr = lp.getHost()
        location = "tor:%s:%d" % (addr.onion_uri, addr.onion_port)

        # * tor_config is a dictionary of keys/values to add to the "[tor]"
        #   section of tahoe.cfg, which tells the new node how to launch Tor
        #   in the right way.
        # * privkey is a string, which will be written into a file, and then
        #   passed back into the new (tahoe-start) -time onion endpoint
        # * external_port is an integer, which we record and pass back in
        # * local_port is a server endpoint string, which is added to
        #   tub.port=, and also parsed to tell Tor where it should send
        #   inbound connections. It will probably start as tcp:%d, but could
        #   usefully be a unix-domain socket in BASEDIR/private/
        # * location is a foolscap connection hint, "tor:ONION:EXTERNAL_PORT"

        return (self._tor_config(), privkey, external_port, local_port, location)

class _Launch(_Common):
    def __init__(self, tor_binary=None, data_directory=None):
        _Common.__init__(self)
        self._data_directory = data_directory
        self._tor_binary = tor_binary
        self.tor_control_protocol = None
        self._when_launched = None

    def _tor_config(self):
        config = {"launch": "True"}
        if self._tor_binary:
            # TODO: it might be a good idea to find exactly which Tor we
            # used, and record it's absolute path into tahoe.cfg . This would
            # protect us against one Tor being on $PATH at create-node time,
            # but then a different Tor being present at node startup. OTOH,
            # maybe we don't need to worry about it.
            config["tor.executable"] = os.path.abspath(self._tor_binary)
        # We assume/require that the Node gives us the same data_directory=
        # at both create-node and startup time. The data directory is not
        # recorded in tahoe.cfg
        return config

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
