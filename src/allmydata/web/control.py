
import time
from nevow.util import resource_filename
from nevow import rend
from twisted.web import static
from twisted.web.resource import Resource
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

class ControlPanel(Resource):
    def __init__(self, client):
        Resource.__init__(self)
        self.client = client
        # putChild("") makes /control/KEY/ work (as opposed to /control/KEY
        # without the trailing slash), which lets us use relative links from
        # this page
        self.putChild("", self)
        self.putChild("clients", Clients(self.client))

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
