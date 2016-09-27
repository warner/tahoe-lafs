# -*- coding: utf-8 -*-
from __future__ import absolute_import, print_function, with_statement
import os
from twisted.internet import reactor, protocol, addresses, service
from twisted.internet.defer import inlineCallbacks, returnValue
from twisted.internet.endpoints import clientFromString
from .observer import OneShotObserverList
from .iputil import allocate_tcp_port
import txtorcon

def data_directory(private_dir):
    return os.path.join(private_dir, "tor-statedir")


# different ways we might approach this:

# 1: get an ITorControlProtocol, make a
# txtorcon.EphemeralHiddenService(ports), yield ehs.add_to_tor(tcp), store
# ehs.hostname and ehs.private_key, yield ehs.remove_from_tor(tcp)

# 2: get a control endpoint (string), then
# ep = TCPHiddenServiceEndpoint.system_tor(control_endpoint, portstuff)
# and point hidden_service_dir= at a persistent directory, then
# lp = yield ep.listen(empty factory), store ep.onion_uri and
# ep.onion_private_key, yield lp.stopListening()

APPROACH = 1

def _try_to_connect(endpoint):
    # yields a TorState, or None
    d = txtorcon.build_tor_connection(endpoint)
    def _failed(f):
        f.trap(SomethingError)
        return None
    d.addErrback(_failed)
    return d

@inlineCallbacks
def create_onion(reactor, cli_config):
    private_dir = os.path.join(cli_config["basedir"], "private")
    tahoe_config_tor = {} # written into tahoe.cfg:[tor]
    if cli_config["tor-launch"]:
        # TODO: handle default tor-executable
        tahoe_config_tor["launch"] = "true"
        control_port = allocate_tcp_port()
        tor_binary = cli_config["tor-executable"]
        if cli_config["tor-executable"]:
            tahoe_config_tor["tor.executable"] = cli_config["tor-executable"]
        # TODO: it might be a good idea to find exactly which Tor we used,
        # and record it's absolute path into tahoe.cfg . This would protect
        # us against one Tor being on $PATH at create-node time, but then a
        # different Tor being present at node startup. OTOH, maybe we don't
        # need to worry about it.
        tor_config = txtorcon.TorConfig()
        tor_config.DataDirectory = data_directory(private_dir)
        tor_config.ControlPort = control_port
        tpp = yield txtorcon.launch_tor(tor_config, reactor,
                                        tor_binary=tor_binary)
        # now tor is launched and ready to be spoken to
        if APPROACH == 1:
            # as a side effect, we've got an ITorControlProtocol ready to go
            tor_control_proto = tpp.tor_protocol
        else:
            tor_control_endpoint = "tcp:127.0.0.1:%d" % control_port # unix?

        # How/when to shut down the new process? for normal usage, the child
        # tor will exit when it notices its parent (us) quit. Unit tests will
        # mock out txtorcon.launch_tor(), so there will never be a real Tor
        # process. So I guess we don't need to track the process.
    else:
        # we assume tor is already running
        ports_to_try = ["unix:/var/run/tor/control",
                        "tcp:127.0.0.1:9051",
                        "tcp:127.0.0.1:9151", # TorBrowserBundle
                        ]
        if cli_config["tor-control-endpoint"]:
            ports_to_try = cli_config["tor-control-endpoint"]
        for tor_control_endpoint in ports_to_try:
            ep = clientFromString(reactor, tor_control_endpoint)
            tor_state = yield _try_to_connect(ep)
            if tor_state:
                break
        else:
            raise PrivacyError("unable to reach default Tor control ports")
        tahoe_config_tor["control.port"] = tor_control_endpoint
        if APPROACH == 1:
            tor_control_proto = tor_state.protocol
        else:
            # we already have tor_control_endpoint set up
            pass

    external_port = 3457 # TODO: pick this randomly? there's no contention.

    if APPROACH == 1:
        local_port = allocate_tcp_port()
        ehs = txtorcon.EphemeralHiddenService("%d 127.0.0.1:%d" %
                                              (local_port, external_port))
        yield ehs.add_to_tor(tor_control_proto)
        tor_port = "tcp:127.0.0.1:%d" % local_port
        tor_location = "tor:%s:%d" % (ehs.hostname, external_port)
        privkey = ehs.private_key
        yield ehs.remove_from_tor(tor_control_proto)
    else: # approach 2
        # this allocates the onion service and waits for it to be published

        # from what I can tell, txtorcon ignores local_port=, and always
        # assigns its own (txtorcon.endpoints.TCPHiddenServiceEndpoint.listen
        # at line 422). We could fix this if/when there's a txtorcon version
        # that doesn't do that, or we could just always let txtorcon allocate
        # for us.

        # TCPHiddenServiceEndpoint doesn't accept a privatekey= argument, so
        # we need to use a persistent hidden_service_dir= instead.
        relative_hsdir = os.path.join("private", "tor-hsdir")
        hs_dir = os.path.join(cli_config["basedir"], relative_hsdir)
        ep = txtorcon.TCPHiddenServiceEndpoint.system_tor(
            reactor, tor_control_endpoint, external_port,
            hidden_service_dir=hs_dir, local_port=None)
        empty_factory = protocol.Factory()
        lp = yield ep.listen(empty_factory)

        local_addr = lp.local_address.getHost()
        assert isinstance(local_addr, addresses.IPv4Address)
        # assume local_addr.host is localhost or 127.0.0.1
        local_port = local_addr.port
        tor_port = "tcp:127.0.0.1:%d" % local_port

        addr = lp.getHost()
        tor_location = "tor:%s:%d" % (addr.onion_uri, addr.external_port)

        #privkey = ep.onion_private_key
        #assert privkey is not None

        yield lp.stopListening()

    # in addition to the "how to launch/connect-to tor" keys above, we also
    # record information about the onion service into tahoe.cfg.
    # * "local_port" is a server endpont string, which should match
    #   "tor_port" (which will be added to tahoe.cfg [node] tub.port)
    # * "external_port" is the random "public onion port" (integer), which
    #   (when combined with the .onion address) should match "tor_location"
    #   (which will be added to tub.location)
    # * "private_key_file" points to the on-disk copy of the private key
    #   material (although we always write it to the same place)

    tahoe_config_tor["onion"] = "true"
    tahoe_config_tor["onion.local_port"] = str(local_port)
    tahoe_config_tor["onion.external_port"] = str(external_port)
    if APPROACH == 1:
        assert privkey
        tahoe_config_tor["onion.private_key_file"] = "private/tor_onion.privkey"
        privkeyfile = os.path.join(private_dir, "tor_onion.privkey")
        with open(privkeyfile, "wb") as f:
            f.write(privkey)
    else:
        tahoe_config_tor["onion.hidden_service_dir"] = relative_hsdir

    # tahoe_config_tor: this is a dictionary of keys/values to add to the
    # "[tor]" section of tahoe.cfg, which tells the new node how to launch
    # Tor in the right way.

    # tor_port: a server endpoint string, it will be added to tub.port=

    # tor_location: a foolscap connection hint, "tor:ONION:EXTERNAL_PORT"

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
    def __init__(self, basedir, node_for_config):
        service.MultiService.__init__(self)
        self._basedir = basedir
        self._node_for_config = node_for_config
        self._tor_launched = None

    def _get_tor_config(self, *args, **kwargs):
        return self._node_for_config.get_config("tor", *args, **kwargs)

    def get_tor_handler(self):
        enabled = self._get_tor_config("enabled", True, boolean=True)
        if not enabled:
            return None
        tor = _import_tor()
        if not tor:
            return None

        if self._get_tor_config("launch", False, boolean=True):
            return tor.control_endpoint_maker(self._make_control_endpoint)

        socks_endpoint_desc = self._get_tor_config("socks.port", None)
        if socks_endpoint_desc:
            socks_ep = clientFromString(reactor, socks_endpoint_desc)
            return tor.socks_endpoint(socks_ep)

        controlport = self._get_tor_config("control.port", None)
        if controlport:
            ep = clientFromString(reactor, controlport)
            return tor.control_endpoint(ep)

        return tor.default_socks()

    @inlineCallbacks
    def _make_control_endpoint(self, reactor):
        # this will only be called when tahoe.cfg has "[tor] launch = true"
        (tor_control_endpoint, _) = yield self._get_launched_tor(reactor)
        returnValue(tor_control_endpoint)

    def _get_launched_tor(self, reactor):
        # this fires with a tuple of (control_endpoint, tor_protocol)
        if not self._tor_launched:
            self._tor_launched = OneShotObserverList()
            d = self._launch_tor(reactor)
            d.addBoth(self._tor_launched)
        return self._tor_launched.whenFired()

    @inlineCallbacks
    def _launch_tor(self, reactor):
        private_dir = os.path.join(self._basedir, "private")
        tor_binary = self._get_tor_config("tor.executable", None)
        tor_config = txtorcon.TorConfig()
        tor_config.DataDirectory = data_directory(private_dir)
        # we allocate a new control port each time
        port = allocate_tcp_port()
        tor_config.ControlPort = port
        tpp = yield txtorcon.launch_tor(tor_config, reactor,
                                        tor_binary=tor_binary)
        tor_control_proto = tpp.tor_protocol
        tor_control_endpoint = clientFromString(reactor,
                                                "tcp:127.0.0.1:%d" % port)
        rv = (tor_control_endpoint, tor_control_proto)
        returnValue(rv)

    def check_onion_config(self):
        if self._get_tor_config("onion", False, boolean=True):
            # to start an onion server, we either need a Tor control port, or
            # we need to launch tor
            launch = self._get_tor_config("launch", False, boolean=True)
            controlport = self._get_tor_config("control.port", None)
            if not launch and not controlport:
                raise ValueError("[tor] onion = true, but we have neither "
                                 "launch=true or control.port=")
            # check that all the expected onion-specific keys are present
            def require(name):
                if not self._get_tor_config("onion.%s" % name, None):
                    raise ValueError("[tor] onion = true,"
                                     " but onion.%s= is missing" % name)
            require("local_port")
            require("external_port")
            if APPROACH == 1:
                require("private_key_file")
            else:
                require("hidden_service_dir")

    @inlineCallbacks
    def _start_onion(self):
        # launch tor, if necessary
        if self._get_tor_config("launch", False, boolean=True):
            (tcep, tor_control_proto) = yield self._get_launched_tor(reactor)
        else:
            controlport = self._get_tor_config("control.port", None)
            tcep = clientFromString(reactor, controlport)
            tor_state = yield txtorcon.build_tor_connection(tcep)
            tor_control_proto = tor_state.protocol

        local_port = int(self._get_tor_config("onion.local_port"))
        external_port = int(self._get_tor_config("onion.external_port"))
        private_dir = os.path.join(self._basedir, "private")

        if APPROACH == 1:
            fn = self._get_tor_config("onion.private_key_file")
            privkeyfile = os.path.join(private_dir, fn)
            with open(privkeyfile, "rb") as f:
                privkey = f.read()
            ehs = txtorcon.EphemeralHiddenService(
                "%d 127.0.0.1:%d" % (local_port, external_port), privkey)
            yield ehs.add_to_tor(tor_control_proto)
        else:
            relative_hsdir = self._get_tor_config("onion.hidden_service_dir")
            hs_dir = os.path.join(self._basedir, relative_hsdir)
            hsep = txtorcon.TCPHiddenServiceEndpoint.system_tor(
                reactor, tcep, external_port,
                hidden_service_dir=hs_dir, local_port=None)
            # now.. wait, at this point do we do tub.listenOn(hsep)?
            TUB.listenOn(hsep)


    def startService(self):
        service.MultiService.startService(self)
        # if we need to start an onion service, now is the time
        if self._get_tor_config("onion", False, boolean=True):
            self._start_onion(reactor)

    def stopService(self):
        # stop tor??
        pass
