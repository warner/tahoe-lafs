import os
from twisted.trial import unittest
from twisted.internet import defer, error
from StringIO import StringIO
import mock
from ..util import tor_provider
from ..scripts import create_node

def mock_txtorcon(txtorcon):
    return mock.patch("allmydata.util.tor_provider._import_txtorcon",
                      return_value=txtorcon)

def mock_tor(tor):
    return mock.patch("allmydata.util.tor_provider._import_tor",
                      return_value=tor)

class Connect(unittest.TestCase):
    def test_try(self):
        reactor = object()
        txtorcon = mock.Mock()
        tor_state = object()
        d = defer.succeed(tor_state)
        txtorcon.build_tor_connection = mock.Mock(return_value=d)
        ep = object()
        stdout = StringIO()
        with mock.patch("allmydata.util.tor_provider.clientFromString",
                        return_value=ep) as cfs:
            d = tor_provider._try_to_connect(reactor, "desc", stdout, txtorcon)
        r = self.successResultOf(d)
        self.assertIs(r, tor_state)
        cfs.assert_called_with(reactor, "desc")
        txtorcon.build_tor_connection.assert_called_with(ep)

    def test_try_handled_error(self):
        reactor = object()
        txtorcon = mock.Mock()
        d = defer.fail(error.ConnectError("oops"))
        txtorcon.build_tor_connection = mock.Mock(return_value=d)
        ep = object()
        stdout = StringIO()
        with mock.patch("allmydata.util.tor_provider.clientFromString",
                        return_value=ep) as cfs:
            d = tor_provider._try_to_connect(reactor, "desc", stdout, txtorcon)
        r = self.successResultOf(d)
        self.assertIs(r, None)
        cfs.assert_called_with(reactor, "desc")
        txtorcon.build_tor_connection.assert_called_with(ep)
        self.assertEqual(stdout.getvalue(),
                         "Unable to reach Tor at 'desc': "
                         "An error occurred while connecting: oops.\n")

    def test_try_unhandled_error(self):
        reactor = object()
        txtorcon = mock.Mock()
        d = defer.fail(ValueError("oops"))
        txtorcon.build_tor_connection = mock.Mock(return_value=d)
        ep = object()
        stdout = StringIO()
        with mock.patch("allmydata.util.tor_provider.clientFromString",
                        return_value=ep) as cfs:
            d = tor_provider._try_to_connect(reactor, "desc", stdout, txtorcon)
        f = self.failureResultOf(d)
        self.assertIsInstance(f.value, ValueError)
        self.assertEqual(str(f.value), "oops")
        cfs.assert_called_with(reactor, "desc")
        txtorcon.build_tor_connection.assert_called_with(ep)
        self.assertEqual(stdout.getvalue(), "")

class Create(unittest.TestCase):
    def test_no_txtorcon(self):
        with mock.patch("allmydata.util.tor_provider._import_txtorcon",
                        return_value=None):
            d = tor_provider.create_onion("reactor", "cli_config")
            f = self.failureResultOf(d)
            self.assertIsInstance(f.value, ValueError)
            self.assertEqual(str(f.value),
                             "Cannot create onion without txtorcon. "
                             "Please 'pip install tahoe-lafs[tor]' to fix this.")

    def _do_test_launch(self, tor_executable):
        reactor = object()
        private_dir = "private"
        txtorcon = mock.Mock()
        tpp = mock.Mock
        tpp.tor_protocol = mock.Mock()
        txtorcon.launch_tor = mock.Mock(return_value=tpp)

        with mock.patch("allmydata.util.tor_provider.allocate_tcp_port",
                        return_value=999999):
            d = tor_provider._launch_tor(reactor, tor_executable, private_dir,
                                         txtorcon)
        tor_control_endpoint, tor_control_proto = self.successResultOf(d)
        self.assertIs(tor_control_proto, tpp.tor_protocol)

    def test_launch(self):
        return self._do_test_launch(None)
    def test_launch_executable(self):
        return self._do_test_launch("mytor")

    def _do_test_connect(self, endpoint, reachable):
        reactor = object()
        cli_config = create_node.CreateNodeOptions()
        #cli_config["tor-launch"] = False
        cli_config["tor-control-endpoint"] = endpoint
        cli_config.stdout = stdout = StringIO()
        expected_port = "tcp:127.0.0.1:9151"
        if endpoint:
            expected_port = endpoint
        tor_state = mock.Mock
        tor_state.protocol = object()
        tried = []
        def _try_to_connect(reactor, port, stdout):
            tried.append( (reactor, port, stdout) )
            if not reachable:
                return defer.succeed(None)
            if port == expected_port: # second one on the list
                return defer.succeed(tor_state)
            return defer.succeed(None)

        with mock.patch("allmydata.util.tor_provider._try_to_connect",
                        _try_to_connect):
            d = tor_provider._connect_to_tor(reactor, cli_config)
        if not reachable:
            f = self.failureResultOf(d)
            self.assertIsInstance(f.value, ValueError)
            self.assertEqual(str(f.value),
                             "unable to reach any default Tor control port")
            return
        successful_port, tor_control_proto = self.successResultOf(d)
        self.assertEqual(successful_port, expected_port)
        self.assertIs(tor_control_proto, tor_state.protocol)
        expected = [(reactor, "unix:/var/run/tor/control", stdout),
                    (reactor, "tcp:127.0.0.1:9051", stdout),
                    (reactor, "tcp:127.0.0.1:9151", stdout),
                    ]
        if endpoint:
            expected = [(reactor, endpoint, stdout)]
        self.assertEqual(tried, expected)

    def test_connect(self):
        return self._do_test_connect(None, True)
    def test_connect_endpoint(self):
        return self._do_test_connect("tcp:other:port", True)
    def test_connect_unreachable(self):
        return self._do_test_connect(None, False)


    def _do_test_create_launch(self, executable):
        basedir = self.mktemp()
        os.mkdir(basedir)
        private_dir = os.path.join(basedir, "private")
        os.mkdir(private_dir)
        reactor = object()
        cli_config = create_node.CreateNodeOptions()
        cli_config.update({"basedir": basedir,
                           "tor-launch": True,
                           })
        if executable:
            cli_config["tor-executable"] = executable
        cli_config.stdout = StringIO()
        protocol = object()
        launch_tor = mock.Mock(return_value=defer.succeed(("control_endpoint",
                                                           protocol)))
        txtorcon = mock.Mock()
        ehs = mock.Mock()
        ehs.private_key = "privkey"
        ehs.hostname = "ONION.onion"
        txtorcon.EphemeralHiddenService = mock.Mock(return_value=ehs)
        ehs.add_to_tor = mock.Mock(return_value=defer.succeed(None))
        ehs.remove_from_tor = mock.Mock(return_value=defer.succeed(None))

        with mock_txtorcon(txtorcon):
            with mock.patch("allmydata.util.tor_provider._launch_tor",
                            launch_tor):
                with mock.patch("allmydata.util.tor_provider.allocate_tcp_port",
                                return_value=999999):
                    d = tor_provider.create_onion(reactor, cli_config)
        tahoe_config_tor, tor_port, tor_location = self.successResultOf(d)

        launch_tor.assert_called_with(reactor, executable, private_dir,
                                      txtorcon)
        txtorcon.EphemeralHiddenService.assert_called_with("999999 127.0.0.1:3457")
        ehs.add_to_tor.assert_called_with(protocol)
        ehs.remove_from_tor.assert_called_with(protocol)

        expected = {"launch": "true",
                    "onion": "true",
                    "onion.local_port": "999999",
                    "onion.external_port": "3457",
                    "onion.private_key_file": "private/tor_onion.privkey",
                    }
        if executable:
            expected["tor.executable"] = executable
        self.assertEqual(tahoe_config_tor, expected)
        self.assertEqual(tor_port, "tcp:127.0.0.1:999999")
        self.assertEqual(tor_location, "tor:ONION.onion:3457")
        fn = os.path.join(basedir, tahoe_config_tor["onion.private_key_file"])
        with open(fn, "rb") as f:
            privkey = f.read()
        self.assertEqual(privkey, "privkey")

    def test_create_launch(self):
        return self._do_test_create_launch(None)
    def test_create_launch_executable(self):
        return self._do_test_create_launch("mytor")

    def test_create_control_endpoint(self):
        basedir = self.mktemp()
        os.mkdir(basedir)
        private_dir = os.path.join(basedir, "private")
        os.mkdir(private_dir)
        reactor = object()
        cli_config = create_node.CreateNodeOptions()
        cli_config.update({"basedir": basedir,
                           "tor-launch": False,
                           })
        cli_config.stdout = StringIO()
        protocol = object()
        connect_to_tor = mock.Mock(return_value=defer.succeed(("goodport",
                                                               protocol)))
        txtorcon = mock.Mock()
        ehs = mock.Mock()
        ehs.private_key = "privkey"
        ehs.hostname = "ONION.onion"
        txtorcon.EphemeralHiddenService = mock.Mock(return_value=ehs)
        ehs.add_to_tor = mock.Mock(return_value=defer.succeed(None))
        ehs.remove_from_tor = mock.Mock(return_value=defer.succeed(None))

        with mock_txtorcon(txtorcon):
            with mock.patch("allmydata.util.tor_provider._connect_to_tor",
                            connect_to_tor):
                with mock.patch("allmydata.util.tor_provider.allocate_tcp_port",
                                return_value=999999):
                    d = tor_provider.create_onion(reactor, cli_config)
        tahoe_config_tor, tor_port, tor_location = self.successResultOf(d)

        connect_to_tor.assert_called_with(reactor, cli_config)
        txtorcon.EphemeralHiddenService.assert_called_with("999999 127.0.0.1:3457")
        ehs.add_to_tor.assert_called_with(protocol)
        ehs.remove_from_tor.assert_called_with(protocol)

        expected = {"control.port": "goodport",
                    "onion": "true",
                    "onion.local_port": "999999",
                    "onion.external_port": "3457",
                    "onion.private_key_file": "private/tor_onion.privkey",
                    }
        self.assertEqual(tahoe_config_tor, expected)
        self.assertEqual(tor_port, "tcp:127.0.0.1:999999")
        self.assertEqual(tor_location, "tor:ONION.onion:3457")
        fn = os.path.join(basedir, tahoe_config_tor["onion.private_key_file"])
        with open(fn, "rb") as f:
            privkey = f.read()
        self.assertEqual(privkey, "privkey")

_None = object()
class FakeConfig(dict):
    def get_config(self, section, option, default=_None, boolean=False):
        if section != "tor":
            raise ValueError(section)
        value = self.get(option, default)
        if value is _None:
            raise KeyError
        return value

class Provider(unittest.TestCase):
    def test_build(self):
        tor_provider.Provider("basedir", FakeConfig())

    def test_handler_disabled(self):
        p = tor_provider.Provider("basedir", FakeConfig(enabled=False))
        self.assertEqual(p.get_tor_handler("reactor"), None)

    def test_handler_no_tor(self):
        with mock_tor(None):
            p = tor_provider.Provider("basedir", FakeConfig())
        self.assertEqual(p.get_tor_handler("reactor"), None)

    def test_handler_launch_no_txtorcon(self):
        with mock_txtorcon(None):
            p = tor_provider.Provider("basedir", FakeConfig(launch=True))
        self.assertEqual(p.get_tor_handler("reactor"), None)

    def test_handler_launch(self):
        reactor = object()
        tor = mock.Mock()
        handler = object()
        tor.control_endpoint_maker = mock.Mock(return_value=handler)
        with mock_tor(tor):
            p = tor_provider.Provider("basedir", FakeConfig(launch=True))
        h = p.get_tor_handler(reactor)
        self.assertIs(h, handler)
        tor.control_endpoint_maker.assert_called_with(p._make_control_endpoint)

    def ELSE_do_test_launch(self, tor_executable):
        basedir = self.mktemp()
        os.mkdir(basedir)
        os.mkdir(os.path.join(basedir, "private"))
        reactor = object()
        cli_config = {"basedir": basedir,
                      "tor-launch": True,
                      "tor-executable": tor_executable,
                      }
        txtorcon = mock.Mock()
        tpp = mock.Mock
        tpp.tor_protocol = mock.Mock()
        txtorcon.launch_tor = mock.Mock(return_value=tpp)
        ehs = mock.Mock()
        ehs.private_key = "privkey"
        ehs.hostname = "ONION.onion"
        txtorcon.EphemeralHiddenService = mock.Mock(return_value=ehs)
        ehs.add_to_tor = mock.Mock(return_value=defer.succeed(None))
        ehs.remove_from_tor = mock.Mock(return_value=defer.succeed(None))

        with mock_txtorcon(txtorcon):
            with mock.patch("allmydata.util.tor_provider.allocate_tcp_port",
                            return_value=999999):
                d = tor_provider.create_onion(reactor, cli_config)
        ehs.add_to_tor.assert_called_with(tpp.tor_protocol)
        ehs.remove_from_tor.assert_called_with(tpp.tor_protocol)
        tahoe_config_tor, tor_port, tor_location = self.successResultOf(d)
        expected = {"onion.local_port": "999999",
                    "onion.external_port": "3457",
                    "onion.private_key_file": "private/tor_onion.privkey",
                    "onion": "true",
                    "launch": "true",
                    }
        if tor_executable:
            expected["tor.executable"] = tor_executable
        self.assertEqual(tahoe_config_tor, expected)
        self.assertEqual(tor_port, "tcp:127.0.0.1:999999")
        self.assertEqual(tor_location, "tor:ONION.onion:3457")
        fn = os.path.join(basedir, tahoe_config_tor["onion.private_key_file"])
        with open(fn, "rb") as f:
            privkey = f.read()
        self.assertEqual(privkey, "privkey")

    def test_handler_socks_endpoint(self):
        tor = mock.Mock()
        handler = object()
        tor.socks_endpoint = mock.Mock(return_value=handler)
        ep = object()
        cfs = mock.Mock(return_value=ep)
        reactor = object()

        with mock_tor(tor):
            p = tor_provider.Provider("basedir",
                                      FakeConfig(**{"socks.port": "ep_desc"}))
            with mock.patch("allmydata.util.tor_provider.clientFromString", cfs):
                h = p.get_tor_handler(reactor)
        cfs.assert_called_with(reactor, "ep_desc")
        tor.socks_endpoint.assert_called_with(ep)
        self.assertIs(h, handler)

    def test_handler_control_endpoint(self):
        tor = mock.Mock()
        handler = object()
        tor.control_endpoint = mock.Mock(return_value=handler)
        ep = object()
        cfs = mock.Mock(return_value=ep)
        reactor = object()

        with mock_tor(tor):
            p = tor_provider.Provider("basedir",
                                      FakeConfig(**{"control.port": "ep_desc"}))
            with mock.patch("allmydata.util.tor_provider.clientFromString", cfs):
                h = p.get_tor_handler(reactor)
        self.assertIs(h, handler)
        cfs.assert_called_with(reactor, "ep_desc")
        tor.control_endpoint.assert_called_with(ep)

    def test_handler_default(self):
        tor = mock.Mock()
        handler = object()
        tor.default_socks = mock.Mock(return_value=handler)
        reactor = object()

        with mock_tor(tor):
            p = tor_provider.Provider("basedir", FakeConfig())
            h = p.get_tor_handler(reactor)
        self.assertIs(h, handler)
        tor.default_socks.assert_called_with()

class CheckOnionConfig(unittest.TestCase):
    def test_default(self):
        # default config doesn't start an onion service, so it should be
        # happy both with and without txtorcon

        p = tor_provider.Provider("basedir", FakeConfig())
        p.check_onion_config()

        with mock_txtorcon(None):
            p = tor_provider.Provider("basedir", FakeConfig())
            p.check_onion_config()

    def test_no_txtorcon(self):
        with mock_txtorcon(None):
            p = tor_provider.Provider("basedir", FakeConfig(onion=True))
            e = self.assertRaises(ValueError, p.check_onion_config)
            self.assertEqual(str(e), "Cannot create onion without txtorcon. "
                             "Please 'pip install tahoe-lafs[tor]' to fix.")

    def test_no_launch_no_control(self):
        p = tor_provider.Provider("basedir", FakeConfig(onion=True))
        e = self.assertRaises(ValueError, p.check_onion_config)
        self.assertEqual(str(e), "[tor] onion = true, but we have neither "
                         "launch=true nor control.port=")

    def test_missing_keys(self):
        p = tor_provider.Provider("basedir", FakeConfig(onion=True,
                                                        launch=True))
        e = self.assertRaises(ValueError, p.check_onion_config)
        self.assertEqual(str(e), "[tor] onion = true, "
                         "but onion.local_port= is missing")

        p = tor_provider.Provider("basedir",
                                  FakeConfig(onion=True, launch=True,
                                             **{"onion.local_port": "x",
                                                }))
        e = self.assertRaises(ValueError, p.check_onion_config)
        self.assertEqual(str(e), "[tor] onion = true, "
                         "but onion.external_port= is missing")

        p = tor_provider.Provider("basedir",
                                  FakeConfig(onion=True, launch=True,
                                             **{"onion.local_port": "x",
                                                "onion.external_port": "y",
                                                }))
        e = self.assertRaises(ValueError, p.check_onion_config)
        self.assertEqual(str(e), "[tor] onion = true, "
                         "but onion.private_key_file= is missing")

    def test_ok(self):
        p = tor_provider.Provider("basedir",
                                  FakeConfig(onion=True, launch=True,
                                             **{"onion.local_port": "x",
                                                "onion.external_port": "y",
                                                "onion.private_key_file": "z",
                                                }))
        p.check_onion_config()
