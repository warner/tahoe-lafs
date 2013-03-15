
import os.path
from twisted.trial import unittest
from cStringIO import StringIO
import urllib, re, sys
import simplejson

from mock import patch, Mock, call

from allmydata.util import fileutil, hashutil, base32, keyutil
from allmydata import uri
from allmydata.immutable import upload
from allmydata.interfaces import MDMF_VERSION, SDMF_VERSION
from allmydata.mutable.publish import MutableData
from allmydata.dirnode import normalize
from allmydata.scripts.common_http import socket_error
import allmydata.scripts.common_http
from pycryptopp.publickey import ed25519

# Test that the scripts can be imported.
from allmydata.scripts import create_node, debug, keygen, startstop_node, \
    tahoe_add_alias, tahoe_backup, tahoe_check, tahoe_cp, tahoe_get, tahoe_ls, \
    tahoe_manifest, tahoe_mkdir, tahoe_mv, tahoe_put, tahoe_unlink, tahoe_webopen
_hush_pyflakes = [create_node, debug, keygen, startstop_node,
    tahoe_add_alias, tahoe_backup, tahoe_check, tahoe_cp, tahoe_get, tahoe_ls,
    tahoe_manifest, tahoe_mkdir, tahoe_mv, tahoe_put, tahoe_unlink, tahoe_webopen]

from allmydata.scripts import common
from allmydata.scripts.common import DEFAULT_ALIAS, get_aliases, get_alias, \
     DefaultAliasMarker

from allmydata.scripts import cli, debug, runner, backupdb
from allmydata.test.common_util import StallMixin, ReallyEqualMixin
from allmydata.test.no_network import GridTestMixin
from twisted.internet import threads # CLI tests use deferToThread
from twisted.internet import defer # List uses a DeferredList in one place.
from twisted.python import usage

from allmydata.util.assertutil import precondition
from allmydata.util.encodingutil import listdir_unicode, unicode_platform, \
    quote_output, get_io_encoding, get_filesystem_encoding, \
    unicode_to_output, unicode_to_argv, to_str
from allmydata.util.fileutil import abspath_expanduser_unicode

timeout = 480 # deep_check takes 360s on Zandr's linksys box, others take > 240s


class CLITestMixin(ReallyEqualMixin):
    def do_cli(self, verb, *args, **kwargs):
        nodeargs = [
            "--node-directory", self.get_clientdir(),
            ]
        argv = [verb] + nodeargs + list(args)
        stdin = kwargs.get("stdin", "")
        stdout, stderr = StringIO(), StringIO()
        d = threads.deferToThread(runner.runner, argv, run_by_human=False,
                                  stdin=StringIO(stdin),
                                  stdout=stdout, stderr=stderr)
        def _done(rc):
            return rc, stdout.getvalue(), stderr.getvalue()
        d.addCallback(_done)
        return d

    def skip_if_cannot_represent_filename(self, u):
        precondition(isinstance(u, unicode))

        enc = get_filesystem_encoding()
        if not unicode_platform():
            try:
                u.encode(enc)
            except UnicodeEncodeError:
                raise unittest.SkipTest("A non-ASCII filename could not be encoded on this platform.")


class CLI(CLITestMixin, unittest.TestCase):
    # this test case only looks at argument-processing and simple stuff.
    def test_options(self):
        fileutil.rm_dir("cli/test_options")
        fileutil.make_dirs("cli/test_options")
        fileutil.make_dirs("cli/test_options/private")
        fileutil.write("cli/test_options/node.url", "http://localhost:8080/\n")
        filenode_uri = uri.WriteableSSKFileURI(writekey="\x00"*16,
                                               fingerprint="\x00"*32)
        private_uri = uri.DirectoryURI(filenode_uri).to_string()
        fileutil.write("cli/test_options/private/root_dir.cap", private_uri + "\n")
        o = cli.ListOptions()
        o.parseOptions(["--node-directory", "cli/test_options"])
        self.failUnlessReallyEqual(o['node-url'], "http://localhost:8080/")
        self.failUnlessReallyEqual(o.aliases[DEFAULT_ALIAS], private_uri)
        self.failUnlessReallyEqual(o.where, u"")

        o = cli.ListOptions()
        o.parseOptions(["--node-directory", "cli/test_options",
                        "--node-url", "http://example.org:8111/"])
        self.failUnlessReallyEqual(o['node-url'], "http://example.org:8111/")
        self.failUnlessReallyEqual(o.aliases[DEFAULT_ALIAS], private_uri)
        self.failUnlessReallyEqual(o.where, u"")

        o = cli.ListOptions()
        o.parseOptions(["--node-directory", "cli/test_options",
                        "--dir-cap", "root"])
        self.failUnlessReallyEqual(o['node-url'], "http://localhost:8080/")
        self.failUnlessReallyEqual(o.aliases[DEFAULT_ALIAS], "root")
        self.failUnlessReallyEqual(o.where, u"")

        o = cli.ListOptions()
        other_filenode_uri = uri.WriteableSSKFileURI(writekey="\x11"*16,
                                                     fingerprint="\x11"*32)
        other_uri = uri.DirectoryURI(other_filenode_uri).to_string()
        o.parseOptions(["--node-directory", "cli/test_options",
                        "--dir-cap", other_uri])
        self.failUnlessReallyEqual(o['node-url'], "http://localhost:8080/")
        self.failUnlessReallyEqual(o.aliases[DEFAULT_ALIAS], other_uri)
        self.failUnlessReallyEqual(o.where, u"")

        o = cli.ListOptions()
        o.parseOptions(["--node-directory", "cli/test_options",
                        "--dir-cap", other_uri, "subdir"])
        self.failUnlessReallyEqual(o['node-url'], "http://localhost:8080/")
        self.failUnlessReallyEqual(o.aliases[DEFAULT_ALIAS], other_uri)
        self.failUnlessReallyEqual(o.where, u"subdir")

        o = cli.ListOptions()
        self.failUnlessRaises(usage.UsageError,
                              o.parseOptions,
                              ["--node-directory", "cli/test_options",
                               "--node-url", "NOT-A-URL"])

        o = cli.ListOptions()
        o.parseOptions(["--node-directory", "cli/test_options",
                        "--node-url", "http://localhost:8080"])
        self.failUnlessReallyEqual(o["node-url"], "http://localhost:8080/")

        o = cli.ListOptions()
        o.parseOptions(["--node-directory", "cli/test_options",
                        "--node-url", "https://localhost/"])
        self.failUnlessReallyEqual(o["node-url"], "https://localhost/")

    def _dump_cap(self, *args):
        config = debug.DumpCapOptions()
        config.stdout,config.stderr = StringIO(), StringIO()
        config.parseOptions(args)
        debug.dump_cap(config)
        self.failIf(config.stderr.getvalue())
        output = config.stdout.getvalue()
        return output

    def test_dump_cap_chk(self):
        key = "\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b\x0c\x0d\x0e\x0f"
        uri_extension_hash = hashutil.uri_extension_hash("stuff")
        needed_shares = 25
        total_shares = 100
        size = 1234
        u = uri.CHKFileURI(key=key,
                           uri_extension_hash=uri_extension_hash,
                           needed_shares=needed_shares,
                           total_shares=total_shares,
                           size=size)
        output = self._dump_cap(u.to_string())
        self.failUnless("CHK File:" in output, output)
        self.failUnless("key: aaaqeayeaudaocajbifqydiob4" in output, output)
        self.failUnless("UEB hash: nf3nimquen7aeqm36ekgxomalstenpkvsdmf6fplj7swdatbv5oa" in output, output)
        self.failUnless("size: 1234" in output, output)
        self.failUnless("k/N: 25/100" in output, output)
        self.failUnless("storage index: hdis5iaveku6lnlaiccydyid7q" in output, output)

        output = self._dump_cap("--client-secret", "5s33nk3qpvnj2fw3z4mnm2y6fa",
                                u.to_string())
        self.failUnless("client renewal secret: znxmki5zdibb5qlt46xbdvk2t55j7hibejq3i5ijyurkr6m6jkhq" in output, output)

        output = self._dump_cap(u.get_verify_cap().to_string())
        self.failIf("key: " in output, output)
        self.failUnless("UEB hash: nf3nimquen7aeqm36ekgxomalstenpkvsdmf6fplj7swdatbv5oa" in output, output)
        self.failUnless("size: 1234" in output, output)
        self.failUnless("k/N: 25/100" in output, output)
        self.failUnless("storage index: hdis5iaveku6lnlaiccydyid7q" in output, output)

        prefixed_u = "http://127.0.0.1/uri/%s" % urllib.quote(u.to_string())
        output = self._dump_cap(prefixed_u)
        self.failUnless("CHK File:" in output, output)
        self.failUnless("key: aaaqeayeaudaocajbifqydiob4" in output, output)
        self.failUnless("UEB hash: nf3nimquen7aeqm36ekgxomalstenpkvsdmf6fplj7swdatbv5oa" in output, output)
        self.failUnless("size: 1234" in output, output)
        self.failUnless("k/N: 25/100" in output, output)
        self.failUnless("storage index: hdis5iaveku6lnlaiccydyid7q" in output, output)

    def test_dump_cap_lit(self):
        u = uri.LiteralFileURI("this is some data")
        output = self._dump_cap(u.to_string())
        self.failUnless("Literal File URI:" in output, output)
        self.failUnless("data: 'this is some data'" in output, output)

    def test_dump_cap_sdmf(self):
        writekey = "\x01" * 16
        fingerprint = "\xfe" * 32
        u = uri.WriteableSSKFileURI(writekey, fingerprint)

        output = self._dump_cap(u.to_string())
        self.failUnless("SDMF Writeable URI:" in output, output)
        self.failUnless("writekey: aeaqcaibaeaqcaibaeaqcaibae" in output, output)
        self.failUnless("readkey: nvgh5vj2ekzzkim5fgtb4gey5y" in output, output)
        self.failUnless("storage index: nt4fwemuw7flestsezvo2eveke" in output, output)
        self.failUnless("fingerprint: 737p57x6737p57x6737p57x6737p57x6737p57x6737p57x6737a" in output, output)

        output = self._dump_cap("--client-secret", "5s33nk3qpvnj2fw3z4mnm2y6fa",
                                u.to_string())
        self.failUnless("file renewal secret: arpszxzc2t6kb4okkg7sp765xgkni5z7caavj7lta73vmtymjlxq" in output, output)

        fileutil.make_dirs("cli/test_dump_cap/private")
        fileutil.write("cli/test_dump_cap/private/secret", "5s33nk3qpvnj2fw3z4mnm2y6fa\n")
        output = self._dump_cap("--client-dir", "cli/test_dump_cap",
                                u.to_string())
        self.failUnless("file renewal secret: arpszxzc2t6kb4okkg7sp765xgkni5z7caavj7lta73vmtymjlxq" in output, output)

        output = self._dump_cap("--client-dir", "cli/test_dump_cap_BOGUS",
                                u.to_string())
        self.failIf("file renewal secret:" in output, output)

        output = self._dump_cap("--nodeid", "tqc35esocrvejvg4mablt6aowg6tl43j",
                                u.to_string())
        self.failUnless("write_enabler: mgcavriox2wlb5eer26unwy5cw56elh3sjweffckkmivvsxtaknq" in output, output)
        self.failIf("file renewal secret:" in output, output)

        output = self._dump_cap("--nodeid", "tqc35esocrvejvg4mablt6aowg6tl43j",
                                "--client-secret", "5s33nk3qpvnj2fw3z4mnm2y6fa",
                                u.to_string())
        self.failUnless("write_enabler: mgcavriox2wlb5eer26unwy5cw56elh3sjweffckkmivvsxtaknq" in output, output)
        self.failUnless("file renewal secret: arpszxzc2t6kb4okkg7sp765xgkni5z7caavj7lta73vmtymjlxq" in output, output)
        self.failUnless("lease renewal secret: 7pjtaumrb7znzkkbvekkmuwpqfjyfyamznfz4bwwvmh4nw33lorq" in output, output)

        u = u.get_readonly()
        output = self._dump_cap(u.to_string())
        self.failUnless("SDMF Read-only URI:" in output, output)
        self.failUnless("readkey: nvgh5vj2ekzzkim5fgtb4gey5y" in output, output)
        self.failUnless("storage index: nt4fwemuw7flestsezvo2eveke" in output, output)
        self.failUnless("fingerprint: 737p57x6737p57x6737p57x6737p57x6737p57x6737p57x6737a" in output, output)

        u = u.get_verify_cap()
        output = self._dump_cap(u.to_string())
        self.failUnless("SDMF Verifier URI:" in output, output)
        self.failUnless("storage index: nt4fwemuw7flestsezvo2eveke" in output, output)
        self.failUnless("fingerprint: 737p57x6737p57x6737p57x6737p57x6737p57x6737p57x6737a" in output, output)

    def test_dump_cap_mdmf(self):
        writekey = "\x01" * 16
        fingerprint = "\xfe" * 32
        u = uri.WriteableMDMFFileURI(writekey, fingerprint)

        output = self._dump_cap(u.to_string())
        self.failUnless("MDMF Writeable URI:" in output, output)
        self.failUnless("writekey: aeaqcaibaeaqcaibaeaqcaibae" in output, output)
        self.failUnless("readkey: nvgh5vj2ekzzkim5fgtb4gey5y" in output, output)
        self.failUnless("storage index: nt4fwemuw7flestsezvo2eveke" in output, output)
        self.failUnless("fingerprint: 737p57x6737p57x6737p57x6737p57x6737p57x6737p57x6737a" in output, output)

        output = self._dump_cap("--client-secret", "5s33nk3qpvnj2fw3z4mnm2y6fa",
                                u.to_string())
        self.failUnless("file renewal secret: arpszxzc2t6kb4okkg7sp765xgkni5z7caavj7lta73vmtymjlxq" in output, output)

        fileutil.make_dirs("cli/test_dump_cap/private")
        fileutil.write("cli/test_dump_cap/private/secret", "5s33nk3qpvnj2fw3z4mnm2y6fa\n")
        output = self._dump_cap("--client-dir", "cli/test_dump_cap",
                                u.to_string())
        self.failUnless("file renewal secret: arpszxzc2t6kb4okkg7sp765xgkni5z7caavj7lta73vmtymjlxq" in output, output)

        output = self._dump_cap("--client-dir", "cli/test_dump_cap_BOGUS",
                                u.to_string())
        self.failIf("file renewal secret:" in output, output)

        output = self._dump_cap("--nodeid", "tqc35esocrvejvg4mablt6aowg6tl43j",
                                u.to_string())
        self.failUnless("write_enabler: mgcavriox2wlb5eer26unwy5cw56elh3sjweffckkmivvsxtaknq" in output, output)
        self.failIf("file renewal secret:" in output, output)

        output = self._dump_cap("--nodeid", "tqc35esocrvejvg4mablt6aowg6tl43j",
                                "--client-secret", "5s33nk3qpvnj2fw3z4mnm2y6fa",
                                u.to_string())
        self.failUnless("write_enabler: mgcavriox2wlb5eer26unwy5cw56elh3sjweffckkmivvsxtaknq" in output, output)
        self.failUnless("file renewal secret: arpszxzc2t6kb4okkg7sp765xgkni5z7caavj7lta73vmtymjlxq" in output, output)
        self.failUnless("lease renewal secret: 7pjtaumrb7znzkkbvekkmuwpqfjyfyamznfz4bwwvmh4nw33lorq" in output, output)

        u = u.get_readonly()
        output = self._dump_cap(u.to_string())
        self.failUnless("MDMF Read-only URI:" in output, output)
        self.failUnless("readkey: nvgh5vj2ekzzkim5fgtb4gey5y" in output, output)
        self.failUnless("storage index: nt4fwemuw7flestsezvo2eveke" in output, output)
        self.failUnless("fingerprint: 737p57x6737p57x6737p57x6737p57x6737p57x6737p57x6737a" in output, output)

        u = u.get_verify_cap()
        output = self._dump_cap(u.to_string())
        self.failUnless("MDMF Verifier URI:" in output, output)
        self.failUnless("storage index: nt4fwemuw7flestsezvo2eveke" in output, output)
        self.failUnless("fingerprint: 737p57x6737p57x6737p57x6737p57x6737p57x6737p57x6737a" in output, output)


    def test_dump_cap_chk_directory(self):
        key = "\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b\x0c\x0d\x0e\x0f"
        uri_extension_hash = hashutil.uri_extension_hash("stuff")
        needed_shares = 25
        total_shares = 100
        size = 1234
        u1 = uri.CHKFileURI(key=key,
                            uri_extension_hash=uri_extension_hash,
                            needed_shares=needed_shares,
                            total_shares=total_shares,
                            size=size)
        u = uri.ImmutableDirectoryURI(u1)

        output = self._dump_cap(u.to_string())
        self.failUnless("CHK Directory URI:" in output, output)
        self.failUnless("key: aaaqeayeaudaocajbifqydiob4" in output, output)
        self.failUnless("UEB hash: nf3nimquen7aeqm36ekgxomalstenpkvsdmf6fplj7swdatbv5oa" in output, output)
        self.failUnless("size: 1234" in output, output)
        self.failUnless("k/N: 25/100" in output, output)
        self.failUnless("storage index: hdis5iaveku6lnlaiccydyid7q" in output, output)

        output = self._dump_cap("--client-secret", "5s33nk3qpvnj2fw3z4mnm2y6fa",
                                u.to_string())
        self.failUnless("file renewal secret: csrvkjgomkyyyil5yo4yk5np37p6oa2ve2hg6xmk2dy7kaxsu6xq" in output, output)

        u = u.get_verify_cap()
        output = self._dump_cap(u.to_string())
        self.failUnless("CHK Directory Verifier URI:" in output, output)
        self.failIf("key: " in output, output)
        self.failUnless("UEB hash: nf3nimquen7aeqm36ekgxomalstenpkvsdmf6fplj7swdatbv5oa" in output, output)
        self.failUnless("size: 1234" in output, output)
        self.failUnless("k/N: 25/100" in output, output)
        self.failUnless("storage index: hdis5iaveku6lnlaiccydyid7q" in output, output)

    def test_dump_cap_sdmf_directory(self):
        writekey = "\x01" * 16
        fingerprint = "\xfe" * 32
        u1 = uri.WriteableSSKFileURI(writekey, fingerprint)
        u = uri.DirectoryURI(u1)

        output = self._dump_cap(u.to_string())
        self.failUnless("Directory Writeable URI:" in output, output)
        self.failUnless("writekey: aeaqcaibaeaqcaibaeaqcaibae" in output,
                        output)
        self.failUnless("readkey: nvgh5vj2ekzzkim5fgtb4gey5y" in output, output)
        self.failUnless("storage index: nt4fwemuw7flestsezvo2eveke" in output,
                        output)
        self.failUnless("fingerprint: 737p57x6737p57x6737p57x6737p57x6737p57x6737p57x6737a" in output, output)

        output = self._dump_cap("--client-secret", "5s33nk3qpvnj2fw3z4mnm2y6fa",
                                u.to_string())
        self.failUnless("file renewal secret: arpszxzc2t6kb4okkg7sp765xgkni5z7caavj7lta73vmtymjlxq" in output, output)

        output = self._dump_cap("--nodeid", "tqc35esocrvejvg4mablt6aowg6tl43j",
                                u.to_string())
        self.failUnless("write_enabler: mgcavriox2wlb5eer26unwy5cw56elh3sjweffckkmivvsxtaknq" in output, output)
        self.failIf("file renewal secret:" in output, output)

        output = self._dump_cap("--nodeid", "tqc35esocrvejvg4mablt6aowg6tl43j",
                                "--client-secret", "5s33nk3qpvnj2fw3z4mnm2y6fa",
                                u.to_string())
        self.failUnless("write_enabler: mgcavriox2wlb5eer26unwy5cw56elh3sjweffckkmivvsxtaknq" in output, output)
        self.failUnless("file renewal secret: arpszxzc2t6kb4okkg7sp765xgkni5z7caavj7lta73vmtymjlxq" in output, output)
        self.failUnless("lease renewal secret: 7pjtaumrb7znzkkbvekkmuwpqfjyfyamznfz4bwwvmh4nw33lorq" in output, output)

        u = u.get_readonly()
        output = self._dump_cap(u.to_string())
        self.failUnless("Directory Read-only URI:" in output, output)
        self.failUnless("readkey: nvgh5vj2ekzzkim5fgtb4gey5y" in output, output)
        self.failUnless("storage index: nt4fwemuw7flestsezvo2eveke" in output, output)
        self.failUnless("fingerprint: 737p57x6737p57x6737p57x6737p57x6737p57x6737p57x6737a" in output, output)

        u = u.get_verify_cap()
        output = self._dump_cap(u.to_string())
        self.failUnless("Directory Verifier URI:" in output, output)
        self.failUnless("storage index: nt4fwemuw7flestsezvo2eveke" in output, output)
        self.failUnless("fingerprint: 737p57x6737p57x6737p57x6737p57x6737p57x6737p57x6737a" in output, output)

    def test_dump_cap_mdmf_directory(self):
        writekey = "\x01" * 16
        fingerprint = "\xfe" * 32
        u1 = uri.WriteableMDMFFileURI(writekey, fingerprint)
        u = uri.MDMFDirectoryURI(u1)

        output = self._dump_cap(u.to_string())
        self.failUnless("Directory Writeable URI:" in output, output)
        self.failUnless("writekey: aeaqcaibaeaqcaibaeaqcaibae" in output,
                        output)
        self.failUnless("readkey: nvgh5vj2ekzzkim5fgtb4gey5y" in output, output)
        self.failUnless("storage index: nt4fwemuw7flestsezvo2eveke" in output,
                        output)
        self.failUnless("fingerprint: 737p57x6737p57x6737p57x6737p57x6737p57x6737p57x6737a" in output, output)

        output = self._dump_cap("--client-secret", "5s33nk3qpvnj2fw3z4mnm2y6fa",
                                u.to_string())
        self.failUnless("file renewal secret: arpszxzc2t6kb4okkg7sp765xgkni5z7caavj7lta73vmtymjlxq" in output, output)

        output = self._dump_cap("--nodeid", "tqc35esocrvejvg4mablt6aowg6tl43j",
                                u.to_string())
        self.failUnless("write_enabler: mgcavriox2wlb5eer26unwy5cw56elh3sjweffckkmivvsxtaknq" in output, output)
        self.failIf("file renewal secret:" in output, output)

        output = self._dump_cap("--nodeid", "tqc35esocrvejvg4mablt6aowg6tl43j",
                                "--client-secret", "5s33nk3qpvnj2fw3z4mnm2y6fa",
                                u.to_string())
        self.failUnless("write_enabler: mgcavriox2wlb5eer26unwy5cw56elh3sjweffckkmivvsxtaknq" in output, output)
        self.failUnless("file renewal secret: arpszxzc2t6kb4okkg7sp765xgkni5z7caavj7lta73vmtymjlxq" in output, output)
        self.failUnless("lease renewal secret: 7pjtaumrb7znzkkbvekkmuwpqfjyfyamznfz4bwwvmh4nw33lorq" in output, output)

        u = u.get_readonly()
        output = self._dump_cap(u.to_string())
        self.failUnless("Directory Read-only URI:" in output, output)
        self.failUnless("readkey: nvgh5vj2ekzzkim5fgtb4gey5y" in output, output)
        self.failUnless("storage index: nt4fwemuw7flestsezvo2eveke" in output, output)
        self.failUnless("fingerprint: 737p57x6737p57x6737p57x6737p57x6737p57x6737p57x6737a" in output, output)

        u = u.get_verify_cap()
        output = self._dump_cap(u.to_string())
        self.failUnless("Directory Verifier URI:" in output, output)
        self.failUnless("storage index: nt4fwemuw7flestsezvo2eveke" in output, output)
        self.failUnless("fingerprint: 737p57x6737p57x6737p57x6737p57x6737p57x6737p57x6737a" in output, output)


    def _catalog_shares(self, *basedirs):
        o = debug.CatalogSharesOptions()
        o.stdout,o.stderr = StringIO(), StringIO()
        args = list(basedirs)
        o.parseOptions(args)
        debug.catalog_shares(o)
        out = o.stdout.getvalue()
        err = o.stderr.getvalue()
        return out, err

    def test_catalog_shares_error(self):
        nodedir1 = "cli/test_catalog_shares/node1"
        sharedir = os.path.join(nodedir1, "storage", "shares", "mq", "mqfblse6m5a6dh45isu2cg7oji")
        fileutil.make_dirs(sharedir)
        fileutil.write("cli/test_catalog_shares/node1/storage/shares/mq/not-a-dir", "")
        # write a bogus share that looks a little bit like CHK
        fileutil.write(os.path.join(sharedir, "8"),
                       "\x00\x00\x00\x01" + "\xff" * 200) # this triggers an assert

        nodedir2 = "cli/test_catalog_shares/node2"
        fileutil.make_dirs(nodedir2)
        fileutil.write("cli/test_catalog_shares/node1/storage/shares/not-a-dir", "")

        # now make sure that the 'catalog-shares' commands survives the error
        out, err = self._catalog_shares(nodedir1, nodedir2)
        self.failUnlessReallyEqual(out, "", out)
        self.failUnless("Error processing " in err,
                        "didn't see 'error processing' in '%s'" % err)
        #self.failUnless(nodedir1 in err,
        #                "didn't see '%s' in '%s'" % (nodedir1, err))
        # windows mangles the path, and os.path.join isn't enough to make
        # up for it, so just look for individual strings
        self.failUnless("node1" in err,
                        "didn't see 'node1' in '%s'" % err)
        self.failUnless("mqfblse6m5a6dh45isu2cg7oji" in err,
                        "didn't see 'mqfblse6m5a6dh45isu2cg7oji' in '%s'" % err)

    def test_alias(self):
        aliases = {"tahoe": "TA",
                   "work": "WA",
                   "c": "CA"}
        def ga1(path):
            return get_alias(aliases, path, u"tahoe")
        uses_lettercolon = common.platform_uses_lettercolon_drivename()
        self.failUnlessReallyEqual(ga1(u"bare"), ("TA", "bare"))
        self.failUnlessReallyEqual(ga1(u"baredir/file"), ("TA", "baredir/file"))
        self.failUnlessReallyEqual(ga1(u"baredir/file:7"), ("TA", "baredir/file:7"))
        self.failUnlessReallyEqual(ga1(u"tahoe:"), ("TA", ""))
        self.failUnlessReallyEqual(ga1(u"tahoe:file"), ("TA", "file"))
        self.failUnlessReallyEqual(ga1(u"tahoe:dir/file"), ("TA", "dir/file"))
        self.failUnlessReallyEqual(ga1(u"work:"), ("WA", ""))
        self.failUnlessReallyEqual(ga1(u"work:file"), ("WA", "file"))
        self.failUnlessReallyEqual(ga1(u"work:dir/file"), ("WA", "dir/file"))
        # default != None means we really expect a tahoe path, regardless of
        # whether we're on windows or not. This is what 'tahoe get' uses.
        self.failUnlessReallyEqual(ga1(u"c:"), ("CA", ""))
        self.failUnlessReallyEqual(ga1(u"c:file"), ("CA", "file"))
        self.failUnlessReallyEqual(ga1(u"c:dir/file"), ("CA", "dir/file"))
        self.failUnlessReallyEqual(ga1(u"URI:stuff"), ("URI:stuff", ""))
        self.failUnlessReallyEqual(ga1(u"URI:stuff/file"), ("URI:stuff", "file"))
        self.failUnlessReallyEqual(ga1(u"URI:stuff:./file"), ("URI:stuff", "file"))
        self.failUnlessReallyEqual(ga1(u"URI:stuff/dir/file"), ("URI:stuff", "dir/file"))
        self.failUnlessReallyEqual(ga1(u"URI:stuff:./dir/file"), ("URI:stuff", "dir/file"))
        self.failUnlessRaises(common.UnknownAliasError, ga1, u"missing:")
        self.failUnlessRaises(common.UnknownAliasError, ga1, u"missing:dir")
        self.failUnlessRaises(common.UnknownAliasError, ga1, u"missing:dir/file")

        def ga2(path):
            return get_alias(aliases, path, None)
        self.failUnlessReallyEqual(ga2(u"bare"), (DefaultAliasMarker, "bare"))
        self.failUnlessReallyEqual(ga2(u"baredir/file"),
                             (DefaultAliasMarker, "baredir/file"))
        self.failUnlessReallyEqual(ga2(u"baredir/file:7"),
                             (DefaultAliasMarker, "baredir/file:7"))
        self.failUnlessReallyEqual(ga2(u"baredir/sub:1/file:7"),
                             (DefaultAliasMarker, "baredir/sub:1/file:7"))
        self.failUnlessReallyEqual(ga2(u"tahoe:"), ("TA", ""))
        self.failUnlessReallyEqual(ga2(u"tahoe:file"), ("TA", "file"))
        self.failUnlessReallyEqual(ga2(u"tahoe:dir/file"), ("TA", "dir/file"))
        # on windows, we really want c:foo to indicate a local file.
        # default==None is what 'tahoe cp' uses.
        if uses_lettercolon:
            self.failUnlessReallyEqual(ga2(u"c:"), (DefaultAliasMarker, "c:"))
            self.failUnlessReallyEqual(ga2(u"c:file"), (DefaultAliasMarker, "c:file"))
            self.failUnlessReallyEqual(ga2(u"c:dir/file"),
                                 (DefaultAliasMarker, "c:dir/file"))
        else:
            self.failUnlessReallyEqual(ga2(u"c:"), ("CA", ""))
            self.failUnlessReallyEqual(ga2(u"c:file"), ("CA", "file"))
            self.failUnlessReallyEqual(ga2(u"c:dir/file"), ("CA", "dir/file"))
        self.failUnlessReallyEqual(ga2(u"work:"), ("WA", ""))
        self.failUnlessReallyEqual(ga2(u"work:file"), ("WA", "file"))
        self.failUnlessReallyEqual(ga2(u"work:dir/file"), ("WA", "dir/file"))
        self.failUnlessReallyEqual(ga2(u"URI:stuff"), ("URI:stuff", ""))
        self.failUnlessReallyEqual(ga2(u"URI:stuff/file"), ("URI:stuff", "file"))
        self.failUnlessReallyEqual(ga2(u"URI:stuff:./file"), ("URI:stuff", "file"))
        self.failUnlessReallyEqual(ga2(u"URI:stuff/dir/file"), ("URI:stuff", "dir/file"))
        self.failUnlessReallyEqual(ga2(u"URI:stuff:./dir/file"), ("URI:stuff", "dir/file"))
        self.failUnlessRaises(common.UnknownAliasError, ga2, u"missing:")
        self.failUnlessRaises(common.UnknownAliasError, ga2, u"missing:dir")
        self.failUnlessRaises(common.UnknownAliasError, ga2, u"missing:dir/file")

        def ga3(path):
            old = common.pretend_platform_uses_lettercolon
            try:
                common.pretend_platform_uses_lettercolon = True
                retval = get_alias(aliases, path, None)
            finally:
                common.pretend_platform_uses_lettercolon = old
            return retval
        self.failUnlessReallyEqual(ga3(u"bare"), (DefaultAliasMarker, "bare"))
        self.failUnlessReallyEqual(ga3(u"baredir/file"),
                             (DefaultAliasMarker, "baredir/file"))
        self.failUnlessReallyEqual(ga3(u"baredir/file:7"),
                             (DefaultAliasMarker, "baredir/file:7"))
        self.failUnlessReallyEqual(ga3(u"baredir/sub:1/file:7"),
                             (DefaultAliasMarker, "baredir/sub:1/file:7"))
        self.failUnlessReallyEqual(ga3(u"tahoe:"), ("TA", ""))
        self.failUnlessReallyEqual(ga3(u"tahoe:file"), ("TA", "file"))
        self.failUnlessReallyEqual(ga3(u"tahoe:dir/file"), ("TA", "dir/file"))
        self.failUnlessReallyEqual(ga3(u"c:"), (DefaultAliasMarker, "c:"))
        self.failUnlessReallyEqual(ga3(u"c:file"), (DefaultAliasMarker, "c:file"))
        self.failUnlessReallyEqual(ga3(u"c:dir/file"),
                             (DefaultAliasMarker, "c:dir/file"))
        self.failUnlessReallyEqual(ga3(u"work:"), ("WA", ""))
        self.failUnlessReallyEqual(ga3(u"work:file"), ("WA", "file"))
        self.failUnlessReallyEqual(ga3(u"work:dir/file"), ("WA", "dir/file"))
        self.failUnlessReallyEqual(ga3(u"URI:stuff"), ("URI:stuff", ""))
        self.failUnlessReallyEqual(ga3(u"URI:stuff:./file"), ("URI:stuff", "file"))
        self.failUnlessReallyEqual(ga3(u"URI:stuff:./dir/file"), ("URI:stuff", "dir/file"))
        self.failUnlessRaises(common.UnknownAliasError, ga3, u"missing:")
        self.failUnlessRaises(common.UnknownAliasError, ga3, u"missing:dir")
        self.failUnlessRaises(common.UnknownAliasError, ga3, u"missing:dir/file")
        # calling get_alias with a path that doesn't include an alias and
        # default set to something that isn't in the aliases argument should
        # raise an UnknownAliasError.
        def ga4(path):
            return get_alias(aliases, path, u"badddefault:")
        self.failUnlessRaises(common.UnknownAliasError, ga4, u"afile")
        self.failUnlessRaises(common.UnknownAliasError, ga4, u"a/dir/path/")

        def ga5(path):
            old = common.pretend_platform_uses_lettercolon
            try:
                common.pretend_platform_uses_lettercolon = True
                retval = get_alias(aliases, path, u"baddefault:")
            finally:
                common.pretend_platform_uses_lettercolon = old
            return retval
        self.failUnlessRaises(common.UnknownAliasError, ga5, u"C:\\Windows")

    def test_listdir_unicode_good(self):
        filenames = [u'L\u00F4zane', u'Bern', u'Gen\u00E8ve']  # must be NFC

        for name in filenames:
            self.skip_if_cannot_represent_filename(name)

        basedir = "cli/common/listdir_unicode_good"
        fileutil.make_dirs(basedir)

        for name in filenames:
            open(os.path.join(unicode(basedir), name), "wb").close()

        for file in listdir_unicode(unicode(basedir)):
            self.failUnlessIn(normalize(file), filenames)

    def test_exception_catcher(self):
        self.basedir = "cli/exception_catcher"

        runner_mock = Mock()
        sys_exit_mock = Mock()
        stderr = StringIO()
        self.patch(sys, "argv", ["tahoe"])
        self.patch(runner, "runner", runner_mock)
        self.patch(sys, "exit", sys_exit_mock)
        self.patch(sys, "stderr", stderr)
        exc = Exception("canary")

        def call_runner(args, install_node_control=True):
            raise exc
        runner_mock.side_effect = call_runner

        runner.run()
        self.failUnlessEqual(runner_mock.call_args_list, [call([], install_node_control=True)])
        self.failUnlessEqual(sys_exit_mock.call_args_list, [call(1)])
        self.failUnlessIn(str(exc), stderr.getvalue())


class Help(unittest.TestCase):
    def test_get(self):
        help = str(cli.GetOptions())
        self.failUnlessIn(" get [options] REMOTE_FILE LOCAL_FILE", help)
        self.failUnlessIn("% tahoe get FOO |less", help)

    def test_put(self):
        help = str(cli.PutOptions())
        self.failUnlessIn(" put [options] LOCAL_FILE REMOTE_FILE", help)
        self.failUnlessIn("% cat FILE | tahoe put", help)

    def test_ls(self):
        help = str(cli.ListOptions())
        self.failUnlessIn(" ls [options] [PATH]", help)

    def test_unlink(self):
        help = str(cli.UnlinkOptions())
        self.failUnlessIn(" unlink [options] REMOTE_FILE", help)

    def test_rm(self):
        help = str(cli.RmOptions())
        self.failUnlessIn(" rm [options] REMOTE_FILE", help)

    def test_mv(self):
        help = str(cli.MvOptions())
        self.failUnlessIn(" mv [options] FROM TO", help)
        self.failUnlessIn("Use 'tahoe mv' to move files", help)

    def test_cp(self):
        help = str(cli.CpOptions())
        self.failUnlessIn(" cp [options] FROM.. TO", help)
        self.failUnlessIn("Use 'tahoe cp' to copy files", help)

    def test_ln(self):
        help = str(cli.LnOptions())
        self.failUnlessIn(" ln [options] FROM_LINK TO_LINK", help)
        self.failUnlessIn("Use 'tahoe ln' to duplicate a link", help)

    def test_mkdir(self):
        help = str(cli.MakeDirectoryOptions())
        self.failUnlessIn(" mkdir [options] [REMOTE_DIR]", help)
        self.failUnlessIn("Create a new directory", help)

    def test_backup(self):
        help = str(cli.BackupOptions())
        self.failUnlessIn(" backup [options] FROM ALIAS:TO", help)

    def test_webopen(self):
        help = str(cli.WebopenOptions())
        self.failUnlessIn(" webopen [options] [ALIAS:PATH]", help)

    def test_manifest(self):
        help = str(cli.ManifestOptions())
        self.failUnlessIn(" manifest [options] [ALIAS:PATH]", help)

    def test_stats(self):
        help = str(cli.StatsOptions())
        self.failUnlessIn(" stats [options] [ALIAS:PATH]", help)

    def test_check(self):
        help = str(cli.CheckOptions())
        self.failUnlessIn(" check [options] [ALIAS:PATH]", help)

    def test_deep_check(self):
        help = str(cli.DeepCheckOptions())
        self.failUnlessIn(" deep-check [options] [ALIAS:PATH]", help)

    def test_create_alias(self):
        help = str(cli.CreateAliasOptions())
        self.failUnlessIn(" create-alias [options] ALIAS[:]", help)

    def test_add_alias(self):
        help = str(cli.AddAliasOptions())
        self.failUnlessIn(" add-alias [options] ALIAS[:] DIRCAP", help)

    def test_list_aliases(self):
        help = str(cli.ListAliasesOptions())
        self.failUnlessIn(" list-aliases [options]", help)

    def test_start(self):
        help = str(startstop_node.StartOptions())
        self.failUnlessIn(" start [options] [NODEDIR]", help)

    def test_stop(self):
        help = str(startstop_node.StopOptions())
        self.failUnlessIn(" stop [options] [NODEDIR]", help)

    def test_restart(self):
        help = str(startstop_node.RestartOptions())
        self.failUnlessIn(" restart [options] [NODEDIR]", help)

    def test_run(self):
        help = str(startstop_node.RunOptions())
        self.failUnlessIn(" run [options] [NODEDIR]", help)

    def test_create_client(self):
        help = str(create_node.CreateClientOptions())
        self.failUnlessIn(" create-client [options] [NODEDIR]", help)

    def test_create_node(self):
        help = str(create_node.CreateNodeOptions())
        self.failUnlessIn(" create-node [options] [NODEDIR]", help)

    def test_create_introducer(self):
        help = str(create_node.CreateIntroducerOptions())
        self.failUnlessIn(" create-introducer [options] NODEDIR", help)

    def test_debug_trial(self):
        help = str(debug.TrialOptions())
        self.failUnlessIn(" debug trial [options] [[file|package|module|TestCase|testmethod]...]", help)
        self.failUnlessIn("The 'tahoe debug trial' command uses the correct imports", help)

    def test_debug_flogtool(self):
        options = debug.FlogtoolOptions()
        help = str(options)
        self.failUnlessIn(" debug flogtool ", help)
        self.failUnlessIn("The 'tahoe debug flogtool' command uses the correct imports", help)

        for (option, shortcut, oClass, desc) in options.subCommands:
            subhelp = str(oClass())
            self.failUnlessIn(" debug flogtool %s " % (option,), subhelp)


class CreateAlias(GridTestMixin, CLITestMixin, unittest.TestCase):

    def _test_webopen(self, args, expected_url):
        woo = cli.WebopenOptions()
        all_args = ["--node-directory", self.get_clientdir()] + list(args)
        woo.parseOptions(all_args)
        urls = []
        rc = cli.webopen(woo, urls.append)
        self.failUnlessReallyEqual(rc, 0)
        self.failUnlessReallyEqual(len(urls), 1)
        self.failUnlessReallyEqual(urls[0], expected_url)

    def test_create(self):
        self.basedir = "cli/CreateAlias/create"
        self.set_up_grid()
        aliasfile = os.path.join(self.get_clientdir(), "private", "aliases")

        d = self.do_cli("create-alias", "tahoe")
        def _done((rc,stdout,stderr)):
            self.failUnless("Alias 'tahoe' created" in stdout)
            self.failIf(stderr)
            aliases = get_aliases(self.get_clientdir())
            self.failUnless("tahoe" in aliases)
            self.failUnless(aliases["tahoe"].startswith("URI:DIR2:"))
        d.addCallback(_done)
        d.addCallback(lambda res: self.do_cli("create-alias", "two:"))

        def _stash_urls(res):
            aliases = get_aliases(self.get_clientdir())
            node_url_file = os.path.join(self.get_clientdir(), "node.url")
            nodeurl = fileutil.read(node_url_file).strip()
            self.welcome_url = nodeurl
            uribase = nodeurl + "uri/"
            self.tahoe_url = uribase + urllib.quote(aliases["tahoe"])
            self.tahoe_subdir_url = self.tahoe_url + "/subdir"
            self.two_url = uribase + urllib.quote(aliases["two"])
            self.two_uri = aliases["two"]
        d.addCallback(_stash_urls)

        d.addCallback(lambda res: self.do_cli("create-alias", "two")) # dup
        def _check_create_duplicate((rc,stdout,stderr)):
            self.failIfEqual(rc, 0)
            self.failUnless("Alias 'two' already exists!" in stderr)
            aliases = get_aliases(self.get_clientdir())
            self.failUnlessReallyEqual(aliases["two"], self.two_uri)
        d.addCallback(_check_create_duplicate)

        d.addCallback(lambda res: self.do_cli("add-alias", "added", self.two_uri))
        def _check_add((rc,stdout,stderr)):
            self.failUnlessReallyEqual(rc, 0)
            self.failUnless("Alias 'added' added" in stdout)
        d.addCallback(_check_add)

        # check add-alias with a duplicate
        d.addCallback(lambda res: self.do_cli("add-alias", "two", self.two_uri))
        def _check_add_duplicate((rc,stdout,stderr)):
            self.failIfEqual(rc, 0)
            self.failUnless("Alias 'two' already exists!" in stderr)
            aliases = get_aliases(self.get_clientdir())
            self.failUnlessReallyEqual(aliases["two"], self.two_uri)
        d.addCallback(_check_add_duplicate)

        # check create-alias and add-alias with invalid aliases
        def _check_invalid((rc,stdout,stderr)):
            self.failIfEqual(rc, 0)
            self.failUnlessIn("cannot contain", stderr)

        for invalid in ['foo:bar', 'foo bar', 'foobar::']:
            d.addCallback(lambda res, invalid=invalid: self.do_cli("create-alias", invalid))
            d.addCallback(_check_invalid)
            d.addCallback(lambda res, invalid=invalid: self.do_cli("add-alias", invalid, self.two_uri))
            d.addCallback(_check_invalid)

        def _test_urls(junk):
            self._test_webopen([], self.welcome_url)
            self._test_webopen(["/"], self.tahoe_url)
            self._test_webopen(["tahoe:"], self.tahoe_url)
            self._test_webopen(["tahoe:/"], self.tahoe_url)
            self._test_webopen(["tahoe:subdir"], self.tahoe_subdir_url)
            self._test_webopen(["-i", "tahoe:subdir"],
                               self.tahoe_subdir_url+"?t=info")
            self._test_webopen(["tahoe:subdir/"], self.tahoe_subdir_url + '/')
            self._test_webopen(["tahoe:subdir/file"],
                               self.tahoe_subdir_url + '/file')
            self._test_webopen(["--info", "tahoe:subdir/file"],
                               self.tahoe_subdir_url + '/file?t=info')
            # if "file" is indeed a file, then the url produced by webopen in
            # this case is disallowed by the webui. but by design, webopen
            # passes through the mistake from the user to the resultant
            # webopened url
            self._test_webopen(["tahoe:subdir/file/"], self.tahoe_subdir_url + '/file/')
            self._test_webopen(["two:"], self.two_url)
        d.addCallback(_test_urls)

        def _remove_trailing_newline_and_create_alias(ign):
            # ticket #741 is about a manually-edited alias file (which
            # doesn't end in a newline) being corrupted by a subsequent
            # "tahoe create-alias"
            old = fileutil.read(aliasfile)
            fileutil.write(aliasfile, old.rstrip())
            return self.do_cli("create-alias", "un-corrupted1")
        d.addCallback(_remove_trailing_newline_and_create_alias)
        def _check_not_corrupted1((rc,stdout,stderr)):
            self.failUnless("Alias 'un-corrupted1' created" in stdout, stdout)
            self.failIf(stderr)
            # the old behavior was to simply append the new record, causing a
            # line that looked like "NAME1: CAP1NAME2: CAP2". This won't look
            # like a valid dircap, so get_aliases() will raise an exception.
            aliases = get_aliases(self.get_clientdir())
            self.failUnless("added" in aliases)
            self.failUnless(aliases["added"].startswith("URI:DIR2:"))
            # to be safe, let's confirm that we don't see "NAME2:" in CAP1.
            # No chance of a false-negative, because the hyphen in
            # "un-corrupted1" is not a valid base32 character.
            self.failIfIn("un-corrupted1:", aliases["added"])
            self.failUnless("un-corrupted1" in aliases)
            self.failUnless(aliases["un-corrupted1"].startswith("URI:DIR2:"))
        d.addCallback(_check_not_corrupted1)

        def _remove_trailing_newline_and_add_alias(ign):
            # same thing, but for "tahoe add-alias"
            old = fileutil.read(aliasfile)
            fileutil.write(aliasfile, old.rstrip())
            return self.do_cli("add-alias", "un-corrupted2", self.two_uri)
        d.addCallback(_remove_trailing_newline_and_add_alias)
        def _check_not_corrupted((rc,stdout,stderr)):
            self.failUnless("Alias 'un-corrupted2' added" in stdout, stdout)
            self.failIf(stderr)
            aliases = get_aliases(self.get_clientdir())
            self.failUnless("un-corrupted1" in aliases)
            self.failUnless(aliases["un-corrupted1"].startswith("URI:DIR2:"))
            self.failIfIn("un-corrupted2:", aliases["un-corrupted1"])
            self.failUnless("un-corrupted2" in aliases)
            self.failUnless(aliases["un-corrupted2"].startswith("URI:DIR2:"))
        d.addCallback(_check_not_corrupted)

    def test_create_unicode(self):
        self.basedir = "cli/CreateAlias/create_unicode"
        self.set_up_grid()

        try:
            etudes_arg = u"\u00E9tudes".encode(get_io_encoding())
            lumiere_arg = u"lumi\u00E8re.txt".encode(get_io_encoding())
        except UnicodeEncodeError:
            raise unittest.SkipTest("A non-ASCII command argument could not be encoded on this platform.")

        d = self.do_cli("create-alias", etudes_arg)
        def _check_create_unicode((rc, out, err)):
            self.failUnlessReallyEqual(rc, 0)
            self.failUnlessReallyEqual(err, "")
            self.failUnlessIn("Alias %s created" % quote_output(u"\u00E9tudes"), out)

            aliases = get_aliases(self.get_clientdir())
            self.failUnless(aliases[u"\u00E9tudes"].startswith("URI:DIR2:"))
        d.addCallback(_check_create_unicode)

        d.addCallback(lambda res: self.do_cli("ls", etudes_arg + ":"))
        def _check_ls1((rc, out, err)):
            self.failUnlessReallyEqual(rc, 0)
            self.failUnlessReallyEqual(err, "")
            self.failUnlessReallyEqual(out, "")
        d.addCallback(_check_ls1)

        d.addCallback(lambda res: self.do_cli("put", "-", etudes_arg + ":uploaded.txt",
                                              stdin="Blah blah blah"))

        d.addCallback(lambda res: self.do_cli("ls", etudes_arg + ":"))
        def _check_ls2((rc, out, err)):
            self.failUnlessReallyEqual(rc, 0)
            self.failUnlessReallyEqual(err, "")
            self.failUnlessReallyEqual(out, "uploaded.txt\n")
        d.addCallback(_check_ls2)

        d.addCallback(lambda res: self.do_cli("get", etudes_arg + ":uploaded.txt"))
        def _check_get((rc, out, err)):
            self.failUnlessReallyEqual(rc, 0)
            self.failUnlessReallyEqual(err, "")
            self.failUnlessReallyEqual(out, "Blah blah blah")
        d.addCallback(_check_get)

        # Ensure that an Unicode filename in an Unicode alias works as expected
        d.addCallback(lambda res: self.do_cli("put", "-", etudes_arg + ":" + lumiere_arg,
                                              stdin="Let the sunshine In!"))

        d.addCallback(lambda res: self.do_cli("get",
                                              get_aliases(self.get_clientdir())[u"\u00E9tudes"] + "/" + lumiere_arg))
        def _check_get2((rc, out, err)):
            self.failUnlessReallyEqual(rc, 0)
            self.failUnlessReallyEqual(err, "")
            self.failUnlessReallyEqual(out, "Let the sunshine In!")
        d.addCallback(_check_get2)

        return d

    # TODO: test list-aliases, including Unicode


class Ln(GridTestMixin, CLITestMixin, unittest.TestCase):
    def _create_test_file(self):
        data = "puppies" * 1000
        path = os.path.join(self.basedir, "datafile")
        fileutil.write(path, data)
        self.datafile = path

    def test_ln_without_alias(self):
        # if invoked without an alias when the 'tahoe' alias doesn't
        # exist, 'tahoe ln' should output a useful error message and not
        # a stack trace
        self.basedir = "cli/Ln/ln_without_alias"
        self.set_up_grid()
        d = self.do_cli("ln", "from", "to")
        def _check((rc, out, err)):
            self.failUnlessReallyEqual(rc, 1)
            self.failUnlessIn("error:", err)
            self.failUnlessReallyEqual(out, "")
        d.addCallback(_check)
        # Make sure that validation extends to the "to" parameter
        d.addCallback(lambda ign: self.do_cli("create-alias", "havasu"))
        d.addCallback(lambda ign: self._create_test_file())
        d.addCallback(lambda ign: self.do_cli("put", self.datafile,
                                              "havasu:from"))
        d.addCallback(lambda ign: self.do_cli("ln", "havasu:from", "to"))
        d.addCallback(_check)
        return d

    def test_ln_with_nonexistent_alias(self):
        # If invoked with aliases that don't exist, 'tahoe ln' should
        # output a useful error message and not a stack trace.
        self.basedir = "cli/Ln/ln_with_nonexistent_alias"
        self.set_up_grid()
        d = self.do_cli("ln", "havasu:from", "havasu:to")
        def _check((rc, out, err)):
            self.failUnlessReallyEqual(rc, 1)
            self.failUnlessIn("error:", err)
        d.addCallback(_check)
        # Make sure that validation occurs on the to parameter if the
        # from parameter passes.
        d.addCallback(lambda ign: self.do_cli("create-alias", "havasu"))
        d.addCallback(lambda ign: self._create_test_file())
        d.addCallback(lambda ign: self.do_cli("put", self.datafile,
                                              "havasu:from"))
        d.addCallback(lambda ign: self.do_cli("ln", "havasu:from", "huron:to"))
        d.addCallback(_check)
        return d


class Put(GridTestMixin, CLITestMixin, unittest.TestCase):

    def test_unlinked_immutable_stdin(self):
        # tahoe get `echo DATA | tahoe put`
        # tahoe get `echo DATA | tahoe put -`
        self.basedir = "cli/Put/unlinked_immutable_stdin"
        DATA = "data" * 100
        self.set_up_grid()
        d = self.do_cli("put", stdin=DATA)
        def _uploaded(res):
            (rc, out, err) = res
            self.failUnlessIn("waiting for file data on stdin..", err)
            self.failUnlessIn("200 OK", err)
            self.readcap = out
            self.failUnless(self.readcap.startswith("URI:CHK:"))
        d.addCallback(_uploaded)
        d.addCallback(lambda res: self.do_cli("get", self.readcap))
        def _downloaded(res):
            (rc, out, err) = res
            self.failUnlessReallyEqual(err, "")
            self.failUnlessReallyEqual(out, DATA)
        d.addCallback(_downloaded)
        d.addCallback(lambda res: self.do_cli("put", "-", stdin=DATA))
        d.addCallback(lambda (rc, out, err):
                      self.failUnlessReallyEqual(out, self.readcap))
        return d

    def test_unlinked_immutable_from_file(self):
        # tahoe put file.txt
        # tahoe put ./file.txt
        # tahoe put /tmp/file.txt
        # tahoe put ~/file.txt
        self.basedir = "cli/Put/unlinked_immutable_from_file"
        self.set_up_grid()

        rel_fn = os.path.join(self.basedir, "DATAFILE")
        abs_fn = unicode_to_argv(abspath_expanduser_unicode(unicode(rel_fn)))
        # we make the file small enough to fit in a LIT file, for speed
        fileutil.write(rel_fn, "short file")
        d = self.do_cli("put", rel_fn)
        def _uploaded((rc, out, err)):
            readcap = out
            self.failUnless(readcap.startswith("URI:LIT:"), readcap)
            self.readcap = readcap
        d.addCallback(_uploaded)
        d.addCallback(lambda res: self.do_cli("put", "./" + rel_fn))
        d.addCallback(lambda (rc,stdout,stderr):
                      self.failUnlessReallyEqual(stdout, self.readcap))
        d.addCallback(lambda res: self.do_cli("put", abs_fn))
        d.addCallback(lambda (rc,stdout,stderr):
                      self.failUnlessReallyEqual(stdout, self.readcap))
        # we just have to assume that ~ is handled properly
        return d

    def test_immutable_from_file(self):
        # tahoe put file.txt uploaded.txt
        # tahoe - uploaded.txt
        # tahoe put file.txt subdir/uploaded.txt
        # tahoe put file.txt tahoe:uploaded.txt
        # tahoe put file.txt tahoe:subdir/uploaded.txt
        # tahoe put file.txt DIRCAP:./uploaded.txt
        # tahoe put file.txt DIRCAP:./subdir/uploaded.txt
        self.basedir = "cli/Put/immutable_from_file"
        self.set_up_grid()

        rel_fn = os.path.join(self.basedir, "DATAFILE")
        # we make the file small enough to fit in a LIT file, for speed
        DATA = "short file"
        DATA2 = "short file two"
        fileutil.write(rel_fn, DATA)

        d = self.do_cli("create-alias", "tahoe")

        d.addCallback(lambda res:
                      self.do_cli("put", rel_fn, "uploaded.txt"))
        def _uploaded((rc, out, err)):
            readcap = out.strip()
            self.failUnless(readcap.startswith("URI:LIT:"), readcap)
            self.failUnlessIn("201 Created", err)
            self.readcap = readcap
        d.addCallback(_uploaded)
        d.addCallback(lambda res:
                      self.do_cli("get", "tahoe:uploaded.txt"))
        d.addCallback(lambda (rc,stdout,stderr):
                      self.failUnlessReallyEqual(stdout, DATA))

        d.addCallback(lambda res:
                      self.do_cli("put", "-", "uploaded.txt", stdin=DATA2))
        def _replaced((rc, out, err)):
            readcap = out.strip()
            self.failUnless(readcap.startswith("URI:LIT:"), readcap)
            self.failUnlessIn("200 OK", err)
        d.addCallback(_replaced)

        d.addCallback(lambda res:
                      self.do_cli("put", rel_fn, "subdir/uploaded2.txt"))
        d.addCallback(lambda res: self.do_cli("get", "subdir/uploaded2.txt"))
        d.addCallback(lambda (rc,stdout,stderr):
                      self.failUnlessReallyEqual(stdout, DATA))

        d.addCallback(lambda res:
                      self.do_cli("put", rel_fn, "tahoe:uploaded3.txt"))
        d.addCallback(lambda res: self.do_cli("get", "tahoe:uploaded3.txt"))
        d.addCallback(lambda (rc,stdout,stderr):
                      self.failUnlessReallyEqual(stdout, DATA))

        d.addCallback(lambda res:
                      self.do_cli("put", rel_fn, "tahoe:subdir/uploaded4.txt"))
        d.addCallback(lambda res:
                      self.do_cli("get", "tahoe:subdir/uploaded4.txt"))
        d.addCallback(lambda (rc,stdout,stderr):
                      self.failUnlessReallyEqual(stdout, DATA))

        def _get_dircap(res):
            self.dircap = get_aliases(self.get_clientdir())["tahoe"]
        d.addCallback(_get_dircap)

        d.addCallback(lambda res:
                      self.do_cli("put", rel_fn,
                                  self.dircap+":./uploaded5.txt"))
        d.addCallback(lambda res:
                      self.do_cli("get", "tahoe:uploaded5.txt"))
        d.addCallback(lambda (rc,stdout,stderr):
                      self.failUnlessReallyEqual(stdout, DATA))

        d.addCallback(lambda res:
                      self.do_cli("put", rel_fn,
                                  self.dircap+":./subdir/uploaded6.txt"))
        d.addCallback(lambda res:
                      self.do_cli("get", "tahoe:subdir/uploaded6.txt"))
        d.addCallback(lambda (rc,stdout,stderr):
                      self.failUnlessReallyEqual(stdout, DATA))

        return d

    def test_mutable_unlinked(self):
        # FILECAP = `echo DATA | tahoe put --mutable`
        # tahoe get FILECAP, compare against DATA
        # echo DATA2 | tahoe put - FILECAP
        # tahoe get FILECAP, compare against DATA2
        # tahoe put file.txt FILECAP
        self.basedir = "cli/Put/mutable_unlinked"
        self.set_up_grid()

        DATA = "data" * 100
        DATA2 = "two" * 100
        rel_fn = os.path.join(self.basedir, "DATAFILE")
        DATA3 = "three" * 100
        fileutil.write(rel_fn, DATA3)

        d = self.do_cli("put", "--mutable", stdin=DATA)
        def _created(res):
            (rc, out, err) = res
            self.failUnlessIn("waiting for file data on stdin..", err)
            self.failUnlessIn("200 OK", err)
            self.filecap = out
            self.failUnless(self.filecap.startswith("URI:SSK:"), self.filecap)
        d.addCallback(_created)
        d.addCallback(lambda res: self.do_cli("get", self.filecap))
        d.addCallback(lambda (rc,out,err): self.failUnlessReallyEqual(out, DATA))

        d.addCallback(lambda res: self.do_cli("put", "-", self.filecap, stdin=DATA2))
        def _replaced(res):
            (rc, out, err) = res
            self.failUnlessIn("waiting for file data on stdin..", err)
            self.failUnlessIn("200 OK", err)
            self.failUnlessReallyEqual(self.filecap, out)
        d.addCallback(_replaced)
        d.addCallback(lambda res: self.do_cli("get", self.filecap))
        d.addCallback(lambda (rc,out,err): self.failUnlessReallyEqual(out, DATA2))

        d.addCallback(lambda res: self.do_cli("put", rel_fn, self.filecap))
        def _replaced2(res):
            (rc, out, err) = res
            self.failUnlessIn("200 OK", err)
            self.failUnlessReallyEqual(self.filecap, out)
        d.addCallback(_replaced2)
        d.addCallback(lambda res: self.do_cli("get", self.filecap))
        d.addCallback(lambda (rc,out,err): self.failUnlessReallyEqual(out, DATA3))

        return d

    def test_mutable(self):
        # echo DATA1 | tahoe put --mutable - uploaded.txt
        # echo DATA2 | tahoe put - uploaded.txt # should modify-in-place
        # tahoe get uploaded.txt, compare against DATA2

        self.basedir = "cli/Put/mutable"
        self.set_up_grid()

        DATA1 = "data" * 100
        fn1 = os.path.join(self.basedir, "DATA1")
        fileutil.write(fn1, DATA1)
        DATA2 = "two" * 100
        fn2 = os.path.join(self.basedir, "DATA2")
        fileutil.write(fn2, DATA2)

        d = self.do_cli("create-alias", "tahoe")
        d.addCallback(lambda res:
                      self.do_cli("put", "--mutable", fn1, "tahoe:uploaded.txt"))
        d.addCallback(lambda res:
                      self.do_cli("put", fn2, "tahoe:uploaded.txt"))
        d.addCallback(lambda res:
                      self.do_cli("get", "tahoe:uploaded.txt"))
        d.addCallback(lambda (rc,out,err): self.failUnlessReallyEqual(out, DATA2))
        return d

    def _check_mdmf_json(self, (rc, json, err)):
         self.failUnlessEqual(rc, 0)
         self.failUnlessEqual(err, "")
         self.failUnlessIn('"format": "MDMF"', json)
         # We also want a valid MDMF cap to be in the json.
         self.failUnlessIn("URI:MDMF", json)
         self.failUnlessIn("URI:MDMF-RO", json)
         self.failUnlessIn("URI:MDMF-Verifier", json)

    def _check_sdmf_json(self, (rc, json, err)):
        self.failUnlessEqual(rc, 0)
        self.failUnlessEqual(err, "")
        self.failUnlessIn('"format": "SDMF"', json)
        # We also want to see the appropriate SDMF caps.
        self.failUnlessIn("URI:SSK", json)
        self.failUnlessIn("URI:SSK-RO", json)
        self.failUnlessIn("URI:SSK-Verifier", json)

    def _check_chk_json(self, (rc, json, err)):
        self.failUnlessEqual(rc, 0)
        self.failUnlessEqual(err, "")
        self.failUnlessIn('"format": "CHK"', json)
        # We also want to see the appropriate CHK caps.
        self.failUnlessIn("URI:CHK", json)
        self.failUnlessIn("URI:CHK-Verifier", json)

    def test_format(self):
        self.basedir = "cli/Put/format"
        self.set_up_grid()
        data = "data" * 40000 # 160kB total, two segments
        fn1 = os.path.join(self.basedir, "data")
        fileutil.write(fn1, data)
        d = self.do_cli("create-alias", "tahoe")

        def _put_and_ls(ign, cmdargs, expected, filename=None):
            if filename:
                args = ["put"] + cmdargs + [fn1, filename]
            else:
                # unlinked
                args = ["put"] + cmdargs + [fn1]
            d2 = self.do_cli(*args)
            def _list((rc, out, err)):
                self.failUnlessEqual(rc, 0) # don't allow failure
                if filename:
                    return self.do_cli("ls", "--json", filename)
                else:
                    cap = out.strip()
                    return self.do_cli("ls", "--json", cap)
            d2.addCallback(_list)
            return d2

        # 'tahoe put' to a directory
        d.addCallback(_put_and_ls, ["--mutable"], "SDMF", "tahoe:s1.txt")
        d.addCallback(self._check_sdmf_json) # backwards-compatibility
        d.addCallback(_put_and_ls, ["--format=SDMF"], "SDMF", "tahoe:s2.txt")
        d.addCallback(self._check_sdmf_json)
        d.addCallback(_put_and_ls, ["--format=sdmf"], "SDMF", "tahoe:s3.txt")
        d.addCallback(self._check_sdmf_json)
        d.addCallback(_put_and_ls, ["--mutable", "--format=SDMF"], "SDMF", "tahoe:s4.txt")
        d.addCallback(self._check_sdmf_json)

        d.addCallback(_put_and_ls, ["--format=MDMF"], "MDMF", "tahoe:m1.txt")
        d.addCallback(self._check_mdmf_json)
        d.addCallback(_put_and_ls, ["--mutable", "--format=MDMF"], "MDMF", "tahoe:m2.txt")
        d.addCallback(self._check_mdmf_json)

        d.addCallback(_put_and_ls, ["--format=CHK"], "CHK", "tahoe:c1.txt")
        d.addCallback(self._check_chk_json)
        d.addCallback(_put_and_ls, [], "CHK", "tahoe:c1.txt")
        d.addCallback(self._check_chk_json)

        # 'tahoe put' unlinked
        d.addCallback(_put_and_ls, ["--mutable"], "SDMF")
        d.addCallback(self._check_sdmf_json) # backwards-compatibility
        d.addCallback(_put_and_ls, ["--format=SDMF"], "SDMF")
        d.addCallback(self._check_sdmf_json)
        d.addCallback(_put_and_ls, ["--format=sdmf"], "SDMF")
        d.addCallback(self._check_sdmf_json)
        d.addCallback(_put_and_ls, ["--mutable", "--format=SDMF"], "SDMF")
        d.addCallback(self._check_sdmf_json)

        d.addCallback(_put_and_ls, ["--format=MDMF"], "MDMF")
        d.addCallback(self._check_mdmf_json)
        d.addCallback(_put_and_ls, ["--mutable", "--format=MDMF"], "MDMF")
        d.addCallback(self._check_mdmf_json)

        d.addCallback(_put_and_ls, ["--format=CHK"], "CHK")
        d.addCallback(self._check_chk_json)
        d.addCallback(_put_and_ls, [], "CHK")
        d.addCallback(self._check_chk_json)

        return d

    def test_put_to_mdmf_cap(self):
        self.basedir = "cli/Put/put_to_mdmf_cap"
        self.set_up_grid()
        data = "data" * 100000
        fn1 = os.path.join(self.basedir, "data")
        fileutil.write(fn1, data)
        d = self.do_cli("put", "--format=MDMF", fn1)
        def _got_cap((rc, out, err)):
            self.failUnlessEqual(rc, 0)
            self.cap = out.strip()
        d.addCallback(_got_cap)
        # Now try to write something to the cap using put.
        data2 = "data2" * 100000
        fn2 = os.path.join(self.basedir, "data2")
        fileutil.write(fn2, data2)
        d.addCallback(lambda ignored:
            self.do_cli("put", fn2, self.cap))
        def _got_put((rc, out, err)):
            self.failUnlessEqual(rc, 0)
            self.failUnlessIn(self.cap, out)
        d.addCallback(_got_put)
        # Now get the cap. We should see the data we just put there.
        d.addCallback(lambda ignored:
            self.do_cli("get", self.cap))
        def _got_data((rc, out, err)):
            self.failUnlessEqual(rc, 0)
            self.failUnlessEqual(out, data2)
        d.addCallback(_got_data)
        # add some extension information to the cap and try to put something
        # to it.
        def _make_extended_cap(ignored):
            self.cap = self.cap + ":Extension-Stuff"
        d.addCallback(_make_extended_cap)
        data3 = "data3" * 100000
        fn3 = os.path.join(self.basedir, "data3")
        fileutil.write(fn3, data3)
        d.addCallback(lambda ignored:
            self.do_cli("put", fn3, self.cap))
        d.addCallback(lambda ignored:
            self.do_cli("get", self.cap))
        def _got_data3((rc, out, err)):
            self.failUnlessEqual(rc, 0)
            self.failUnlessEqual(out, data3)
        d.addCallback(_got_data3)
        return d

    def test_put_to_sdmf_cap(self):
        self.basedir = "cli/Put/put_to_sdmf_cap"
        self.set_up_grid()
        data = "data" * 100000
        fn1 = os.path.join(self.basedir, "data")
        fileutil.write(fn1, data)
        d = self.do_cli("put", "--format=SDMF", fn1)
        def _got_cap((rc, out, err)):
            self.failUnlessEqual(rc, 0)
            self.cap = out.strip()
        d.addCallback(_got_cap)
        # Now try to write something to the cap using put.
        data2 = "data2" * 100000
        fn2 = os.path.join(self.basedir, "data2")
        fileutil.write(fn2, data2)
        d.addCallback(lambda ignored:
            self.do_cli("put", fn2, self.cap))
        def _got_put((rc, out, err)):
            self.failUnlessEqual(rc, 0)
            self.failUnlessIn(self.cap, out)
        d.addCallback(_got_put)
        # Now get the cap. We should see the data we just put there.
        d.addCallback(lambda ignored:
            self.do_cli("get", self.cap))
        def _got_data((rc, out, err)):
            self.failUnlessEqual(rc, 0)
            self.failUnlessEqual(out, data2)
        d.addCallback(_got_data)
        return d

    def test_mutable_type_invalid_format(self):
        o = cli.PutOptions()
        self.failUnlessRaises(usage.UsageError,
                              o.parseOptions,
                              ["--format=LDMF"])

    def test_put_with_nonexistent_alias(self):
        # when invoked with an alias that doesn't exist, 'tahoe put'
        # should output a useful error message, not a stack trace
        self.basedir = "cli/Put/put_with_nonexistent_alias"
        self.set_up_grid()
        d = self.do_cli("put", "somefile", "fake:afile")
        def _check((rc, out, err)):
            self.failUnlessReallyEqual(rc, 1)
            self.failUnlessIn("error:", err)
            self.failUnlessReallyEqual(out, "")
        d.addCallback(_check)
        return d

    def test_immutable_from_file_unicode(self):
        # tahoe put "\u00E0 trier.txt" "\u00E0 trier.txt"

        try:
            a_trier_arg = u"\u00E0 trier.txt".encode(get_io_encoding())
        except UnicodeEncodeError:
            raise unittest.SkipTest("A non-ASCII command argument could not be encoded on this platform.")

        self.skip_if_cannot_represent_filename(u"\u00E0 trier.txt")

        self.basedir = "cli/Put/immutable_from_file_unicode"
        self.set_up_grid()

        rel_fn = os.path.join(unicode(self.basedir), u"\u00E0 trier.txt")
        # we make the file small enough to fit in a LIT file, for speed
        DATA = "short file"
        fileutil.write(rel_fn, DATA)

        d = self.do_cli("create-alias", "tahoe")

        d.addCallback(lambda res:
                      self.do_cli("put", rel_fn.encode(get_io_encoding()), a_trier_arg))
        def _uploaded((rc, out, err)):
            readcap = out.strip()
            self.failUnless(readcap.startswith("URI:LIT:"), readcap)
            self.failUnlessIn("201 Created", err)
            self.readcap = readcap
        d.addCallback(_uploaded)

        d.addCallback(lambda res:
                      self.do_cli("get", "tahoe:" + a_trier_arg))
        d.addCallback(lambda (rc, out, err):
                      self.failUnlessReallyEqual(out, DATA))

        return d

class Admin(unittest.TestCase):
    def do_cli(self, *args, **kwargs):
        argv = list(args)
        stdin = kwargs.get("stdin", "")
        stdout, stderr = StringIO(), StringIO()
        d = threads.deferToThread(runner.runner, argv, run_by_human=False,
                                  stdin=StringIO(stdin),
                                  stdout=stdout, stderr=stderr)
        def _done(res):
            return stdout.getvalue(), stderr.getvalue()
        d.addCallback(_done)
        return d

    def test_generate_keypair(self):
        d = self.do_cli("admin", "generate-keypair")
        def _done( (stdout, stderr) ):
            lines = [line.strip() for line in stdout.splitlines()]
            privkey_bits = lines[0].split()
            pubkey_bits = lines[1].split()
            sk_header = "private:"
            vk_header = "public:"
            self.failUnlessEqual(privkey_bits[0], sk_header, lines[0])
            self.failUnlessEqual(pubkey_bits[0], vk_header, lines[1])
            self.failUnless(privkey_bits[1].startswith("priv-v0-"), lines[0])
            self.failUnless(pubkey_bits[1].startswith("pub-v0-"), lines[1])
            sk_bytes = base32.a2b(keyutil.remove_prefix(privkey_bits[1], "priv-v0-"))
            sk = ed25519.SigningKey(sk_bytes)
            vk_bytes = base32.a2b(keyutil.remove_prefix(pubkey_bits[1], "pub-v0-"))
            self.failUnlessEqual(sk.get_verifying_key_bytes(), vk_bytes)
        d.addCallback(_done)
        return d

    def test_derive_pubkey(self):
        priv1,pub1 = keyutil.make_keypair()
        d = self.do_cli("admin", "derive-pubkey", priv1)
        def _done( (stdout, stderr) ):
            lines = stdout.split("\n")
            privkey_line = lines[0].strip()
            pubkey_line = lines[1].strip()
            sk_header = "private: priv-v0-"
            vk_header = "public: pub-v0-"
            self.failUnless(privkey_line.startswith(sk_header), privkey_line)
            self.failUnless(pubkey_line.startswith(vk_header), pubkey_line)
            pub2 = pubkey_line[len(vk_header):]
            self.failUnlessEqual("pub-v0-"+pub2, pub1)
        d.addCallback(_done)
        return d


class List(GridTestMixin, CLITestMixin, unittest.TestCase):
    def test_list(self):
        self.basedir = "cli/List/list"
        self.set_up_grid()
        c0 = self.g.clients[0]
        small = "small"

        # u"g\u00F6\u00F6d" might not be representable in the argv and/or output encodings.
        # It is initially included in the directory in any case.
        try:
            good_arg = u"g\u00F6\u00F6d".encode(get_io_encoding())
        except UnicodeEncodeError:
            good_arg = None

        try:
            good_out = u"g\u00F6\u00F6d".encode(get_io_encoding())
        except UnicodeEncodeError:
            good_out = None

        d = c0.create_dirnode()
        def _stash_root_and_create_file(n):
            self.rootnode = n
            self.rooturi = n.get_uri()
            return n.add_file(u"g\u00F6\u00F6d", upload.Data(small, convergence=""))
        d.addCallback(_stash_root_and_create_file)
        def _stash_goodcap(n):
            self.goodcap = n.get_uri()
        d.addCallback(_stash_goodcap)
        d.addCallback(lambda ign: self.rootnode.create_subdirectory(u"1share"))
        d.addCallback(lambda n:
                      self.delete_shares_numbered(n.get_uri(), range(1,10)))
        d.addCallback(lambda ign: self.rootnode.create_subdirectory(u"0share"))
        d.addCallback(lambda n:
                      self.delete_shares_numbered(n.get_uri(), range(0,10)))
        d.addCallback(lambda ign:
                      self.do_cli("add-alias", "tahoe", self.rooturi))
        d.addCallback(lambda ign: self.do_cli("ls"))
        def _check1((rc,out,err)):
            if good_out is None:
                self.failUnlessReallyEqual(rc, 1)
                self.failUnlessIn("files whose names could not be converted", err)
                self.failUnlessIn(quote_output(u"g\u00F6\u00F6d"), err)
                self.failUnlessReallyEqual(sorted(out.splitlines()), sorted(["0share", "1share"]))
            else:
                self.failUnlessReallyEqual(rc, 0)
                self.failUnlessReallyEqual(err, "")
                self.failUnlessReallyEqual(sorted(out.splitlines()), sorted(["0share", "1share", good_out]))
        d.addCallback(_check1)
        d.addCallback(lambda ign: self.do_cli("ls", "missing"))
        def _check2((rc,out,err)):
            self.failIfEqual(rc, 0)
            self.failUnlessReallyEqual(err.strip(), "No such file or directory")
            self.failUnlessReallyEqual(out, "")
        d.addCallback(_check2)
        d.addCallback(lambda ign: self.do_cli("ls", "1share"))
        def _check3((rc,out,err)):
            self.failIfEqual(rc, 0)
            self.failUnlessIn("Error during GET: 410 Gone", err)
            self.failUnlessIn("UnrecoverableFileError:", err)
            self.failUnlessIn("could not be retrieved, because there were "
                              "insufficient good shares.", err)
            self.failUnlessReallyEqual(out, "")
        d.addCallback(_check3)
        d.addCallback(lambda ign: self.do_cli("ls", "0share"))
        d.addCallback(_check3)
        def _check4((rc, out, err)):
            if good_out is None:
                self.failUnlessReallyEqual(rc, 1)
                self.failUnlessIn("files whose names could not be converted", err)
                self.failUnlessIn(quote_output(u"g\u00F6\u00F6d"), err)
                self.failUnlessReallyEqual(out, "")
            else:
                # listing a file (as dir/filename) should have the edge metadata,
                # including the filename
                self.failUnlessReallyEqual(rc, 0)
                self.failUnlessIn(good_out, out)
                self.failIfIn("-r-- %d -" % len(small), out,
                              "trailing hyphen means unknown date")

        if good_arg is not None:
            d.addCallback(lambda ign: self.do_cli("ls", "-l", good_arg))
            d.addCallback(_check4)
            # listing a file as $DIRCAP/filename should work just like dir/filename
            d.addCallback(lambda ign: self.do_cli("ls", "-l", self.rooturi + "/" + good_arg))
            d.addCallback(_check4)
            # and similarly for $DIRCAP:./filename
            d.addCallback(lambda ign: self.do_cli("ls", "-l", self.rooturi + ":./" + good_arg))
            d.addCallback(_check4)

        def _check5((rc, out, err)):
            # listing a raw filecap should not explode, but it will have no
            # metadata, just the size
            self.failUnlessReallyEqual(rc, 0)
            self.failUnlessReallyEqual("-r-- %d -" % len(small), out.strip())
        d.addCallback(lambda ign: self.do_cli("ls", "-l", self.goodcap))
        d.addCallback(_check5)

        # Now rename 'g\u00F6\u00F6d' to 'good' and repeat the tests that might have been skipped due
        # to encoding problems.
        d.addCallback(lambda ign: self.rootnode.move_child_to(u"g\u00F6\u00F6d", self.rootnode, u"good"))

        d.addCallback(lambda ign: self.do_cli("ls"))
        def _check1_ascii((rc,out,err)):
            self.failUnlessReallyEqual(rc, 0)
            self.failUnlessReallyEqual(err, "")
            self.failUnlessReallyEqual(sorted(out.splitlines()), sorted(["0share", "1share", "good"]))
        d.addCallback(_check1_ascii)
        def _check4_ascii((rc, out, err)):
            # listing a file (as dir/filename) should have the edge metadata,
            # including the filename
            self.failUnlessReallyEqual(rc, 0)
            self.failUnlessIn("good", out)
            self.failIfIn("-r-- %d -" % len(small), out,
                          "trailing hyphen means unknown date")

        d.addCallback(lambda ign: self.do_cli("ls", "-l", "good"))
        d.addCallback(_check4_ascii)
        # listing a file as $DIRCAP/filename should work just like dir/filename
        d.addCallback(lambda ign: self.do_cli("ls", "-l", self.rooturi + "/good"))
        d.addCallback(_check4_ascii)
        # and similarly for $DIRCAP:./filename
        d.addCallback(lambda ign: self.do_cli("ls", "-l", self.rooturi + ":./good"))
        d.addCallback(_check4_ascii)

        unknown_immcap = "imm.URI:unknown"
        def _create_unknown(ign):
            nm = c0.nodemaker
            kids = {u"unknownchild-imm": (nm.create_from_cap(unknown_immcap), {})}
            return self.rootnode.create_subdirectory(u"unknown", initial_children=kids,
                                                     mutable=False)
        d.addCallback(_create_unknown)
        def _check6((rc, out, err)):
            # listing a directory referencing an unknown object should print
            # an extra message to stderr
            self.failUnlessReallyEqual(rc, 0)
            self.failUnlessIn("?r-- ? - unknownchild-imm\n", out)
            self.failUnlessIn("included unknown objects", err)
        d.addCallback(lambda ign: self.do_cli("ls", "-l", "unknown"))
        d.addCallback(_check6)
        def _check7((rc, out, err)):
            # listing an unknown cap directly should print an extra message
            # to stderr (currently this only works if the URI starts with 'URI:'
            # after any 'ro.' or 'imm.' prefix, otherwise it will be confused
            # with an alias).
            self.failUnlessReallyEqual(rc, 0)
            self.failUnlessIn("?r-- ? -\n", out)
            self.failUnlessIn("included unknown objects", err)
        d.addCallback(lambda ign: self.do_cli("ls", "-l", unknown_immcap))
        d.addCallback(_check7)
        return d

    def test_list_without_alias(self):
        # doing just 'tahoe ls' without specifying an alias or first
        # doing 'tahoe create-alias tahoe' should fail gracefully.
        self.basedir = "cli/List/list_without_alias"
        self.set_up_grid()
        d = self.do_cli("ls")
        def _check((rc, out, err)):
            self.failUnlessReallyEqual(rc, 1)
            self.failUnlessIn("error:", err)
            self.failUnlessReallyEqual(out, "")
        d.addCallback(_check)
        return d

    def test_list_with_nonexistent_alias(self):
        # doing 'tahoe ls' while specifying an alias that doesn't already
        # exist should fail with an informative error message
        self.basedir = "cli/List/list_with_nonexistent_alias"
        self.set_up_grid()
        d = self.do_cli("ls", "nonexistent:")
        def _check((rc, out, err)):
            self.failUnlessReallyEqual(rc, 1)
            self.failUnlessIn("error:", err)
            self.failUnlessIn("nonexistent", err)
            self.failUnlessReallyEqual(out, "")
        d.addCallback(_check)
        return d

    def _create_directory_structure(self):
        # Create a simple directory structure that we can use for MDMF,
        # SDMF, and immutable testing.
        assert self.g

        client = self.g.clients[0]
        # Create a dirnode
        d = client.create_dirnode()
        def _got_rootnode(n):
            # Add a few nodes.
            self._dircap = n.get_uri()
            nm = n._nodemaker
            # The uploaders may run at the same time, so we need two
            # MutableData instances or they'll fight over offsets &c and
            # break.
            mutable_data = MutableData("data" * 100000)
            mutable_data2 = MutableData("data" * 100000)
            # Add both kinds of mutable node.
            d1 = nm.create_mutable_file(mutable_data,
                                        version=MDMF_VERSION)
            d2 = nm.create_mutable_file(mutable_data2,
                                        version=SDMF_VERSION)
            # Add an immutable node. We do this through the directory,
            # with add_file.
            immutable_data = upload.Data("immutable data" * 100000,
                                         convergence="")
            d3 = n.add_file(u"immutable", immutable_data)
            ds = [d1, d2, d3]
            dl = defer.DeferredList(ds)
            def _made_files((r1, r2, r3)):
                self.failUnless(r1[0])
                self.failUnless(r2[0])
                self.failUnless(r3[0])

                # r1, r2, and r3 contain nodes.
                mdmf_node = r1[1]
                sdmf_node = r2[1]
                imm_node = r3[1]

                self._mdmf_uri = mdmf_node.get_uri()
                self._mdmf_readonly_uri = mdmf_node.get_readonly_uri()
                self._sdmf_uri = mdmf_node.get_uri()
                self._sdmf_readonly_uri = sdmf_node.get_readonly_uri()
                self._imm_uri = imm_node.get_uri()

                d1 = n.set_node(u"mdmf", mdmf_node)
                d2 = n.set_node(u"sdmf", sdmf_node)
                return defer.DeferredList([d1, d2])
            # We can now list the directory by listing self._dircap.
            dl.addCallback(_made_files)
            return dl
        d.addCallback(_got_rootnode)
        return d

    def test_list_mdmf(self):
        # 'tahoe ls' should include MDMF files.
        self.basedir = "cli/List/list_mdmf"
        self.set_up_grid()
        d = self._create_directory_structure()
        d.addCallback(lambda ignored:
            self.do_cli("ls", self._dircap))
        def _got_ls((rc, out, err)):
            self.failUnlessEqual(rc, 0)
            self.failUnlessEqual(err, "")
            self.failUnlessIn("immutable", out)
            self.failUnlessIn("mdmf", out)
            self.failUnlessIn("sdmf", out)
        d.addCallback(_got_ls)
        return d

    def test_list_mdmf_json(self):
        # 'tahoe ls' should include MDMF caps when invoked with MDMF
        # caps.
        self.basedir = "cli/List/list_mdmf_json"
        self.set_up_grid()
        d = self._create_directory_structure()
        d.addCallback(lambda ignored:
            self.do_cli("ls", "--json", self._dircap))
        def _got_json((rc, out, err)):
            self.failUnlessEqual(rc, 0)
            self.failUnlessEqual(err, "")
            self.failUnlessIn(self._mdmf_uri, out)
            self.failUnlessIn(self._mdmf_readonly_uri, out)
            self.failUnlessIn(self._sdmf_uri, out)
            self.failUnlessIn(self._sdmf_readonly_uri, out)
            self.failUnlessIn(self._imm_uri, out)
            self.failUnlessIn('"format": "SDMF"', out)
            self.failUnlessIn('"format": "MDMF"', out)
        d.addCallback(_got_json)
        return d


class Mv(GridTestMixin, CLITestMixin, unittest.TestCase):
    def test_mv_behavior(self):
        self.basedir = "cli/Mv/mv_behavior"
        self.set_up_grid()
        fn1 = os.path.join(self.basedir, "file1")
        DATA1 = "Nuclear launch codes"
        fileutil.write(fn1, DATA1)
        fn2 = os.path.join(self.basedir, "file2")
        DATA2 = "UML diagrams"
        fileutil.write(fn2, DATA2)
        # copy both files to the grid
        d = self.do_cli("create-alias", "tahoe")
        d.addCallback(lambda res:
            self.do_cli("cp", fn1, "tahoe:"))
        d.addCallback(lambda res:
            self.do_cli("cp", fn2, "tahoe:"))

        # do mv file1 file3
        # (we should be able to rename files)
        d.addCallback(lambda res:
            self.do_cli("mv", "tahoe:file1", "tahoe:file3"))
        d.addCallback(lambda (rc, out, err):
            self.failUnlessIn("OK", out, "mv didn't rename a file"))

        # do mv file3 file2
        # (This should succeed without issue)
        d.addCallback(lambda res:
            self.do_cli("mv", "tahoe:file3", "tahoe:file2"))
        # Out should contain "OK" to show that the transfer worked.
        d.addCallback(lambda (rc,out,err):
            self.failUnlessIn("OK", out, "mv didn't output OK after mving"))

        # Next, make a remote directory.
        d.addCallback(lambda res:
            self.do_cli("mkdir", "tahoe:directory"))

        # mv file2 directory
        # (should fail with a descriptive error message; the CLI mv
        #  client should support this)
        d.addCallback(lambda res:
            self.do_cli("mv", "tahoe:file2", "tahoe:directory"))
        d.addCallback(lambda (rc, out, err):
            self.failUnlessIn(
                "Error: You can't overwrite a directory with a file", err,
                "mv shouldn't overwrite directories" ))

        # mv file2 directory/
        # (should succeed by making file2 a child node of directory)
        d.addCallback(lambda res:
            self.do_cli("mv", "tahoe:file2", "tahoe:directory/"))
        # We should see an "OK"...
        d.addCallback(lambda (rc, out, err):
            self.failUnlessIn("OK", out,
                            "mv didn't mv a file into a directory"))
        # ... and be able to GET the file
        d.addCallback(lambda res:
            self.do_cli("get", "tahoe:directory/file2", self.basedir + "new"))
        d.addCallback(lambda (rc, out, err):
            self.failUnless(os.path.exists(self.basedir + "new"),
                            "mv didn't write the destination file"))
        # ... and not find the file where it was before.
        d.addCallback(lambda res:
            self.do_cli("get", "tahoe:file2", "file2"))
        d.addCallback(lambda (rc, out, err):
            self.failUnlessIn("404", err,
                            "mv left the source file intact"))

        # Let's build:
        # directory/directory2/some_file
        # directory3
        d.addCallback(lambda res:
            self.do_cli("mkdir", "tahoe:directory/directory2"))
        d.addCallback(lambda res:
            self.do_cli("cp", fn2, "tahoe:directory/directory2/some_file"))
        d.addCallback(lambda res:
            self.do_cli("mkdir", "tahoe:directory3"))

        # Let's now try to mv directory/directory2/some_file to
        # directory3/some_file
        d.addCallback(lambda res:
            self.do_cli("mv", "tahoe:directory/directory2/some_file",
                        "tahoe:directory3/"))
        # We should have just some_file in tahoe:directory3
        d.addCallback(lambda res:
            self.do_cli("get", "tahoe:directory3/some_file", "some_file"))
        d.addCallback(lambda (rc, out, err):
            self.failUnless("404" not in err,
                              "mv didn't handle nested directories correctly"))
        d.addCallback(lambda res:
            self.do_cli("get", "tahoe:directory3/directory", "directory"))
        d.addCallback(lambda (rc, out, err):
            self.failUnlessIn("404", err,
                              "mv moved the wrong thing"))
        return d

    def test_mv_error_if_DELETE_fails(self):
        self.basedir = "cli/Mv/mv_error_if_DELETE_fails"
        self.set_up_grid()
        fn1 = os.path.join(self.basedir, "file1")
        DATA1 = "Nuclear launch codes"
        fileutil.write(fn1, DATA1)

        original_do_http = tahoe_mv.do_http
        def mock_do_http(method, url, body=""):
            if method == "DELETE":
                class FakeResponse:
                    def read(self):
                        return "response"
                resp = FakeResponse()
                resp.status = '500 Something Went Wrong'
                resp.reason = '*shrug*'
                return resp
            else:
                return original_do_http(method, url, body=body)
        tahoe_mv.do_http = mock_do_http

        # copy file to the grid
        d = self.do_cli("create-alias", "tahoe")
        d.addCallback(lambda res:
            self.do_cli("cp", fn1, "tahoe:"))

        # do mv file1 file2
        d.addCallback(lambda res:
            self.do_cli("mv", "tahoe:file1", "tahoe:file2"))
        def _check( (rc, out, err) ):
            self.failIfIn("OK", out, "mv printed 'OK' even though the DELETE failed")
            self.failUnlessEqual(rc, 2)
        d.addCallback(_check)

        def _restore_do_http(res):
            tahoe_mv.do_http = original_do_http
            return res
        d.addBoth(_restore_do_http)
        return d

    def test_mv_without_alias(self):
        # doing 'tahoe mv' without explicitly specifying an alias or
        # creating the default 'tahoe' alias should fail with a useful
        # error message.
        self.basedir = "cli/Mv/mv_without_alias"
        self.set_up_grid()
        d = self.do_cli("mv", "afile", "anotherfile")
        def _check((rc, out, err)):
            self.failUnlessReallyEqual(rc, 1)
            self.failUnlessIn("error:", err)
            self.failUnlessReallyEqual(out, "")
        d.addCallback(_check)
        # check to see that the validation extends to the
        # target argument by making an alias that will work with the first
        # one.
        d.addCallback(lambda ign: self.do_cli("create-alias", "havasu"))
        def _create_a_test_file(ign):
            self.test_file_path = os.path.join(self.basedir, "afile")
            fileutil.write(self.test_file_path, "puppies" * 100)
        d.addCallback(_create_a_test_file)
        d.addCallback(lambda ign: self.do_cli("put", self.test_file_path,
                                              "havasu:afile"))
        d.addCallback(lambda ign: self.do_cli("mv", "havasu:afile",
                                              "anotherfile"))
        d.addCallback(_check)
        return d

    def test_mv_with_nonexistent_alias(self):
        # doing 'tahoe mv' with an alias that doesn't exist should fail
        # with an informative error message.
        self.basedir = "cli/Mv/mv_with_nonexistent_alias"
        self.set_up_grid()
        d = self.do_cli("mv", "fake:afile", "fake:anotherfile")
        def _check((rc, out, err)):
            self.failUnlessReallyEqual(rc, 1)
            self.failUnlessIn("error:", err)
            self.failUnlessIn("fake", err)
            self.failUnlessReallyEqual(out, "")
        d.addCallback(_check)
        # check to see that the validation extends to the
        # target argument by making an alias that will work with the first
        # one.
        d.addCallback(lambda ign: self.do_cli("create-alias", "havasu"))
        def _create_a_test_file(ign):
            self.test_file_path = os.path.join(self.basedir, "afile")
            fileutil.write(self.test_file_path, "puppies" * 100)
        d.addCallback(_create_a_test_file)
        d.addCallback(lambda ign: self.do_cli("put", self.test_file_path,
                                              "havasu:afile"))
        d.addCallback(lambda ign: self.do_cli("mv", "havasu:afile",
                                              "fake:anotherfile"))
        d.addCallback(_check)
        return d


class Cp(GridTestMixin, CLITestMixin, unittest.TestCase):

    def test_not_enough_args(self):
        o = cli.CpOptions()
        self.failUnlessRaises(usage.UsageError,
                              o.parseOptions, ["onearg"])

    def test_unicode_filename(self):
        self.basedir = "cli/Cp/unicode_filename"

        fn1 = os.path.join(unicode(self.basedir), u"\u00C4rtonwall")
        try:
            fn1_arg = fn1.encode(get_io_encoding())
            artonwall_arg = u"\u00C4rtonwall".encode(get_io_encoding())
        except UnicodeEncodeError:
            raise unittest.SkipTest("A non-ASCII command argument could not be encoded on this platform.")

        self.skip_if_cannot_represent_filename(fn1)

        self.set_up_grid()

        DATA1 = "unicode file content"
        fileutil.write(fn1, DATA1)

        fn2 = os.path.join(self.basedir, "Metallica")
        DATA2 = "non-unicode file content"
        fileutil.write(fn2, DATA2)

        d = self.do_cli("create-alias", "tahoe")

        d.addCallback(lambda res: self.do_cli("cp", fn1_arg, "tahoe:"))

        d.addCallback(lambda res: self.do_cli("get", "tahoe:" + artonwall_arg))
        d.addCallback(lambda (rc,out,err): self.failUnlessReallyEqual(out, DATA1))

        d.addCallback(lambda res: self.do_cli("cp", fn2, "tahoe:"))

        d.addCallback(lambda res: self.do_cli("get", "tahoe:Metallica"))
        d.addCallback(lambda (rc,out,err): self.failUnlessReallyEqual(out, DATA2))

        d.addCallback(lambda res: self.do_cli("ls", "tahoe:"))
        def _check((rc, out, err)):
            try:
                unicode_to_output(u"\u00C4rtonwall")
            except UnicodeEncodeError:
                self.failUnlessReallyEqual(rc, 1)
                self.failUnlessReallyEqual(out, "Metallica\n")
                self.failUnlessIn(quote_output(u"\u00C4rtonwall"), err)
                self.failUnlessIn("files whose names could not be converted", err)
            else:
                self.failUnlessReallyEqual(rc, 0)
                self.failUnlessReallyEqual(out.decode(get_io_encoding()), u"Metallica\n\u00C4rtonwall\n")
                self.failUnlessReallyEqual(err, "")
        d.addCallback(_check)

        return d

    def test_dangling_symlink_vs_recursion(self):
        if not hasattr(os, 'symlink'):
            raise unittest.SkipTest("Symlinks are not supported by Python on this platform.")

        # cp -r on a directory containing a dangling symlink shouldn't assert
        self.basedir = "cli/Cp/dangling_symlink_vs_recursion"
        self.set_up_grid()
        dn = os.path.join(self.basedir, "dir")
        os.mkdir(dn)
        fn = os.path.join(dn, "Fakebandica")
        ln = os.path.join(dn, "link")
        os.symlink(fn, ln)

        d = self.do_cli("create-alias", "tahoe")
        d.addCallback(lambda res: self.do_cli("cp", "--recursive",
                                              dn, "tahoe:"))
        return d

    def test_copy_using_filecap(self):
        self.basedir = "cli/Cp/test_copy_using_filecap"
        self.set_up_grid()
        outdir = os.path.join(self.basedir, "outdir")
        os.mkdir(outdir)
        fn1 = os.path.join(self.basedir, "Metallica")
        fn2 = os.path.join(outdir, "Not Metallica")
        fn3 = os.path.join(outdir, "test2")
        DATA1 = "puppies" * 10000
        fileutil.write(fn1, DATA1)

        d = self.do_cli("create-alias", "tahoe")
        d.addCallback(lambda ign: self.do_cli("put", fn1))
        def _put_file((rc, out, err)):
            self.failUnlessReallyEqual(rc, 0)
            self.failUnlessIn("200 OK", err)
            # keep track of the filecap
            self.filecap = out.strip()
        d.addCallback(_put_file)

        # Let's try copying this to the disk using the filecap
        #  cp FILECAP filename
        d.addCallback(lambda ign: self.do_cli("cp", self.filecap, fn2))
        def _copy_file((rc, out, err)):
            self.failUnlessReallyEqual(rc, 0)
            results = fileutil.read(fn2)
            self.failUnlessReallyEqual(results, DATA1)
        d.addCallback(_copy_file)

        # Test with ./ (see #761)
        #  cp FILECAP localdir
        d.addCallback(lambda ign: self.do_cli("cp", self.filecap, outdir))
        def _resp((rc, out, err)):
            self.failUnlessReallyEqual(rc, 1)
            self.failUnlessIn("error: you must specify a destination filename",
                              err)
            self.failUnlessReallyEqual(out, "")
        d.addCallback(_resp)

        # Create a directory, linked at tahoe:test
        d.addCallback(lambda ign: self.do_cli("mkdir", "tahoe:test"))
        def _get_dir((rc, out, err)):
            self.failUnlessReallyEqual(rc, 0)
            self.dircap = out.strip()
        d.addCallback(_get_dir)

        # Upload a file to the directory
        d.addCallback(lambda ign:
                      self.do_cli("put", fn1, "tahoe:test/test_file"))
        d.addCallback(lambda (rc, out, err): self.failUnlessReallyEqual(rc, 0))

        #  cp DIRCAP/filename localdir
        d.addCallback(lambda ign:
                      self.do_cli("cp",  self.dircap + "/test_file", outdir))
        def _get_resp((rc, out, err)):
            self.failUnlessReallyEqual(rc, 0)
            results = fileutil.read(os.path.join(outdir, "test_file"))
            self.failUnlessReallyEqual(results, DATA1)
        d.addCallback(_get_resp)

        #  cp -r DIRCAP/filename filename2
        d.addCallback(lambda ign:
                      self.do_cli("cp",  self.dircap + "/test_file", fn3))
        def _get_resp2((rc, out, err)):
            self.failUnlessReallyEqual(rc, 0)
            results = fileutil.read(fn3)
            self.failUnlessReallyEqual(results, DATA1)
        d.addCallback(_get_resp2)
        #  cp --verbose filename3 dircap:test_file
        d.addCallback(lambda ign:
                      self.do_cli("cp", "--verbose", '--recursive', self.basedir, self.dircap))
        def _test_for_wrong_indices((rc, out, err)):
            self.failUnless('examining 1 of 1\n' in err)
        d.addCallback(_test_for_wrong_indices)
        return d

    def test_cp_with_nonexistent_alias(self):
        # when invoked with an alias or aliases that don't exist, 'tahoe cp'
        # should output a sensible error message rather than a stack trace.
        self.basedir = "cli/Cp/cp_with_nonexistent_alias"
        self.set_up_grid()
        d = self.do_cli("cp", "fake:file1", "fake:file2")
        def _check((rc, out, err)):
            self.failUnlessReallyEqual(rc, 1)
            self.failUnlessIn("error:", err)
        d.addCallback(_check)
        # 'tahoe cp' actually processes the target argument first, so we need
        # to check to make sure that validation extends to the source
        # argument.
        d.addCallback(lambda ign: self.do_cli("create-alias", "tahoe"))
        d.addCallback(lambda ign: self.do_cli("cp", "fake:file1",
                                              "tahoe:file2"))
        d.addCallback(_check)
        return d

    def test_unicode_dirnames(self):
        self.basedir = "cli/Cp/unicode_dirnames"

        fn1 = os.path.join(unicode(self.basedir), u"\u00C4rtonwall")
        try:
            fn1_arg = fn1.encode(get_io_encoding())
            del fn1_arg # hush pyflakes
            artonwall_arg = u"\u00C4rtonwall".encode(get_io_encoding())
        except UnicodeEncodeError:
            raise unittest.SkipTest("A non-ASCII command argument could not be encoded on this platform.")

        self.skip_if_cannot_represent_filename(fn1)

        self.set_up_grid()

        d = self.do_cli("create-alias", "tahoe")
        d.addCallback(lambda res: self.do_cli("mkdir", "tahoe:test/" + artonwall_arg))
        d.addCallback(lambda res: self.do_cli("cp", "-r", "tahoe:test", "tahoe:test2"))
        d.addCallback(lambda res: self.do_cli("ls", "tahoe:test2"))
        def _check((rc, out, err)):
            try:
                unicode_to_output(u"\u00C4rtonwall")
            except UnicodeEncodeError:
                self.failUnlessReallyEqual(rc, 1)
                self.failUnlessReallyEqual(out, "")
                self.failUnlessIn(quote_output(u"\u00C4rtonwall"), err)
                self.failUnlessIn("files whose names could not be converted", err)
            else:
                self.failUnlessReallyEqual(rc, 0)
                self.failUnlessReallyEqual(out.decode(get_io_encoding()), u"\u00C4rtonwall\n")
                self.failUnlessReallyEqual(err, "")
        d.addCallback(_check)

        return d

    def test_cp_replaces_mutable_file_contents(self):
        self.basedir = "cli/Cp/cp_replaces_mutable_file_contents"
        self.set_up_grid()

        # Write a test file, which we'll copy to the grid.
        test_txt_path = os.path.join(self.basedir, "test.txt")
        test_txt_contents = "foo bar baz"
        f = open(test_txt_path, "w")
        f.write(test_txt_contents)
        f.close()

        d = self.do_cli("create-alias", "tahoe")
        d.addCallback(lambda ignored:
            self.do_cli("mkdir", "tahoe:test"))
        # We have to use 'tahoe put' here because 'tahoe cp' doesn't
        # know how to make mutable files at the destination.
        d.addCallback(lambda ignored:
            self.do_cli("put", "--mutable", test_txt_path, "tahoe:test/test.txt"))
        d.addCallback(lambda ignored:
            self.do_cli("get", "tahoe:test/test.txt"))
        def _check((rc, out, err)):
            self.failUnlessEqual(rc, 0)
            self.failUnlessEqual(out, test_txt_contents)
        d.addCallback(_check)

        # We'll do ls --json to get the read uri and write uri for the
        # file we've just uploaded.
        d.addCallback(lambda ignored:
            self.do_cli("ls", "--json", "tahoe:test/test.txt"))
        def _get_test_txt_uris((rc, out, err)):
            self.failUnlessEqual(rc, 0)
            filetype, data = simplejson.loads(out)

            self.failUnlessEqual(filetype, "filenode")
            self.failUnless(data['mutable'])

            self.failUnlessIn("rw_uri", data)
            self.rw_uri = to_str(data["rw_uri"])
            self.failUnlessIn("ro_uri", data)
            self.ro_uri = to_str(data["ro_uri"])
        d.addCallback(_get_test_txt_uris)

        # Now make a new file to copy in place of test.txt.
        new_txt_path = os.path.join(self.basedir, "new.txt")
        new_txt_contents = "baz bar foo" * 100000
        f = open(new_txt_path, "w")
        f.write(new_txt_contents)
        f.close()

        # Copy the new file on top of the old file.
        d.addCallback(lambda ignored:
            self.do_cli("cp", new_txt_path, "tahoe:test/test.txt"))

        # If we get test.txt now, we should see the new data.
        d.addCallback(lambda ignored:
            self.do_cli("get", "tahoe:test/test.txt"))
        d.addCallback(lambda (rc, out, err):
            self.failUnlessEqual(out, new_txt_contents))
        # If we get the json of the new file, we should see that the old
        # uri is there
        d.addCallback(lambda ignored:
            self.do_cli("ls", "--json", "tahoe:test/test.txt"))
        def _check_json((rc, out, err)):
            self.failUnlessEqual(rc, 0)
            filetype, data = simplejson.loads(out)

            self.failUnlessEqual(filetype, "filenode")
            self.failUnless(data['mutable'])

            self.failUnlessIn("ro_uri", data)
            self.failUnlessEqual(to_str(data["ro_uri"]), self.ro_uri)
            self.failUnlessIn("rw_uri", data)
            self.failUnlessEqual(to_str(data["rw_uri"]), self.rw_uri)
        d.addCallback(_check_json)

        # and, finally, doing a GET directly on one of the old uris
        # should give us the new contents.
        d.addCallback(lambda ignored:
            self.do_cli("get", self.rw_uri))
        d.addCallback(lambda (rc, out, err):
            self.failUnlessEqual(out, new_txt_contents))
        # Now copy the old test.txt without an explicit destination
        # file. tahoe cp will match it to the existing file and
        # overwrite it appropriately.
        d.addCallback(lambda ignored:
            self.do_cli("cp", test_txt_path, "tahoe:test"))
        d.addCallback(lambda ignored:
            self.do_cli("get", "tahoe:test/test.txt"))
        d.addCallback(lambda (rc, out, err):
            self.failUnlessEqual(out, test_txt_contents))
        d.addCallback(lambda ignored:
            self.do_cli("ls", "--json", "tahoe:test/test.txt"))
        d.addCallback(_check_json)
        d.addCallback(lambda ignored:
            self.do_cli("get", self.rw_uri))
        d.addCallback(lambda (rc, out, err):
            self.failUnlessEqual(out, test_txt_contents))

        # Now we'll make a more complicated directory structure.
        # test2/
        # test2/mutable1
        # test2/mutable2
        # test2/imm1
        # test2/imm2
        imm_test_txt_path = os.path.join(self.basedir, "imm_test.txt")
        imm_test_txt_contents = test_txt_contents * 10000
        fileutil.write(imm_test_txt_path, imm_test_txt_contents)
        d.addCallback(lambda ignored:
            self.do_cli("mkdir", "tahoe:test2"))
        d.addCallback(lambda ignored:
            self.do_cli("put", "--mutable", new_txt_path,
                        "tahoe:test2/mutable1"))
        d.addCallback(lambda ignored:
            self.do_cli("put", "--mutable", new_txt_path,
                        "tahoe:test2/mutable2"))
        d.addCallback(lambda ignored:
            self.do_cli('put', new_txt_path, "tahoe:test2/imm1"))
        d.addCallback(lambda ignored:
            self.do_cli("put", imm_test_txt_path, "tahoe:test2/imm2"))
        d.addCallback(lambda ignored:
            self.do_cli("ls", "--json", "tahoe:test2"))
        def _process_directory_json((rc, out, err)):
            self.failUnlessEqual(rc, 0)

            filetype, data = simplejson.loads(out)
            self.failUnlessEqual(filetype, "dirnode")
            self.failUnless(data['mutable'])
            self.failUnlessIn("children", data)
            children = data['children']

            # Store the URIs for later use.
            self.childuris = {}
            for k in ["mutable1", "mutable2", "imm1", "imm2"]:
                self.failUnlessIn(k, children)
                childtype, childdata = children[k]
                self.failUnlessEqual(childtype, "filenode")
                if "mutable" in k:
                    self.failUnless(childdata['mutable'])
                    self.failUnlessIn("rw_uri", childdata)
                    uri_key = "rw_uri"
                else:
                    self.failIf(childdata['mutable'])
                    self.failUnlessIn("ro_uri", childdata)
                    uri_key = "ro_uri"
                self.childuris[k] = to_str(childdata[uri_key])
        d.addCallback(_process_directory_json)
        # Now build a local directory to copy into place, like the following:
        # source1/
        # source1/mutable1
        # source1/mutable2
        # source1/imm1
        # source1/imm3
        def _build_local_directory(ignored):
            source1_path = os.path.join(self.basedir, "source1")
            fileutil.make_dirs(source1_path)
            for fn in ("mutable1", "mutable2", "imm1", "imm3"):
                fileutil.write(os.path.join(source1_path, fn), fn * 1000)
            self.source1_path = source1_path
        d.addCallback(_build_local_directory)
        d.addCallback(lambda ignored:
            self.do_cli("cp", "-r", self.source1_path, "tahoe:test2"))

        # We expect that mutable1 and mutable2 are overwritten in-place,
        # so they'll retain their URIs but have different content.
        def _process_file_json((rc, out, err), fn):
            self.failUnlessEqual(rc, 0)
            filetype, data = simplejson.loads(out)
            self.failUnlessEqual(filetype, "filenode")

            if "mutable" in fn:
                self.failUnless(data['mutable'])
                self.failUnlessIn("rw_uri", data)
                self.failUnlessEqual(to_str(data["rw_uri"]), self.childuris[fn])
            else:
                self.failIf(data['mutable'])
                self.failUnlessIn("ro_uri", data)
                self.failIfEqual(to_str(data["ro_uri"]), self.childuris[fn])

        for fn in ("mutable1", "mutable2"):
            d.addCallback(lambda ignored, fn=fn:
                self.do_cli("get", "tahoe:test2/%s" % fn))
            d.addCallback(lambda (rc, out, err), fn=fn:
                self.failUnlessEqual(out, fn * 1000))
            d.addCallback(lambda ignored, fn=fn:
                self.do_cli("ls", "--json", "tahoe:test2/%s" % fn))
            d.addCallback(_process_file_json, fn=fn)

        # imm1 should have been replaced, so both its uri and content
        # should be different.
        d.addCallback(lambda ignored:
            self.do_cli("get", "tahoe:test2/imm1"))
        d.addCallback(lambda (rc, out, err):
            self.failUnlessEqual(out, "imm1" * 1000))
        d.addCallback(lambda ignored:
            self.do_cli("ls", "--json", "tahoe:test2/imm1"))
        d.addCallback(_process_file_json, fn="imm1")

        # imm3 should have been created.
        d.addCallback(lambda ignored:
            self.do_cli("get", "tahoe:test2/imm3"))
        d.addCallback(lambda (rc, out, err):
            self.failUnlessEqual(out, "imm3" * 1000))

        # imm2 should be exactly as we left it, since our newly-copied
        # directory didn't contain an imm2 entry.
        d.addCallback(lambda ignored:
            self.do_cli("get", "tahoe:test2/imm2"))
        d.addCallback(lambda (rc, out, err):
            self.failUnlessEqual(out, imm_test_txt_contents))
        d.addCallback(lambda ignored:
            self.do_cli("ls", "--json", "tahoe:test2/imm2"))
        def _process_imm2_json((rc, out, err)):
            self.failUnlessEqual(rc, 0)
            filetype, data = simplejson.loads(out)
            self.failUnlessEqual(filetype, "filenode")
            self.failIf(data['mutable'])
            self.failUnlessIn("ro_uri", data)
            self.failUnlessEqual(to_str(data["ro_uri"]), self.childuris["imm2"])
        d.addCallback(_process_imm2_json)
        return d

    def test_cp_overwrite_readonly_mutable_file(self):
        # tahoe cp should print an error when asked to overwrite a
        # mutable file that it can't overwrite.
        self.basedir = "cli/Cp/overwrite_readonly_mutable_file"
        self.set_up_grid()

        # This is our initial file. We'll link its readcap into the
        # tahoe: alias.
        test_file_path = os.path.join(self.basedir, "test_file.txt")
        test_file_contents = "This is a test file."
        fileutil.write(test_file_path, test_file_contents)

        # This is our replacement file. We'll try and fail to upload it
        # over the readcap that we linked into the tahoe: alias.
        replacement_file_path = os.path.join(self.basedir, "replacement.txt")
        replacement_file_contents = "These are new contents."
        fileutil.write(replacement_file_path, replacement_file_contents)

        d = self.do_cli("create-alias", "tahoe:")
        d.addCallback(lambda ignored:
            self.do_cli("put", "--mutable", test_file_path))
        def _get_test_uri((rc, out, err)):
            self.failUnlessEqual(rc, 0)
            # this should be a write uri
            self._test_write_uri = out
        d.addCallback(_get_test_uri)
        d.addCallback(lambda ignored:
            self.do_cli("ls", "--json", self._test_write_uri))
        def _process_test_json((rc, out, err)):
            self.failUnlessEqual(rc, 0)
            filetype, data = simplejson.loads(out)

            self.failUnlessEqual(filetype, "filenode")
            self.failUnless(data['mutable'])
            self.failUnlessIn("ro_uri", data)
            self._test_read_uri = to_str(data["ro_uri"])
        d.addCallback(_process_test_json)
        # Now we'll link the readonly URI into the tahoe: alias.
        d.addCallback(lambda ignored:
            self.do_cli("ln", self._test_read_uri, "tahoe:test_file.txt"))
        d.addCallback(lambda (rc, out, err):
            self.failUnlessEqual(rc, 0))
        # Let's grab the json of that to make sure that we did it right.
        d.addCallback(lambda ignored:
            self.do_cli("ls", "--json", "tahoe:"))
        def _process_tahoe_json((rc, out, err)):
            self.failUnlessEqual(rc, 0)

            filetype, data = simplejson.loads(out)
            self.failUnlessEqual(filetype, "dirnode")
            self.failUnlessIn("children", data)
            kiddata = data['children']

            self.failUnlessIn("test_file.txt", kiddata)
            testtype, testdata = kiddata['test_file.txt']
            self.failUnlessEqual(testtype, "filenode")
            self.failUnless(testdata['mutable'])
            self.failUnlessIn("ro_uri", testdata)
            self.failUnlessEqual(to_str(testdata["ro_uri"]), self._test_read_uri)
            self.failIfIn("rw_uri", testdata)
        d.addCallback(_process_tahoe_json)
        # Okay, now we're going to try uploading another mutable file in
        # place of that one. We should get an error.
        d.addCallback(lambda ignored:
            self.do_cli("cp", replacement_file_path, "tahoe:test_file.txt"))
        def _check_error_message((rc, out, err)):
            self.failUnlessEqual(rc, 1)
            self.failUnlessIn("replace or update requested with read-only cap", err)
        d.addCallback(_check_error_message)
        # Make extra sure that that didn't work.
        d.addCallback(lambda ignored:
            self.do_cli("get", "tahoe:test_file.txt"))
        d.addCallback(lambda (rc, out, err):
            self.failUnlessEqual(out, test_file_contents))
        d.addCallback(lambda ignored:
            self.do_cli("get", self._test_read_uri))
        d.addCallback(lambda (rc, out, err):
            self.failUnlessEqual(out, test_file_contents))
        # Now we'll do it without an explicit destination.
        d.addCallback(lambda ignored:
            self.do_cli("cp", test_file_path, "tahoe:"))
        d.addCallback(_check_error_message)
        d.addCallback(lambda ignored:
            self.do_cli("get", "tahoe:test_file.txt"))
        d.addCallback(lambda (rc, out, err):
            self.failUnlessEqual(out, test_file_contents))
        d.addCallback(lambda ignored:
            self.do_cli("get", self._test_read_uri))
        d.addCallback(lambda (rc, out, err):
            self.failUnlessEqual(out, test_file_contents))
        # Now we'll link a readonly file into a subdirectory.
        d.addCallback(lambda ignored:
            self.do_cli("mkdir", "tahoe:testdir"))
        d.addCallback(lambda (rc, out, err):
            self.failUnlessEqual(rc, 0))
        d.addCallback(lambda ignored:
            self.do_cli("ln", self._test_read_uri, "tahoe:test/file2.txt"))
        d.addCallback(lambda (rc, out, err):
            self.failUnlessEqual(rc, 0))

        test_dir_path = os.path.join(self.basedir, "test")
        fileutil.make_dirs(test_dir_path)
        for f in ("file1.txt", "file2.txt"):
            fileutil.write(os.path.join(test_dir_path, f), f * 10000)

        d.addCallback(lambda ignored:
            self.do_cli("cp", "-r", test_dir_path, "tahoe:test"))
        d.addCallback(_check_error_message)
        d.addCallback(lambda ignored:
            self.do_cli("ls", "--json", "tahoe:test"))
        def _got_testdir_json((rc, out, err)):
            self.failUnlessEqual(rc, 0)

            filetype, data = simplejson.loads(out)
            self.failUnlessEqual(filetype, "dirnode")

            self.failUnlessIn("children", data)
            childdata = data['children']

            self.failUnlessIn("file2.txt", childdata)
            file2type, file2data = childdata['file2.txt']
            self.failUnlessEqual(file2type, "filenode")
            self.failUnless(file2data['mutable'])
            self.failUnlessIn("ro_uri", file2data)
            self.failUnlessEqual(to_str(file2data["ro_uri"]), self._test_read_uri)
            self.failIfIn("rw_uri", file2data)
        d.addCallback(_got_testdir_json)
        return d


class Backup(GridTestMixin, CLITestMixin, StallMixin, unittest.TestCase):

    def writeto(self, path, data):
        full_path = os.path.join(self.basedir, "home", path)
        fileutil.make_dirs(os.path.dirname(full_path))
        fileutil.write(full_path, data)

    def count_output(self, out):
        mo = re.search(r"(\d)+ files uploaded \((\d+) reused\), "
                        "(\d)+ files skipped, "
                        "(\d+) directories created \((\d+) reused\), "
                        "(\d+) directories skipped", out)
        return [int(s) for s in mo.groups()]

    def count_output2(self, out):
        mo = re.search(r"(\d)+ files checked, (\d+) directories checked", out)
        return [int(s) for s in mo.groups()]

    def test_backup(self):
        self.basedir = "cli/Backup/backup"
        self.set_up_grid()

        # is the backupdb available? If so, we test that a second backup does
        # not create new directories.
        hush = StringIO()
        bdb = backupdb.get_backupdb(os.path.join(self.basedir, "dbtest"),
                                    hush)
        self.failUnless(bdb)

        # create a small local directory with a couple of files
        source = os.path.join(self.basedir, "home")
        fileutil.make_dirs(os.path.join(source, "empty"))
        self.writeto("parent/subdir/foo.txt", "foo")
        self.writeto("parent/subdir/bar.txt", "bar\n" * 1000)
        self.writeto("parent/blah.txt", "blah")

        def do_backup(verbose=False):
            cmd = ["backup"]
            if verbose:
                cmd.append("--verbose")
            cmd.append(source)
            cmd.append("tahoe:backups")
            return self.do_cli(*cmd)

        d = self.do_cli("create-alias", "tahoe")

        d.addCallback(lambda res: do_backup())
        def _check0((rc, out, err)):
            self.failUnlessReallyEqual(err, "")
            self.failUnlessReallyEqual(rc, 0)
            fu, fr, fs, dc, dr, ds = self.count_output(out)
            # foo.txt, bar.txt, blah.txt
            self.failUnlessReallyEqual(fu, 3)
            self.failUnlessReallyEqual(fr, 0)
            self.failUnlessReallyEqual(fs, 0)
            # empty, home, home/parent, home/parent/subdir
            self.failUnlessReallyEqual(dc, 4)
            self.failUnlessReallyEqual(dr, 0)
            self.failUnlessReallyEqual(ds, 0)
        d.addCallback(_check0)

        d.addCallback(lambda res: self.do_cli("ls", "--uri", "tahoe:backups"))
        def _check1((rc, out, err)):
            self.failUnlessReallyEqual(err, "")
            self.failUnlessReallyEqual(rc, 0)
            lines = out.split("\n")
            children = dict([line.split() for line in lines if line])
            latest_uri = children["Latest"]
            self.failUnless(latest_uri.startswith("URI:DIR2-CHK:"), latest_uri)
            childnames = children.keys()
            self.failUnlessReallyEqual(sorted(childnames), ["Archives", "Latest"])
        d.addCallback(_check1)
        d.addCallback(lambda res: self.do_cli("ls", "tahoe:backups/Latest"))
        def _check2((rc, out, err)):
            self.failUnlessReallyEqual(err, "")
            self.failUnlessReallyEqual(rc, 0)
            self.failUnlessReallyEqual(sorted(out.split()), ["empty", "parent"])
        d.addCallback(_check2)
        d.addCallback(lambda res: self.do_cli("ls", "tahoe:backups/Latest/empty"))
        def _check2a((rc, out, err)):
            self.failUnlessReallyEqual(err, "")
            self.failUnlessReallyEqual(rc, 0)
            self.failUnlessReallyEqual(out.strip(), "")
        d.addCallback(_check2a)
        d.addCallback(lambda res: self.do_cli("get", "tahoe:backups/Latest/parent/subdir/foo.txt"))
        def _check3((rc, out, err)):
            self.failUnlessReallyEqual(err, "")
            self.failUnlessReallyEqual(rc, 0)
            self.failUnlessReallyEqual(out, "foo")
        d.addCallback(_check3)
        d.addCallback(lambda res: self.do_cli("ls", "tahoe:backups/Archives"))
        def _check4((rc, out, err)):
            self.failUnlessReallyEqual(err, "")
            self.failUnlessReallyEqual(rc, 0)
            self.old_archives = out.split()
            self.failUnlessReallyEqual(len(self.old_archives), 1)
        d.addCallback(_check4)


        d.addCallback(self.stall, 1.1)
        d.addCallback(lambda res: do_backup())
        def _check4a((rc, out, err)):
            # second backup should reuse everything, if the backupdb is
            # available
            self.failUnlessReallyEqual(err, "")
            self.failUnlessReallyEqual(rc, 0)
            fu, fr, fs, dc, dr, ds = self.count_output(out)
            # foo.txt, bar.txt, blah.txt
            self.failUnlessReallyEqual(fu, 0)
            self.failUnlessReallyEqual(fr, 3)
            self.failUnlessReallyEqual(fs, 0)
            # empty, home, home/parent, home/parent/subdir
            self.failUnlessReallyEqual(dc, 0)
            self.failUnlessReallyEqual(dr, 4)
            self.failUnlessReallyEqual(ds, 0)
        d.addCallback(_check4a)

        # sneak into the backupdb, crank back the "last checked"
        # timestamp to force a check on all files
        def _reset_last_checked(res):
            dbfile = os.path.join(self.get_clientdir(),
                                  "private", "backupdb.sqlite")
            self.failUnless(os.path.exists(dbfile), dbfile)
            bdb = backupdb.get_backupdb(dbfile)
            bdb.cursor.execute("UPDATE last_upload SET last_checked=0")
            bdb.cursor.execute("UPDATE directories SET last_checked=0")
            bdb.connection.commit()

        d.addCallback(_reset_last_checked)

        d.addCallback(self.stall, 1.1)
        d.addCallback(lambda res: do_backup(verbose=True))
        def _check4b((rc, out, err)):
            # we should check all files, and re-use all of them. None of
            # the directories should have been changed, so we should
            # re-use all of them too.
            self.failUnlessReallyEqual(err, "")
            self.failUnlessReallyEqual(rc, 0)
            fu, fr, fs, dc, dr, ds = self.count_output(out)
            fchecked, dchecked = self.count_output2(out)
            self.failUnlessReallyEqual(fchecked, 3)
            self.failUnlessReallyEqual(fu, 0)
            self.failUnlessReallyEqual(fr, 3)
            self.failUnlessReallyEqual(fs, 0)
            self.failUnlessReallyEqual(dchecked, 4)
            self.failUnlessReallyEqual(dc, 0)
            self.failUnlessReallyEqual(dr, 4)
            self.failUnlessReallyEqual(ds, 0)
        d.addCallback(_check4b)

        d.addCallback(lambda res: self.do_cli("ls", "tahoe:backups/Archives"))
        def _check5((rc, out, err)):
            self.failUnlessReallyEqual(err, "")
            self.failUnlessReallyEqual(rc, 0)
            self.new_archives = out.split()
            self.failUnlessReallyEqual(len(self.new_archives), 3, out)
            # the original backup should still be the oldest (i.e. sorts
            # alphabetically towards the beginning)
            self.failUnlessReallyEqual(sorted(self.new_archives)[0],
                                 self.old_archives[0])
        d.addCallback(_check5)

        d.addCallback(self.stall, 1.1)
        def _modify(res):
            self.writeto("parent/subdir/foo.txt", "FOOF!")
            # and turn a file into a directory
            os.unlink(os.path.join(source, "parent/blah.txt"))
            os.mkdir(os.path.join(source, "parent/blah.txt"))
            self.writeto("parent/blah.txt/surprise file", "surprise")
            self.writeto("parent/blah.txt/surprisedir/subfile", "surprise")
            # turn a directory into a file
            os.rmdir(os.path.join(source, "empty"))
            self.writeto("empty", "imagine nothing being here")
            return do_backup()
        d.addCallback(_modify)
        def _check5a((rc, out, err)):
            # second backup should reuse bar.txt (if backupdb is available),
            # and upload the rest. None of the directories can be reused.
            self.failUnlessReallyEqual(err, "")
            self.failUnlessReallyEqual(rc, 0)
            fu, fr, fs, dc, dr, ds = self.count_output(out)
            # new foo.txt, surprise file, subfile, empty
            self.failUnlessReallyEqual(fu, 4)
            # old bar.txt
            self.failUnlessReallyEqual(fr, 1)
            self.failUnlessReallyEqual(fs, 0)
            # home, parent, subdir, blah.txt, surprisedir
            self.failUnlessReallyEqual(dc, 5)
            self.failUnlessReallyEqual(dr, 0)
            self.failUnlessReallyEqual(ds, 0)
        d.addCallback(_check5a)
        d.addCallback(lambda res: self.do_cli("ls", "tahoe:backups/Archives"))
        def _check6((rc, out, err)):
            self.failUnlessReallyEqual(err, "")
            self.failUnlessReallyEqual(rc, 0)
            self.new_archives = out.split()
            self.failUnlessReallyEqual(len(self.new_archives), 4)
            self.failUnlessReallyEqual(sorted(self.new_archives)[0],
                                 self.old_archives[0])
        d.addCallback(_check6)
        d.addCallback(lambda res: self.do_cli("get", "tahoe:backups/Latest/parent/subdir/foo.txt"))
        def _check7((rc, out, err)):
            self.failUnlessReallyEqual(err, "")
            self.failUnlessReallyEqual(rc, 0)
            self.failUnlessReallyEqual(out, "FOOF!")
            # the old snapshot should not be modified
            return self.do_cli("get", "tahoe:backups/Archives/%s/parent/subdir/foo.txt" % self.old_archives[0])
        d.addCallback(_check7)
        def _check8((rc, out, err)):
            self.failUnlessReallyEqual(err, "")
            self.failUnlessReallyEqual(rc, 0)
            self.failUnlessReallyEqual(out, "foo")
        d.addCallback(_check8)

        return d

    # on our old dapper buildslave, this test takes a long time (usually
    # 130s), so we have to bump up the default 120s timeout. The create-alias
    # and initial backup alone take 60s, probably because of the handful of
    # dirnodes being created (RSA key generation). The backup between check4
    # and check4a takes 6s, as does the backup before check4b.
    test_backup.timeout = 3000

    def _check_filtering(self, filtered, all, included, excluded):
        filtered = set(filtered)
        all = set(all)
        included = set(included)
        excluded = set(excluded)
        self.failUnlessReallyEqual(filtered, included)
        self.failUnlessReallyEqual(all.difference(filtered), excluded)

    def test_exclude_options(self):
        root_listdir = (u'lib.a', u'_darcs', u'subdir', u'nice_doc.lyx')
        subdir_listdir = (u'another_doc.lyx', u'run_snake_run.py', u'CVS', u'.svn', u'_darcs')
        basedir = "cli/Backup/exclude_options"
        fileutil.make_dirs(basedir)
        nodeurl_path = os.path.join(basedir, 'node.url')
        fileutil.write(nodeurl_path, 'http://example.net:2357/')

        # test simple exclude
        backup_options = cli.BackupOptions()
        backup_options.parseOptions(['--exclude', '*lyx', '--node-directory',
                                     basedir, 'from', 'to'])
        filtered = list(backup_options.filter_listdir(root_listdir))
        self._check_filtering(filtered, root_listdir, (u'lib.a', u'_darcs', u'subdir'),
                              (u'nice_doc.lyx',))
        # multiple exclude
        backup_options = cli.BackupOptions()
        backup_options.parseOptions(['--exclude', '*lyx', '--exclude', 'lib.?', '--node-directory',
                                     basedir, 'from', 'to'])
        filtered = list(backup_options.filter_listdir(root_listdir))
        self._check_filtering(filtered, root_listdir, (u'_darcs', u'subdir'),
                              (u'nice_doc.lyx', u'lib.a'))
        # vcs metadata exclusion
        backup_options = cli.BackupOptions()
        backup_options.parseOptions(['--exclude-vcs', '--node-directory',
                                     basedir, 'from', 'to'])
        filtered = list(backup_options.filter_listdir(subdir_listdir))
        self._check_filtering(filtered, subdir_listdir, (u'another_doc.lyx', u'run_snake_run.py',),
                              (u'CVS', u'.svn', u'_darcs'))
        # read exclude patterns from file
        exclusion_string = "_darcs\n*py\n.svn"
        excl_filepath = os.path.join(basedir, 'exclusion')
        fileutil.write(excl_filepath, exclusion_string)
        backup_options = cli.BackupOptions()
        backup_options.parseOptions(['--exclude-from', excl_filepath, '--node-directory',
                                     basedir, 'from', 'to'])
        filtered = list(backup_options.filter_listdir(subdir_listdir))
        self._check_filtering(filtered, subdir_listdir, (u'another_doc.lyx', u'CVS'),
                              (u'.svn', u'_darcs', u'run_snake_run.py'))
        # test BackupConfigurationError
        self.failUnlessRaises(cli.BackupConfigurationError,
                              backup_options.parseOptions,
                              ['--exclude-from', excl_filepath + '.no', '--node-directory',
                               basedir, 'from', 'to'])

        # test that an iterator works too
        backup_options = cli.BackupOptions()
        backup_options.parseOptions(['--exclude', '*lyx', '--node-directory',
                                     basedir, 'from', 'to'])
        filtered = list(backup_options.filter_listdir(iter(root_listdir)))
        self._check_filtering(filtered, root_listdir, (u'lib.a', u'_darcs', u'subdir'),
                              (u'nice_doc.lyx',))

    def test_exclude_options_unicode(self):
        nice_doc = u"nice_d\u00F8c.lyx"
        try:
            doc_pattern_arg = u"*d\u00F8c*".encode(get_io_encoding())
        except UnicodeEncodeError:
            raise unittest.SkipTest("A non-ASCII command argument could not be encoded on this platform.")

        root_listdir = (u'lib.a', u'_darcs', u'subdir', nice_doc)
        basedir = "cli/Backup/exclude_options_unicode"
        fileutil.make_dirs(basedir)
        nodeurl_path = os.path.join(basedir, 'node.url')
        fileutil.write(nodeurl_path, 'http://example.net:2357/')

        # test simple exclude
        backup_options = cli.BackupOptions()
        backup_options.parseOptions(['--exclude', doc_pattern_arg, '--node-directory',
                                     basedir, 'from', 'to'])
        filtered = list(backup_options.filter_listdir(root_listdir))
        self._check_filtering(filtered, root_listdir, (u'lib.a', u'_darcs', u'subdir'),
                              (nice_doc,))
        # multiple exclude
        backup_options = cli.BackupOptions()
        backup_options.parseOptions(['--exclude', doc_pattern_arg, '--exclude', 'lib.?', '--node-directory',
                                     basedir, 'from', 'to'])
        filtered = list(backup_options.filter_listdir(root_listdir))
        self._check_filtering(filtered, root_listdir, (u'_darcs', u'subdir'),
                             (nice_doc, u'lib.a'))
        # read exclude patterns from file
        exclusion_string = doc_pattern_arg + "\nlib.?"
        excl_filepath = os.path.join(basedir, 'exclusion')
        fileutil.write(excl_filepath, exclusion_string)
        backup_options = cli.BackupOptions()
        backup_options.parseOptions(['--exclude-from', excl_filepath, '--node-directory',
                                     basedir, 'from', 'to'])
        filtered = list(backup_options.filter_listdir(root_listdir))
        self._check_filtering(filtered, root_listdir, (u'_darcs', u'subdir'),
                             (nice_doc, u'lib.a'))

        # test that an iterator works too
        backup_options = cli.BackupOptions()
        backup_options.parseOptions(['--exclude', doc_pattern_arg, '--node-directory',
                                     basedir, 'from', 'to'])
        filtered = list(backup_options.filter_listdir(iter(root_listdir)))
        self._check_filtering(filtered, root_listdir, (u'lib.a', u'_darcs', u'subdir'),
                              (nice_doc,))

    @patch('__builtin__.file')
    def test_exclude_from_tilde_expansion(self, mock):
        basedir = "cli/Backup/exclude_from_tilde_expansion"
        fileutil.make_dirs(basedir)
        nodeurl_path = os.path.join(basedir, 'node.url')
        fileutil.write(nodeurl_path, 'http://example.net:2357/')

        # ensure that tilde expansion is performed on exclude-from argument
        exclude_file = u'~/.tahoe/excludes.dummy'
        backup_options = cli.BackupOptions()

        mock.return_value = StringIO()
        backup_options.parseOptions(['--exclude-from', unicode_to_argv(exclude_file),
                                     '--node-directory', basedir, 'from', 'to'])
        self.failUnlessIn(((abspath_expanduser_unicode(exclude_file),), {}), mock.call_args_list)

    def test_ignore_symlinks(self):
        if not hasattr(os, 'symlink'):
            raise unittest.SkipTest("Symlinks are not supported by Python on this platform.")

        self.basedir = os.path.dirname(self.mktemp())
        self.set_up_grid()

        source = os.path.join(self.basedir, "home")
        self.writeto("foo.txt", "foo")
        os.symlink(os.path.join(source, "foo.txt"), os.path.join(source, "foo2.txt"))

        d = self.do_cli("create-alias", "tahoe")
        d.addCallback(lambda res: self.do_cli("backup", "--verbose", source, "tahoe:test"))

        def _check((rc, out, err)):
            self.failUnlessReallyEqual(rc, 2)
            foo2 = os.path.join(source, "foo2.txt")
            self.failUnlessReallyEqual(err, "WARNING: cannot backup symlink '%s'\n" % foo2)

            fu, fr, fs, dc, dr, ds = self.count_output(out)
            # foo.txt
            self.failUnlessReallyEqual(fu, 1)
            self.failUnlessReallyEqual(fr, 0)
            # foo2.txt
            self.failUnlessReallyEqual(fs, 1)
            # home
            self.failUnlessReallyEqual(dc, 1)
            self.failUnlessReallyEqual(dr, 0)
            self.failUnlessReallyEqual(ds, 0)

        d.addCallback(_check)
        return d

    def test_ignore_unreadable_file(self):
        self.basedir = os.path.dirname(self.mktemp())
        self.set_up_grid()

        source = os.path.join(self.basedir, "home")
        self.writeto("foo.txt", "foo")
        os.chmod(os.path.join(source, "foo.txt"), 0000)

        d = self.do_cli("create-alias", "tahoe")
        d.addCallback(lambda res: self.do_cli("backup", source, "tahoe:test"))

        def _check((rc, out, err)):
            self.failUnlessReallyEqual(rc, 2)
            self.failUnlessReallyEqual(err, "WARNING: permission denied on file %s\n" % os.path.join(source, "foo.txt"))

            fu, fr, fs, dc, dr, ds = self.count_output(out)
            self.failUnlessReallyEqual(fu, 0)
            self.failUnlessReallyEqual(fr, 0)
            # foo.txt
            self.failUnlessReallyEqual(fs, 1)
            # home
            self.failUnlessReallyEqual(dc, 1)
            self.failUnlessReallyEqual(dr, 0)
            self.failUnlessReallyEqual(ds, 0)
        d.addCallback(_check)

        # This is necessary for the temp files to be correctly removed
        def _cleanup(self):
            os.chmod(os.path.join(source, "foo.txt"), 0644)
        d.addCallback(_cleanup)
        d.addErrback(_cleanup)

        return d

    def test_ignore_unreadable_directory(self):
        self.basedir = os.path.dirname(self.mktemp())
        self.set_up_grid()

        source = os.path.join(self.basedir, "home")
        os.mkdir(source)
        os.mkdir(os.path.join(source, "test"))
        os.chmod(os.path.join(source, "test"), 0000)

        d = self.do_cli("create-alias", "tahoe")
        d.addCallback(lambda res: self.do_cli("backup", source, "tahoe:test"))

        def _check((rc, out, err)):
            self.failUnlessReallyEqual(rc, 2)
            self.failUnlessReallyEqual(err, "WARNING: permission denied on directory %s\n" % os.path.join(source, "test"))

            fu, fr, fs, dc, dr, ds = self.count_output(out)
            self.failUnlessReallyEqual(fu, 0)
            self.failUnlessReallyEqual(fr, 0)
            self.failUnlessReallyEqual(fs, 0)
            # home, test
            self.failUnlessReallyEqual(dc, 2)
            self.failUnlessReallyEqual(dr, 0)
            # test
            self.failUnlessReallyEqual(ds, 1)
        d.addCallback(_check)

        # This is necessary for the temp files to be correctly removed
        def _cleanup(self):
            os.chmod(os.path.join(source, "test"), 0655)
        d.addCallback(_cleanup)
        d.addErrback(_cleanup)
        return d

    def test_backup_without_alias(self):
        # 'tahoe backup' should output a sensible error message when invoked
        # without an alias instead of a stack trace.
        self.basedir = os.path.dirname(self.mktemp())
        self.set_up_grid()
        source = os.path.join(self.basedir, "file1")
        d = self.do_cli('backup', source, source)
        def _check((rc, out, err)):
            self.failUnlessReallyEqual(rc, 1)
            self.failUnlessIn("error:", err)
            self.failUnlessReallyEqual(out, "")
        d.addCallback(_check)
        return d

    def test_backup_with_nonexistent_alias(self):
        # 'tahoe backup' should output a sensible error message when invoked
        # with a nonexistent alias.
        self.basedir = os.path.dirname(self.mktemp())
        self.set_up_grid()
        source = os.path.join(self.basedir, "file1")
        d = self.do_cli("backup", source, "nonexistent:" + source)
        def _check((rc, out, err)):
            self.failUnlessReallyEqual(rc, 1)
            self.failUnlessIn("error:", err)
            self.failUnlessIn("nonexistent", err)
            self.failUnlessReallyEqual(out, "")
        d.addCallback(_check)
        return d


class Check(GridTestMixin, CLITestMixin, unittest.TestCase):

    def test_check(self):
        self.basedir = "cli/Check/check"
        self.set_up_grid()
        c0 = self.g.clients[0]
        DATA = "data" * 100
        DATA_uploadable = MutableData(DATA)
        d = c0.create_mutable_file(DATA_uploadable)
        def _stash_uri(n):
            self.uri = n.get_uri()
        d.addCallback(_stash_uri)

        d.addCallback(lambda ign: self.do_cli("check", self.uri))
        def _check1((rc, out, err)):
            self.failUnlessReallyEqual(err, "")
            self.failUnlessReallyEqual(rc, 0)
            lines = out.splitlines()
            self.failUnless("Summary: Healthy" in lines, out)
            self.failUnless(" good-shares: 10 (encoding is 3-of-10)" in lines, out)
        d.addCallback(_check1)

        d.addCallback(lambda ign: self.do_cli("check", "--raw", self.uri))
        def _check2((rc, out, err)):
            self.failUnlessReallyEqual(err, "")
            self.failUnlessReallyEqual(rc, 0)
            data = simplejson.loads(out)
            self.failUnlessReallyEqual(to_str(data["summary"]), "Healthy")
            self.failUnlessReallyEqual(data["results"]["healthy"], True)
        d.addCallback(_check2)

        d.addCallback(lambda ign: c0.upload(upload.Data("literal", convergence="")))
        def _stash_lit_uri(n):
            self.lit_uri = n.get_uri()
        d.addCallback(_stash_lit_uri)

        d.addCallback(lambda ign: self.do_cli("check", self.lit_uri))
        def _check_lit((rc, out, err)):
            self.failUnlessReallyEqual(err, "")
            self.failUnlessReallyEqual(rc, 0)
            lines = out.splitlines()
            self.failUnless("Summary: Healthy (LIT)" in lines, out)
        d.addCallback(_check_lit)

        d.addCallback(lambda ign: self.do_cli("check", "--raw", self.lit_uri))
        def _check_lit_raw((rc, out, err)):
            self.failUnlessReallyEqual(err, "")
            self.failUnlessReallyEqual(rc, 0)
            data = simplejson.loads(out)
            self.failUnlessReallyEqual(data["results"]["healthy"], True)
        d.addCallback(_check_lit_raw)

        d.addCallback(lambda ign: c0.create_immutable_dirnode({}, convergence=""))
        def _stash_lit_dir_uri(n):
            self.lit_dir_uri = n.get_uri()
        d.addCallback(_stash_lit_dir_uri)

        d.addCallback(lambda ign: self.do_cli("check", self.lit_dir_uri))
        d.addCallback(_check_lit)

        d.addCallback(lambda ign: self.do_cli("check", "--raw", self.lit_uri))
        d.addCallback(_check_lit_raw)

        def _clobber_shares(ignored):
            # delete one, corrupt a second
            shares = self.find_uri_shares(self.uri)
            self.failUnlessReallyEqual(len(shares), 10)
            os.unlink(shares[0][2])
            cso = debug.CorruptShareOptions()
            cso.stdout = StringIO()
            cso.parseOptions([shares[1][2]])
            storage_index = uri.from_string(self.uri).get_storage_index()
            self._corrupt_share_line = "  server %s, SI %s, shnum %d" % \
                                       (base32.b2a(shares[1][1]),
                                        base32.b2a(storage_index),
                                        shares[1][0])
            debug.corrupt_share(cso)
        d.addCallback(_clobber_shares)

        d.addCallback(lambda ign: self.do_cli("check", "--verify", self.uri))
        def _check3((rc, out, err)):
            self.failUnlessReallyEqual(err, "")
            self.failUnlessReallyEqual(rc, 0)
            lines = out.splitlines()
            summary = [l for l in lines if l.startswith("Summary")][0]
            self.failUnless("Summary: Unhealthy: 8 shares (enc 3-of-10)"
                            in summary, summary)
            self.failUnless(" good-shares: 8 (encoding is 3-of-10)" in lines, out)
            self.failUnless(" corrupt shares:" in lines, out)
            self.failUnless(self._corrupt_share_line in lines, out)
        d.addCallback(_check3)

        d.addCallback(lambda ign: self.do_cli("check", "--verify", "--raw", self.uri))
        def _check3_raw((rc, out, err)):
            self.failUnlessReallyEqual(err, "")
            self.failUnlessReallyEqual(rc, 0)
            data = simplejson.loads(out)
            self.failUnlessReallyEqual(data["results"]["healthy"], False)
            self.failUnlessIn("Unhealthy: 8 shares (enc 3-of-10)", data["summary"])
            self.failUnlessReallyEqual(data["results"]["count-shares-good"], 8)
            self.failUnlessReallyEqual(data["results"]["count-corrupt-shares"], 1)
            self.failUnlessIn("list-corrupt-shares", data["results"])
        d.addCallback(_check3_raw)

        d.addCallback(lambda ign:
                      self.do_cli("check", "--verify", "--repair", self.uri))
        def _check4((rc, out, err)):
            self.failUnlessReallyEqual(err, "")
            self.failUnlessReallyEqual(rc, 0)
            lines = out.splitlines()
            self.failUnless("Summary: not healthy" in lines, out)
            self.failUnless(" good-shares: 8 (encoding is 3-of-10)" in lines, out)
            self.failUnless(" corrupt shares:" in lines, out)
            self.failUnless(self._corrupt_share_line in lines, out)
            self.failUnless(" repair successful" in lines, out)
        d.addCallback(_check4)

        d.addCallback(lambda ign:
                      self.do_cli("check", "--verify", "--repair", self.uri))
        def _check5((rc, out, err)):
            self.failUnlessReallyEqual(err, "")
            self.failUnlessReallyEqual(rc, 0)
            lines = out.splitlines()
            self.failUnless("Summary: healthy" in lines, out)
            self.failUnless(" good-shares: 10 (encoding is 3-of-10)" in lines, out)
            self.failIf(" corrupt shares:" in lines, out)
        d.addCallback(_check5)

        return d

    def test_deep_check(self):
        self.basedir = "cli/Check/deep_check"
        self.set_up_grid()
        c0 = self.g.clients[0]
        self.uris = {}
        self.fileurls = {}
        DATA = "data" * 100
        quoted_good = quote_output(u"g\u00F6\u00F6d")

        d = c0.create_dirnode()
        def _stash_root_and_create_file(n):
            self.rootnode = n
            self.rooturi = n.get_uri()
            return n.add_file(u"g\u00F6\u00F6d", upload.Data(DATA, convergence=""))
        d.addCallback(_stash_root_and_create_file)
        def _stash_uri(fn, which):
            self.uris[which] = fn.get_uri()
            return fn
        d.addCallback(_stash_uri, u"g\u00F6\u00F6d")
        d.addCallback(lambda ign:
                      self.rootnode.add_file(u"small",
                                           upload.Data("literal",
                                                        convergence="")))
        d.addCallback(_stash_uri, "small")
        d.addCallback(lambda ign:
            c0.create_mutable_file(MutableData(DATA+"1")))
        d.addCallback(lambda fn: self.rootnode.set_node(u"mutable", fn))
        d.addCallback(_stash_uri, "mutable")

        d.addCallback(lambda ign: self.do_cli("deep-check", self.rooturi))
        def _check1((rc, out, err)):
            self.failUnlessReallyEqual(err, "")
            self.failUnlessReallyEqual(rc, 0)
            lines = out.splitlines()
            self.failUnless("done: 4 objects checked, 4 healthy, 0 unhealthy"
                            in lines, out)
        d.addCallback(_check1)

        # root
        # root/g\u00F6\u00F6d
        # root/small
        # root/mutable

        d.addCallback(lambda ign: self.do_cli("deep-check", "--verbose",
                                              self.rooturi))
        def _check2((rc, out, err)):
            self.failUnlessReallyEqual(err, "")
            self.failUnlessReallyEqual(rc, 0)
            lines = out.splitlines()
            self.failUnless("'<root>': Healthy" in lines, out)
            self.failUnless("'small': Healthy (LIT)" in lines, out)
            self.failUnless((quoted_good + ": Healthy") in lines, out)
            self.failUnless("'mutable': Healthy" in lines, out)
            self.failUnless("done: 4 objects checked, 4 healthy, 0 unhealthy"
                            in lines, out)
        d.addCallback(_check2)

        d.addCallback(lambda ign: self.do_cli("stats", self.rooturi))
        def _check_stats((rc, out, err)):
            self.failUnlessReallyEqual(err, "")
            self.failUnlessReallyEqual(rc, 0)
            lines = out.splitlines()
            self.failUnlessIn(" count-immutable-files: 1", lines)
            self.failUnlessIn("   count-mutable-files: 1", lines)
            self.failUnlessIn("   count-literal-files: 1", lines)
            self.failUnlessIn("     count-directories: 1", lines)
            self.failUnlessIn("  size-immutable-files: 400", lines)
            self.failUnlessIn("Size Histogram:", lines)
            self.failUnlessIn("   4-10   : 1    (10 B, 10 B)", lines)
            self.failUnlessIn(" 317-1000 : 1    (1000 B, 1000 B)", lines)
        d.addCallback(_check_stats)

        def _clobber_shares(ignored):
            shares = self.find_uri_shares(self.uris[u"g\u00F6\u00F6d"])
            self.failUnlessReallyEqual(len(shares), 10)
            os.unlink(shares[0][2])

            shares = self.find_uri_shares(self.uris["mutable"])
            cso = debug.CorruptShareOptions()
            cso.stdout = StringIO()
            cso.parseOptions([shares[1][2]])
            storage_index = uri.from_string(self.uris["mutable"]).get_storage_index()
            self._corrupt_share_line = " corrupt: server %s, SI %s, shnum %d" % \
                                       (base32.b2a(shares[1][1]),
                                        base32.b2a(storage_index),
                                        shares[1][0])
            debug.corrupt_share(cso)
        d.addCallback(_clobber_shares)

        # root
        # root/g\u00F6\u00F6d  [9 shares]
        # root/small
        # root/mutable [1 corrupt share]

        d.addCallback(lambda ign:
                      self.do_cli("deep-check", "--verbose", self.rooturi))
        def _check3((rc, out, err)):
            self.failUnlessReallyEqual(err, "")
            self.failUnlessReallyEqual(rc, 0)
            lines = out.splitlines()
            self.failUnless("'<root>': Healthy" in lines, out)
            self.failUnless("'small': Healthy (LIT)" in lines, out)
            self.failUnless("'mutable': Healthy" in lines, out) # needs verifier
            self.failUnless((quoted_good + ": Not Healthy: 9 shares (enc 3-of-10)") in lines, out)
            self.failIf(self._corrupt_share_line in lines, out)
            self.failUnless("done: 4 objects checked, 3 healthy, 1 unhealthy"
                            in lines, out)
        d.addCallback(_check3)

        d.addCallback(lambda ign:
                      self.do_cli("deep-check", "--verbose", "--verify",
                                  self.rooturi))
        def _check4((rc, out, err)):
            self.failUnlessReallyEqual(err, "")
            self.failUnlessReallyEqual(rc, 0)
            lines = out.splitlines()
            self.failUnless("'<root>': Healthy" in lines, out)
            self.failUnless("'small': Healthy (LIT)" in lines, out)
            mutable = [l for l in lines if l.startswith("'mutable'")][0]
            self.failUnless(mutable.startswith("'mutable': Unhealthy: 9 shares (enc 3-of-10)"),
                            mutable)
            self.failUnless(self._corrupt_share_line in lines, out)
            self.failUnless((quoted_good + ": Not Healthy: 9 shares (enc 3-of-10)") in lines, out)
            self.failUnless("done: 4 objects checked, 2 healthy, 2 unhealthy"
                            in lines, out)
        d.addCallback(_check4)

        d.addCallback(lambda ign:
                      self.do_cli("deep-check", "--raw",
                                  self.rooturi))
        def _check5((rc, out, err)):
            self.failUnlessReallyEqual(err, "")
            self.failUnlessReallyEqual(rc, 0)
            lines = out.splitlines()
            units = [simplejson.loads(line) for line in lines]
            # root, small, g\u00F6\u00F6d, mutable,  stats
            self.failUnlessReallyEqual(len(units), 4+1)
        d.addCallback(_check5)

        d.addCallback(lambda ign:
                      self.do_cli("deep-check",
                                  "--verbose", "--verify", "--repair",
                                  self.rooturi))
        def _check6((rc, out, err)):
            self.failUnlessReallyEqual(err, "")
            self.failUnlessReallyEqual(rc, 0)
            lines = out.splitlines()
            self.failUnless("'<root>': healthy" in lines, out)
            self.failUnless("'small': healthy" in lines, out)
            self.failUnless("'mutable': not healthy" in lines, out)
            self.failUnless(self._corrupt_share_line in lines, out)
            self.failUnless((quoted_good + ": not healthy") in lines, out)
            self.failUnless("done: 4 objects checked" in lines, out)
            self.failUnless(" pre-repair: 2 healthy, 2 unhealthy" in lines, out)
            self.failUnless(" 2 repairs attempted, 2 successful, 0 failed"
                            in lines, out)
            self.failUnless(" post-repair: 4 healthy, 0 unhealthy" in lines,out)
        d.addCallback(_check6)

        # now add a subdir, and a file below that, then make the subdir
        # unrecoverable

        d.addCallback(lambda ign: self.rootnode.create_subdirectory(u"subdir"))
        d.addCallback(_stash_uri, "subdir")
        d.addCallback(lambda fn:
                      fn.add_file(u"subfile", upload.Data(DATA+"2", "")))
        d.addCallback(lambda ign:
                      self.delete_shares_numbered(self.uris["subdir"],
                                                  range(10)))

        # root
        # rootg\u00F6\u00F6d/
        # root/small
        # root/mutable
        # root/subdir [unrecoverable: 0 shares]
        # root/subfile

        d.addCallback(lambda ign: self.do_cli("manifest", self.rooturi))
        def _manifest_failed((rc, out, err)):
            self.failIfEqual(rc, 0)
            self.failUnlessIn("ERROR: UnrecoverableFileError", err)
            # the fatal directory should still show up, as the last line
            self.failUnlessIn(" subdir\n", out)
        d.addCallback(_manifest_failed)

        d.addCallback(lambda ign: self.do_cli("deep-check", self.rooturi))
        def _deep_check_failed((rc, out, err)):
            self.failIfEqual(rc, 0)
            self.failUnlessIn("ERROR: UnrecoverableFileError", err)
            # we want to make sure that the error indication is the last
            # thing that gets emitted
            self.failIf("done:" in out, out)
        d.addCallback(_deep_check_failed)

        # this test is disabled until the deep-repair response to an
        # unrepairable directory is fixed. The failure-to-repair should not
        # throw an exception, but the failure-to-traverse that follows
        # should throw UnrecoverableFileError.

        #d.addCallback(lambda ign:
        #              self.do_cli("deep-check", "--repair", self.rooturi))
        #def _deep_check_repair_failed((rc, out, err)):
        #    self.failIfEqual(rc, 0)
        #    print err
        #    self.failUnlessIn("ERROR: UnrecoverableFileError", err)
        #    self.failIf("done:" in out, out)
        #d.addCallback(_deep_check_repair_failed)

        return d

    def test_check_without_alias(self):
        # 'tahoe check' should output a sensible error message if it needs to
        # find the default alias and can't
        self.basedir = "cli/Check/check_without_alias"
        self.set_up_grid()
        d = self.do_cli("check")
        def _check((rc, out, err)):
            self.failUnlessReallyEqual(rc, 1)
            self.failUnlessIn("error:", err)
            self.failUnlessReallyEqual(out, "")
        d.addCallback(_check)
        d.addCallback(lambda ign: self.do_cli("deep-check"))
        d.addCallback(_check)
        return d

    def test_check_with_nonexistent_alias(self):
        # 'tahoe check' should output a sensible error message if it needs to
        # find an alias and can't.
        self.basedir = "cli/Check/check_with_nonexistent_alias"
        self.set_up_grid()
        d = self.do_cli("check", "nonexistent:")
        def _check((rc, out, err)):
            self.failUnlessReallyEqual(rc, 1)
            self.failUnlessIn("error:", err)
            self.failUnlessIn("nonexistent", err)
            self.failUnlessReallyEqual(out, "")
        d.addCallback(_check)
        return d


class Errors(GridTestMixin, CLITestMixin, unittest.TestCase):
    def test_get(self):
        self.basedir = "cli/Errors/get"
        self.set_up_grid()
        c0 = self.g.clients[0]
        self.fileurls = {}
        DATA = "data" * 100
        d = c0.upload(upload.Data(DATA, convergence=""))
        def _stash_bad(ur):
            self.uri_1share = ur.get_uri()
            self.delete_shares_numbered(ur.get_uri(), range(1,10))
        d.addCallback(_stash_bad)

        # the download is abandoned as soon as it's clear that we won't get
        # enough shares. The one remaining share might be in either the
        # COMPLETE or the PENDING state.
        in_complete_msg = "ran out of shares: complete=sh0 pending= overdue= unused= need 3"
        in_pending_msg = "ran out of shares: complete= pending=Share(sh0-on-fob7vqgd) overdue= unused= need 3"

        d.addCallback(lambda ign: self.do_cli("get", self.uri_1share))
        def _check1((rc, out, err)):
            self.failIfEqual(rc, 0)
            self.failUnless("410 Gone" in err, err)
            self.failUnlessIn("NotEnoughSharesError: ", err)
            self.failUnless(in_complete_msg in err or in_pending_msg in err,
                            err)
        d.addCallback(_check1)

        targetf = os.path.join(self.basedir, "output")
        d.addCallback(lambda ign: self.do_cli("get", self.uri_1share, targetf))
        def _check2((rc, out, err)):
            self.failIfEqual(rc, 0)
            self.failUnless("410 Gone" in err, err)
            self.failUnlessIn("NotEnoughSharesError: ", err)
            self.failUnless(in_complete_msg in err or in_pending_msg in err,
                            err)
            self.failIf(os.path.exists(targetf))
        d.addCallback(_check2)

        return d

    def test_broken_socket(self):
        # When the http connection breaks (such as when node.url is overwritten
        # by a confused user), a user friendly error message should be printed.
        self.basedir = "cli/Errors/test_broken_socket"
        self.set_up_grid()

        # Simulate a connection error
        def _socket_error(*args, **kwargs):
            raise socket_error('test error')
        self.patch(allmydata.scripts.common_http.httplib.HTTPConnection,
                   "endheaders", _socket_error)

        d = self.do_cli("mkdir")
        def _check_invalid((rc,stdout,stderr)):
            self.failIfEqual(rc, 0)
            self.failUnlessIn("Error trying to connect to http://127.0.0.1", stderr)
        d.addCallback(_check_invalid)
        return d


class Get(GridTestMixin, CLITestMixin, unittest.TestCase):
    def test_get_without_alias(self):
        # 'tahoe get' should output a useful error message when invoked
        # without an explicit alias and when the default 'tahoe' alias
        # hasn't been created yet.
        self.basedir = "cli/Get/get_without_alias"
        self.set_up_grid()
        d = self.do_cli('get', 'file')
        def _check((rc, out, err)):
            self.failUnlessReallyEqual(rc, 1)
            self.failUnlessIn("error:", err)
            self.failUnlessReallyEqual(out, "")
        d.addCallback(_check)
        return d

    def test_get_with_nonexistent_alias(self):
        # 'tahoe get' should output a useful error message when invoked with
        # an explicit alias that doesn't exist.
        self.basedir = "cli/Get/get_with_nonexistent_alias"
        self.set_up_grid()
        d = self.do_cli("get", "nonexistent:file")
        def _check((rc, out, err)):
            self.failUnlessReallyEqual(rc, 1)
            self.failUnlessIn("error:", err)
            self.failUnlessIn("nonexistent", err)
            self.failUnlessReallyEqual(out, "")
        d.addCallback(_check)
        return d


class Manifest(GridTestMixin, CLITestMixin, unittest.TestCase):
    def test_manifest_without_alias(self):
        # 'tahoe manifest' should output a useful error message when invoked
        # without an explicit alias when the default 'tahoe' alias is
        # missing.
        self.basedir = "cli/Manifest/manifest_without_alias"
        self.set_up_grid()
        d = self.do_cli("manifest")
        def _check((rc, out, err)):
            self.failUnlessReallyEqual(rc, 1)
            self.failUnlessIn("error:", err)
            self.failUnlessReallyEqual(out, "")
        d.addCallback(_check)
        return d

    def test_manifest_with_nonexistent_alias(self):
        # 'tahoe manifest' should output a useful error message when invoked
        # with an explicit alias that doesn't exist.
        self.basedir = "cli/Manifest/manifest_with_nonexistent_alias"
        self.set_up_grid()
        d = self.do_cli("manifest", "nonexistent:")
        def _check((rc, out, err)):
            self.failUnlessReallyEqual(rc, 1)
            self.failUnlessIn("error:", err)
            self.failUnlessIn("nonexistent", err)
            self.failUnlessReallyEqual(out, "")
        d.addCallback(_check)
        return d


class Mkdir(GridTestMixin, CLITestMixin, unittest.TestCase):
    def test_mkdir(self):
        self.basedir = os.path.dirname(self.mktemp())
        self.set_up_grid()

        d = self.do_cli("create-alias", "tahoe")
        d.addCallback(lambda res: self.do_cli("mkdir", "test"))
        def _check((rc, out, err)):
            self.failUnlessReallyEqual(rc, 0)
            self.failUnlessReallyEqual(err, "")
            self.failUnlessIn("URI:", out)
        d.addCallback(_check)

        return d

    def test_mkdir_mutable_type(self):
        self.basedir = os.path.dirname(self.mktemp())
        self.set_up_grid()
        d = self.do_cli("create-alias", "tahoe")
        def _check((rc, out, err), st):
            self.failUnlessReallyEqual(rc, 0)
            self.failUnlessReallyEqual(err, "")
            self.failUnlessIn(st, out)
            return out
        def _mkdir(ign, mutable_type, uri_prefix, dirname):
            d2 = self.do_cli("mkdir", "--format="+mutable_type, dirname)
            d2.addCallback(_check, uri_prefix)
            def _stash_filecap(cap):
                u = uri.from_string(cap)
                fn_uri = u.get_filenode_cap()
                self._filecap = fn_uri.to_string()
            d2.addCallback(_stash_filecap)
            d2.addCallback(lambda ign: self.do_cli("ls", "--json", dirname))
            d2.addCallback(_check, uri_prefix)
            d2.addCallback(lambda ign: self.do_cli("ls", "--json", self._filecap))
            d2.addCallback(_check, '"format": "%s"' % (mutable_type.upper(),))
            return d2

        d.addCallback(_mkdir, "sdmf", "URI:DIR2", "tahoe:foo")
        d.addCallback(_mkdir, "SDMF", "URI:DIR2", "tahoe:foo2")
        d.addCallback(_mkdir, "mdmf", "URI:DIR2-MDMF", "tahoe:bar")
        d.addCallback(_mkdir, "MDMF", "URI:DIR2-MDMF", "tahoe:bar2")
        return d

    def test_mkdir_mutable_type_unlinked(self):
        self.basedir = os.path.dirname(self.mktemp())
        self.set_up_grid()
        d = self.do_cli("mkdir", "--format=SDMF")
        def _check((rc, out, err), st):
            self.failUnlessReallyEqual(rc, 0)
            self.failUnlessReallyEqual(err, "")
            self.failUnlessIn(st, out)
            return out
        d.addCallback(_check, "URI:DIR2")
        def _stash_dircap(cap):
            self._dircap = cap
            # Now we're going to feed the cap into uri.from_string...
            u = uri.from_string(cap)
            # ...grab the underlying filenode uri.
            fn_uri = u.get_filenode_cap()
            # ...and stash that.
            self._filecap = fn_uri.to_string()
        d.addCallback(_stash_dircap)
        d.addCallback(lambda res: self.do_cli("ls", "--json",
                                              self._filecap))
        d.addCallback(_check, '"format": "SDMF"')
        d.addCallback(lambda res: self.do_cli("mkdir", "--format=MDMF"))
        d.addCallback(_check, "URI:DIR2-MDMF")
        d.addCallback(_stash_dircap)
        d.addCallback(lambda res: self.do_cli("ls", "--json",
                                              self._filecap))
        d.addCallback(_check, '"format": "MDMF"')
        return d

    def test_mkdir_bad_mutable_type(self):
        o = cli.MakeDirectoryOptions()
        self.failUnlessRaises(usage.UsageError,
                              o.parseOptions,
                              ["--format=LDMF"])

    def test_mkdir_unicode(self):
        self.basedir = os.path.dirname(self.mktemp())
        self.set_up_grid()

        try:
            motorhead_arg = u"tahoe:Mot\u00F6rhead".encode(get_io_encoding())
        except UnicodeEncodeError:
            raise unittest.SkipTest("A non-ASCII command argument could not be encoded on this platform.")

        d = self.do_cli("create-alias", "tahoe")
        d.addCallback(lambda res: self.do_cli("mkdir", motorhead_arg))
        def _check((rc, out, err)):
            self.failUnlessReallyEqual(rc, 0)
            self.failUnlessReallyEqual(err, "")
            self.failUnlessIn("URI:", out)
        d.addCallback(_check)

        return d

    def test_mkdir_with_nonexistent_alias(self):
        # when invoked with an alias that doesn't exist, 'tahoe mkdir' should
        # output a sensible error message rather than a stack trace.
        self.basedir = "cli/Mkdir/mkdir_with_nonexistent_alias"
        self.set_up_grid()
        d = self.do_cli("mkdir", "havasu:")
        def _check((rc, out, err)):
            self.failUnlessReallyEqual(rc, 1)
            self.failUnlessIn("error:", err)
            self.failUnlessReallyEqual(out, "")
        d.addCallback(_check)
        return d


class Unlink(GridTestMixin, CLITestMixin, unittest.TestCase):
    command = "unlink"

    def _create_test_file(self):
        data = "puppies" * 1000
        path = os.path.join(self.basedir, "datafile")
        fileutil.write(path, data)
        self.datafile = path

    def test_unlink_without_alias(self):
        # 'tahoe unlink' should behave sensibly when invoked without an explicit
        # alias before the default 'tahoe' alias has been created.
        self.basedir = "cli/Unlink/%s_without_alias" % (self.command,)
        self.set_up_grid()
        d = self.do_cli(self.command, "afile")
        def _check((rc, out, err)):
            self.failUnlessReallyEqual(rc, 1)
            self.failUnlessIn("error:", err)
            self.failUnlessReallyEqual(out, "")
        d.addCallback(_check)

        d.addCallback(lambda ign: self.do_cli(self.command, "afile"))
        d.addCallback(_check)
        return d

    def test_unlink_with_nonexistent_alias(self):
        # 'tahoe unlink' should behave sensibly when invoked with an explicit
        # alias that doesn't exist.
        self.basedir = "cli/Unlink/%s_with_nonexistent_alias" % (self.command,)
        self.set_up_grid()
        d = self.do_cli(self.command, "nonexistent:afile")
        def _check((rc, out, err)):
            self.failUnlessReallyEqual(rc, 1)
            self.failUnlessIn("error:", err)
            self.failUnlessIn("nonexistent", err)
            self.failUnlessReallyEqual(out, "")
        d.addCallback(_check)

        d.addCallback(lambda ign: self.do_cli(self.command, "nonexistent:afile"))
        d.addCallback(_check)
        return d

    def test_unlink_without_path(self):
        # 'tahoe unlink' should give a sensible error message when invoked without a path.
        self.basedir = "cli/Unlink/%s_without_path" % (self.command,)
        self.set_up_grid()
        self._create_test_file()
        d = self.do_cli("create-alias", "tahoe")
        d.addCallback(lambda ign: self.do_cli("put", self.datafile, "tahoe:test"))
        def _do_unlink((rc, out, err)):
            self.failUnlessReallyEqual(rc, 0)
            self.failUnless(out.startswith("URI:"), out)
            return self.do_cli(self.command, out.strip('\n'))
        d.addCallback(_do_unlink)

        def _check((rc, out, err)):
            self.failUnlessReallyEqual(rc, 1)
            self.failUnlessIn("'tahoe %s'" % (self.command,), err)
            self.failUnlessIn("path must be given", err)
            self.failUnlessReallyEqual(out, "")
        d.addCallback(_check)
        return d


class Rm(Unlink):
    """Test that 'tahoe rm' behaves in the same way as 'tahoe unlink'."""
    command = "rm"


class Stats(GridTestMixin, CLITestMixin, unittest.TestCase):
    def test_empty_directory(self):
        self.basedir = "cli/Stats/empty_directory"
        self.set_up_grid()
        c0 = self.g.clients[0]
        self.fileurls = {}
        d = c0.create_dirnode()
        def _stash_root(n):
            self.rootnode = n
            self.rooturi = n.get_uri()
        d.addCallback(_stash_root)

        # make sure we can get stats on an empty directory too
        d.addCallback(lambda ign: self.do_cli("stats", self.rooturi))
        def _check_stats((rc, out, err)):
            self.failUnlessReallyEqual(err, "")
            self.failUnlessReallyEqual(rc, 0)
            lines = out.splitlines()
            self.failUnlessIn(" count-immutable-files: 0", lines)
            self.failUnlessIn("   count-mutable-files: 0", lines)
            self.failUnlessIn("   count-literal-files: 0", lines)
            self.failUnlessIn("     count-directories: 1", lines)
            self.failUnlessIn("  size-immutable-files: 0", lines)
            self.failIfIn("Size Histogram:", lines)
        d.addCallback(_check_stats)

        return d

    def test_stats_without_alias(self):
        # when invoked with no explicit alias and before the default 'tahoe'
        # alias is created, 'tahoe stats' should output an informative error
        # message, not a stack trace.
        self.basedir = "cli/Stats/stats_without_alias"
        self.set_up_grid()
        d = self.do_cli("stats")
        def _check((rc, out, err)):
            self.failUnlessReallyEqual(rc, 1)
            self.failUnlessIn("error:", err)
            self.failUnlessReallyEqual(out, "")
        d.addCallback(_check)
        return d

    def test_stats_with_nonexistent_alias(self):
        # when invoked with an explicit alias that doesn't exist,
        # 'tahoe stats' should output a useful error message.
        self.basedir = "cli/Stats/stats_with_nonexistent_alias"
        self.set_up_grid()
        d = self.do_cli("stats", "havasu:")
        def _check((rc, out, err)):
            self.failUnlessReallyEqual(rc, 1)
            self.failUnlessIn("error:", err)
            self.failUnlessReallyEqual(out, "")
        d.addCallback(_check)
        return d


class Webopen(GridTestMixin, CLITestMixin, unittest.TestCase):
    def test_webopen_with_nonexistent_alias(self):
        # when invoked with an alias that doesn't exist, 'tahoe webopen'
        # should output an informative error message instead of a stack
        # trace.
        self.basedir = "cli/Webopen/webopen_with_nonexistent_alias"
        self.set_up_grid()
        d = self.do_cli("webopen", "fake:")
        def _check((rc, out, err)):
            self.failUnlessReallyEqual(rc, 1)
            self.failUnlessIn("error:", err)
            self.failUnlessReallyEqual(out, "")
        d.addCallback(_check)
        return d

    def test_webopen(self):
        # TODO: replace with @patch that supports Deferreds.
        import webbrowser
        def call_webbrowser_open(url):
            self.failUnlessIn(self.alias_uri.replace(':', '%3A'), url)
            self.webbrowser_open_called = True
        def _cleanup(res):
            webbrowser.open = self.old_webbrowser_open
            return res

        self.old_webbrowser_open = webbrowser.open
        try:
            webbrowser.open = call_webbrowser_open

            self.basedir = "cli/Webopen/webopen"
            self.set_up_grid()
            d = self.do_cli("create-alias", "alias:")
            def _check_alias((rc, out, err)):
                self.failUnlessReallyEqual(rc, 0, repr((rc, out, err)))
                self.failUnlessIn("Alias 'alias' created", out)
                self.failUnlessReallyEqual(err, "")
                self.alias_uri = get_aliases(self.get_clientdir())["alias"]
            d.addCallback(_check_alias)
            d.addCallback(lambda res: self.do_cli("webopen", "alias:"))
            def _check_webopen((rc, out, err)):
                self.failUnlessReallyEqual(rc, 0, repr((rc, out, err)))
                self.failUnlessReallyEqual(out, "")
                self.failUnlessReallyEqual(err, "")
                self.failUnless(self.webbrowser_open_called)
            d.addCallback(_check_webopen)
            d.addBoth(_cleanup)
        except:
            _cleanup(None)
            raise
        return d
