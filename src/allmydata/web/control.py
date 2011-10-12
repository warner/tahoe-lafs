
from nevow.util import resource_filename
from twisted.web import static
from twisted.web.resource import Resource
from hashlib import sha256

from allmydata.web.common import WebError

def sfile(name):
    return static.File(resource_filename("allmydata.web", name))
def contents(name):
    return open(resource_filename("allmydata.web", name), "rb").read()

class ControlPanel(Resource):
    def __init__(self, client):
        Resource.__init__(self)
        self.client = client
        # putChild("") makes /control/KEY/ work (as opposed to /control/KEY
        # without the trailing slash), which lets us use relative links from
        # this page
        self.putChild("", self)

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
