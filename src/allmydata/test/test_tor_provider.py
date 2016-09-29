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

class Connect(unittest.TestCase):
    def test_try(self):
        reactor = object()
        txtorcon = mock.Mock()
        tor_state = object()
        d = defer.succeed(tor_state)
        txtorcon.build_tor_connection = mock.Mock(return_value=d)
        ep = object()
        stdout = StringIO()
        with mock_txtorcon(txtorcon):
            with mock.patch("allmydata.util.tor_provider.clientFromString",
                            return_value=ep) as cfs:
                d = tor_provider._try_to_connect(reactor, "desc", stdout)
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
        with mock_txtorcon(txtorcon):
            with mock.patch("allmydata.util.tor_provider.clientFromString",
                            return_value=ep) as cfs:
                d = tor_provider._try_to_connect(reactor, "desc", stdout)
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
        with mock_txtorcon(txtorcon):
            with mock.patch("allmydata.util.tor_provider.clientFromString",
                            return_value=ep) as cfs:
                d = tor_provider._try_to_connect(reactor, "desc", stdout)
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

    def test_launch(self):
        return self._do_test_launch(None)
    def test_launch_executable(self):
        return self._do_test_launch("mytor")

    def test_control_endpoint_default(self):
        basedir = self.mktemp()
        os.mkdir(basedir)
        os.mkdir(os.path.join(basedir, "private"))
        reactor = object()
        cli_config = create_node.CreateNodeOptions()
        cli_config.update({"basedir": basedir,
                           "tor-launch": False,
                           "tor-control-endpoint": None,
                            })
        cli_config.stdout = StringIO()
        tor_state = mock.Mock()
        tor_state.protocol = mock.Mock()
        tried = []
        def _try_to_connect(reactor, port, stdout):
            tried.append( (reactor, port, stdout) )
            if port == "tcp:127.0.0.1:9051": # second one on the list
                return defer.succeed(tor_state)
            return defer.succeed(None)
        txtorcon = mock.Mock()
        txtorcon.launch_tor = mock.Mock()
        ehs = mock.Mock()
        ehs.private_key = "privkey"
        ehs.hostname = "ONION.onion"
        txtorcon.EphemeralHiddenService = mock.Mock(return_value=ehs)
        ehs.add_to_tor = mock.Mock(return_value=defer.succeed(None))
        ehs.remove_from_tor = mock.Mock(return_value=defer.succeed(None))

        with mock_txtorcon(txtorcon):
            with mock.patch("allmydata.util.tor_provider._try_to_connect",
                            _try_to_connect):
                with mock.patch("allmydata.util.tor_provider.allocate_tcp_port",
                                return_value=999999):
                    d = tor_provider.create_onion(reactor, cli_config)

        ehs.add_to_tor.assert_called_with(tor_state.protocol)
        ehs.remove_from_tor.assert_called_with(tor_state.protocol)

        tahoe_config_tor, tor_port, tor_location = self.successResultOf(d)
        self.assertEqual(tahoe_config_tor,
                         {"onion.local_port": "999999",
                          "onion.external_port": "3457",
                          "onion.private_key_file": "private/tor_onion.privkey",
                          "onion": "true",
                          "control.port": "tcp:127.0.0.1:9051",
                          })
        self.assertEqual(tor_port, "tcp:127.0.0.1:999999")
        self.assertEqual(tor_location, "tor:ONION.onion:3457")
        fn = os.path.join(basedir, tahoe_config_tor["onion.private_key_file"])
        with open(fn, "rb") as f:
            privkey = f.read()
        self.assertEqual(privkey, "privkey")

