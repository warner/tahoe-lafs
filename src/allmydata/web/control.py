
import time
from twisted.internet import address
from twisted.web import static
from twisted.web.resource import Resource
from nevow.util import resource_filename
from nevow import rend, tags as T
from hashlib import sha256

from allmydata.web.common import getxmlfile, WebError, abbreviate_size

def sfile(name):
    return static.File(resource_filename("allmydata.web", name))
def contents(name):
    return open(resource_filename("allmydata.web", name), "rb").read()

class Clients(rend.Page):
    addSlash = True
    docFactory = getxmlfile("clients.xhtml")
    def __init__(self, client):
        rend.Page.__init__(self, client)
        self.client = client

    def data_clients(self, ctx, data):
        a = self.client.get_accountant()
        if a:
            return sorted(a.get_all_accounts(),
                          key=lambda account: account.get_nickname())
        return []

    def render_client_row(self, ctx, account):
        c = account.get_connection_status()
        if c["connected"]:
            cs = "Yes: from %s" % c["last_connected_from"]
        elif c["last_connected_from"]:
            # there is a window (between Account creation and our connection
            # to the 'rxFURL' receiver) during which the Account exists but
            # we've never connected to it. So c["last_connected_from"] can be
            # None. Also the pseudo-accounts ("anonymous" and "starter")
            # never have connection data.
            cs = "No: last from %s" % c["last_connected_from"]
        else:
            cs = "Never"

        ctx.fillSlots("nickname", account.get_nickname())
        ctx.fillSlots("clientid", account.get_id())
        ctx.fillSlots("connected-bool", c["connected"])
        ctx.fillSlots("connected", cs)

        TIME_FORMAT = "%H:%M:%S %d-%b-%Y"
        if c["connected"]:
            since = time.strftime(TIME_FORMAT,
                                  time.localtime(c["connected_since"]))
        elif c["last_seen"]:
            since = time.strftime(TIME_FORMAT,
                                  time.localtime(c["last_seen"]))
        else:
            since = ""
        ctx.fillSlots("since", since)
        created = ""
        if c["created"]:
            created = time.strftime(TIME_FORMAT, time.localtime(c["created"]))
        ctx.fillSlots("created", created)
        ctx.fillSlots("usage", abbreviate_size(account.get_current_usage()))
        return ctx.tag

class Servers(rend.Page):
    addSlash = True
    docFactory = getxmlfile("servers.xhtml")
    def __init__(self, client):
        rend.Page.__init__(self, client)
        self.client = client

    def data_known_storage_servers(self, ctx, data):
        sb = self.client.get_storage_broker()
        return len(sb.get_all_serverids())

    def data_connected_storage_servers(self, ctx, data):
        sb = self.client.get_storage_broker()
        return len(sb.get_connected_servers())

    def data_services(self, ctx, data):
        sb = self.client.get_storage_broker()
        return sorted(sb.get_known_servers(), key=lambda s: s.get_nickname())

    def render_service_row(self, ctx, server):
        nodeid = server.get_serverid()

        ctx.fillSlots("peerid", server.get_longname())
        ctx.fillSlots("nickname", server.get_nickname())
        rhost = server.get_remote_host()
        if rhost:
            if nodeid == self.client.nodeid:
                rhost_s = "(loopback)"
            elif isinstance(rhost, address.IPv4Address):
                rhost_s = "%s:%d" % (rhost.host, rhost.port)
            else:
                rhost_s = str(rhost)
            connected = "Yes: to " + rhost_s
            since = server.get_last_connect_time()
        else:
            connected = "No"
            since = server.get_last_loss_time()
        announced = server.get_announcement_time()
        announcement = server.get_announcement()
        version = announcement["my-version"]

        status = server.get_account_status()
        def _format_status(status):
            # WRS= FFF FFT FTT TTT
            if not status.get("save",True):
                return "deleted: all shares deleted"
            if not status.get("read",True):
                return "disabled: no read or write"
            if not status.get("write",True):
                return "frozen: read, but no write"
            return "normal: full read+write"
        ctx.fillSlots("status", _format_status(status))

        message = server.get_account_message()
        def _format_message(msg):
            bits = T.span()
            if "message" in msg:
                bits[msg["message"]]
            keys = set(msg.keys())
            keys.discard("message")
            if keys:
                keys = sorted(keys)
                for k in keys:
                    bits[T.br()]
                    bits["%s: %s" % (k, msg[k])]
            return bits
        ctx.fillSlots("server_message", _format_message(message))

        # consider this:
        #  cache the usage, with a timestamp
        #  if the usage is more than 5 minutes out of date:
        #    put a "?" here
        #    and send queries to update it
        #  that means get_claimed_usage() returns immediately, can return
        #  None, and fires off requests in the background.
        TIME_FORMAT = "%H:%M:%S %d-%b-%Y"

        bytes,when = server.get_claimed_usage()
        if bytes is None:
            usage = T.span(title="no data")["?"]
        else:
            when = time.strftime(TIME_FORMAT, time.localtime(when))
            usage = T.span(title="as of %s" % when)[abbreviate_size(bytes)]
        ctx.fillSlots("usage", usage)

        ctx.fillSlots("connected", connected)
        ctx.fillSlots("connected-bool", bool(rhost))
        ctx.fillSlots("since", time.strftime(TIME_FORMAT,
                                             time.localtime(since)))
        ctx.fillSlots("announced", time.strftime(TIME_FORMAT,
                                                 time.localtime(announced)))
        ctx.fillSlots("version", version)

        return ctx.tag

class ControlPanel(Resource):
    def __init__(self, client):
        Resource.__init__(self)
        self.client = client
        # putChild("") makes /control/KEY/ work (as opposed to /control/KEY
        # without the trailing slash), which lets us use relative links from
        # this page
        self.putChild("", self)
        self.putChild("clients", Clients(self.client))
        self.putChild("servers", Servers(self.client))

    def render_GET(self, request):
        return contents("control.html")

class ControlPanelGuard(Resource):
    def __init__(self, client):
        Resource.__init__(self)
        self.client = client

    def render_GET(self, request):
        return "I want a key. Look in ~/.tahoe/private/control.key\n"

    def getChild(self, name, request):
        key = self.client.get_control_url_key()
        # constant-time comparison
        if sha256(key).digest() != sha256(name).digest():
            raise WebError("bad key in /control/KEY request\n")
        return ControlPanel(self.client)
