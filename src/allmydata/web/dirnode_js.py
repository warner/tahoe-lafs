from nevow import rend
from allmydata.web.common import getxmlfile

class DirnodeJS(rend.Page):
    docFactory = getxmlfile("dirnode.xhtml")
    def render_sample(self, ctx, data):
        return ctx.tag["sample"]

