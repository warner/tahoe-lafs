
from twisted.python import usage

class GenerateKeypairOptions(usage.Options):
    def getSynopsis(self):
        return "Usage: tahoe admin generate-keypair"

    def getUsage(self, width=None):
        t = usage.Options.getUsage(self, width)
        t += """
Generate an ECDSA192 public/private keypair, dumped to stdout as two lines of
base32-encoded text.

"""
        return t

# in base32, the signing key is 39 chars long, and the verifying key is 77.
# in base62, the signing key is 33 chars long, and the verifying key is 65.
# in base64, the signing key is 32 chars long, and the verifying key is 64.
#
# We can't use base64 because we want to reserve punctuation and preserve
# cut-and-pasteability. The base62 encoding is not significantly shorter than
# the base32 form, and the minor usability improvement is not worth the
# documentation/specification confusion of using a non-standard encoding. So
# we stick with base32.

def make_keypair():
    from allmydata.util.ecdsa import SigningKey, NIST192p
    from allmydata.util import base32
    privkey = SigningKey.generate(curve=NIST192p)
    privkey_vs = "priv-v0-%s" % base32.b2a(privkey.to_string())
    pubkey = privkey.get_verifying_key()
    pubkey_vs = "pub-v0-%s" % base32.b2a(pubkey.to_string())
    return privkey_vs, pubkey_vs

def print_keypair(options):
    out = options.stdout
    privkey_vs, pubkey_vs = make_keypair()
    print >>out, "private:", privkey_vs
    print >>out, "public:", pubkey_vs

class DerivePubkeyOptions(usage.Options):
    def parseArgs(self, privkey):
        self.privkey = privkey

    def getSynopsis(self):
        return "Usage: tahoe admin derive-pubkey PRIVKEY"

    def getUsage(self, width=None):
        t = usage.Options.getUsage(self, width)
        t += """
Given a private (signing) key that was previously generated with
generate-keypair, derive the public key and print it to stdout.

"""
        return t

def derive_pubkey(options):
    out = options.stdout
    err = options.stderr
    from allmydata.util.ecdsa import SigningKey, NIST192p
    from allmydata.util import base32
    privkey_vs = options.privkey
    if not privkey_vs.startswith("priv-v0-"):
        print >>err, "private key must look like 'priv-v0-...', not '%s'" % privkey_vs
        return 1
    privkey_s = privkey_vs[len("priv-v0-"):]
    sk = SigningKey.from_string(base32.a2b(privkey_s), curve=NIST192p)
    vk = sk.get_verifying_key()
    pubkey_vs = "pub-v0-%s" % base32.b2a(vk.to_string())
    print >>out, "private:", privkey_vs
    print >>out, "public:", pubkey_vs
    return 0

class AdminCommand(usage.Options):
    subCommands = [
        ("generate-keypair", None, GenerateKeypairOptions,
         "Generate a public/private keypair, write to stdout."),
        ("derive-pubkey", None, DerivePubkeyOptions,
         "Derive a public key from a private key."),
        ]
    def postOptions(self):
        if not hasattr(self, 'subOptions'):
            raise usage.UsageError("must specify a subcommand")
    def getSynopsis(self):
        return "Usage: tahoe admin SUBCOMMAND"
    def getUsage(self, width=None):
        #t = usage.Options.getUsage(self, width)
        t = """
Subcommands:
    tahoe admin generate-keypair    Generate a public/private keypair,
                                    write to stdout.

Please run e.g. 'tahoe admin generate-keypair --help' for more details on
each subcommand.
"""
        return t

subDispatch = {
    "generate-keypair": print_keypair,
    "derive-pubkey": derive_pubkey,
    }

def do_admin(options):
    so = options.subOptions
    so.stdout = options.stdout
    so.stderr = options.stderr
    f = subDispatch[options.subCommand]
    return f(so)


subCommands = [
    ["admin", None, AdminCommand, "admin subcommands: use 'tahoe admin' for a list"],
    ]

dispatch = {
    "admin": do_admin,
    }
