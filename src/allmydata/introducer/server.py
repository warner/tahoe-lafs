
import time, os.path
from zope.interface import implements
from twisted.application import service
from foolscap.api import Referenceable
import allmydata
from allmydata import node
from allmydata.util import log, base32, idlib
from allmydata.introducer.interfaces import \
     RIIntroducerPublisherAndSubscriberService_v2
from allmydata.introducer.common import convert_announcement_v1_to_v2, \
     convert_announcement_v2_to_v1, unsign, make_index

class IntroducerNode(node.Node):
    PORTNUMFILE = "introducer.port"
    NODETYPE = "introducer"
    GENERATED_FILES = ['introducer.furl']

    def __init__(self, basedir="."):
        node.Node.__init__(self, basedir)
        self.read_config()
        self.init_introducer()
        webport = self.get_config("node", "web.port", None)
        if webport:
            self.init_web(webport) # strports string

    def init_introducer(self):
        introducerservice = IntroducerService(self.basedir)
        self.add_service(introducerservice)

        d = self.when_tub_ready()
        def _publish(res):
            self.introducer_url = self.tub.registerReference(introducerservice,
                                                             "introducer")
            self.log(" introducer is at %s" % self.introducer_url,
                     umid="qF2L9A")
            self.write_config("introducer.furl", self.introducer_url + "\n")
        d.addCallback(_publish)
        d.addErrback(log.err, facility="tahoe.init",
                     level=log.BAD, umid="UaNs9A")

    def init_web(self, webport):
        self.log("init_web(webport=%s)", args=(webport,), umid="2bUygA")

        from allmydata.webish import IntroducerWebishServer
        nodeurl_path = os.path.join(self.basedir, "node.url")
        ws = IntroducerWebishServer(self, webport, nodeurl_path)
        self.add_service(ws)

class SubscriberAdapter_v1: # for_v1
    """I wrap a RemoteReference that points at an old v1 subscriber, enabling
    it to be treated like a v2 subscriber.
    """

    def __init__(self, original):
        self.original = original
    def __eq__(self, them):
        return self.original == them
    def __ne__(self, them):
        return self.original != them
    def __hash__(self):
        return hash(self.original)
    def getRemoteTubID(self):
        return self.original.getRemoteTubID()
    def getSturdyRef(self):
        return self.original.getSturdyRef()
    def getPeer(self):
        return self.original.getPeer()
    def callRemote(self, methname, *args, **kwargs):
        m = getattr(self, "wrap_" + methname)
        return m(*args, **kwargs)
    def wrap_announce_v2(self, announcements):
        anns_v1 = [convert_announcement_v2_to_v1(ann) for ann in announcements]
        return self.original.callRemote("announce", set(anns_v1))
    def wrap_set_encoding_parameters(self, parameters):
        return self.original.callRemote("set_encoding_parameters", parameters)
    def notifyOnDisconnect(self, *args, **kwargs):
        return self.original.notifyOnDisconnect(*args, **kwargs)

class IntroducerService(service.MultiService, Referenceable):
    implements(RIIntroducerPublisherAndSubscriberService_v2)
    name = "introducer"
    VERSION = { "http://allmydata.org/tahoe/protocols/introducer/v1":
                 { },
                "application-version": str(allmydata.__full_version__),
                }

    def __init__(self, basedir="."):
        service.MultiService.__init__(self)
        self.introducer_url = None
        # 'index' is (service_name, tubid)
        self._announcements = {} # dict of index ->
                                 # (ann_s, canary, ann_d, timestamp)

        # ann_d is cleaned up (nickname is always unicode, servicename is
        # always ascii, etc, even though simplejson.loads sometimes returns
        # either)

        # self._subscribers is a dict mapping servicename to subscriptions
        # 'subscriptions' is a dict mapping rref to a subscription
        # 'subscription' is a tuple of (subscriber_info, timestamp)
        # 'subscriber_info' is a dict, provided directly for v2 clients, or
        # synthesized for v1 clients. The expected keys are:
        #  version, nickname, app-versions, my-version, oldest-supported
        self._subscribers = {}

        # self._stub_client_announcements contains the information provided
        # by v1 clients. We stash this so we can match it up with their
        # subscriptions.
        self._stub_client_announcements = {} # maps tubid to sinfo # for_v1

        self._debug_counts = {"inbound_message": 0,
                              "inbound_duplicate": 0,
                              "inbound_update": 0,
                              "outbound_message": 0,
                              "outbound_announcements": 0,
                              "inbound_subscribe": 0}
        self._debug_outstanding = 0 # also covers SubscriberAdapter_v1

    def _debug_retired(self, res):
        self._debug_outstanding -= 1
        return res

    def log(self, *args, **kwargs):
        if "facility" not in kwargs:
            kwargs["facility"] = "tahoe.introducer.server"
        return log.msg(*args, **kwargs)

    def get_announcements(self):
        return self._announcements
    def get_subscribers(self):
        """Return a list of (service_name, when, subscriber_info, rref) for
        all subscribers. subscriber_info is a dict with the following keys:
        version, nickname, app-versions, my-version, oldest-supported"""
        s = []
        for service_name, subscriptions in self._subscribers.items():
            for rref,(subscriber_info,when) in subscriptions.items():
                s.append( (service_name, when, subscriber_info, rref) )
        return s

    def remote_get_version(self):
        return self.VERSION

    def remote_publish(self, ann_s): # for_v1
        lp = self.log("introducer: old (v1) announcement published: %s"
                      % (ann_s,), umid="6zGOIw")
        ann_v2 = convert_announcement_v1_to_v2(ann_s)
        return self.publish(ann_v2, None, lp)

    def remote_publish_v2(self, ann_s, canary):
        lp = self.log("introducer: announcement (v2) published", umid="L2QXkQ")
        return self.publish(ann_s, canary, lp)

    def publish(self, ann_s, canary, lp):
        try:
            self._publish(ann_s, canary, lp)
        except:
            log.err(format="Introducer.remote_publish failed on %(ann)s",
                    ann=ann_s,
                    level=log.UNUSUAL, parent=lp, umid="620rWA")
            raise

    def _publish(self, ann_s, canary, lp):
        self._debug_counts["inbound_message"] += 1
        self.log("introducer: announcement published: %s" % (ann_s,),
                 umid="wKHgCw")
        ann_d, key = unsign(ann_s) # might raise BadSignatureError
        index = make_index(ann_d, key)

        service_name = str(ann_d["service-name"])
        if service_name == "stub_client": # for_v1
            self._attach_stub_client(ann_d, index, lp)
            return

        if index in self._announcements:
            (old_ann_s, canary, ann_d, timestamp) = self._announcements[index]
            if old_ann_s == ann_s:
                self.log("but we already knew it, ignoring", level=log.NOISY,
                         umid="myxzLw")
                self._debug_counts["inbound_duplicate"] += 1
                return
            else:
                self.log("old announcement being updated", level=log.NOISY,
                         umid="304r9g")
                self._debug_counts["inbound_update"] += 1
        self._announcements[index] = (ann_s, canary, ann_d, time.time())
        #if canary:
        #    canary.notifyOnDisconnect ...
        # use a CanaryWatcher? with cw.is_connected()?
        # actually we just want foolscap to give rref.is_connected(), since
        # this is only for the status display

        for s in self._subscribers.get(service_name, []):
            self._debug_counts["outbound_message"] += 1
            self._debug_counts["outbound_announcements"] += 1
            self._debug_outstanding += 1
            d = s.callRemote("announce_v2", set([ann_s]))
            d.addBoth(self._debug_retired)
            d.addErrback(log.err,
                         format="subscriber errored on announcement %(ann)s",
                         ann=ann_s, facility="tahoe.introducer",
                         level=log.UNUSUAL, umid="jfGMXQ")

    def _attach_stub_client(self, ann_d, index, lp):
        # There might be a v1 subscriber for whom this is a stub_client.
        # We might have received the subscription before the stub_client
        # announcement, in which case we now need to fix up the record in
        # self._subscriptions .

        # record it for later, in case the stub_client arrived before the
        # subscription
        subscriber_info = self._get_subscriber_info_from_ann_d(ann_d)
        ann_tubid = index[1]
        self._stub_client_announcements[ann_tubid] = subscriber_info

        lp2 = self.log("stub_client announcement, "
                       "looking for matching subscriber",
                       parent=lp, level=log.NOISY, umid="BTywDg")

        for sn in self._subscribers:
            s = self._subscribers[sn]
            for (subscriber, info) in s.items():
                # we correlate these by looking for a subscriber whose tubid
                # matches this announcement
                sub_tubid = base32.a2b(subscriber.getRemoteTubID()) # binary
                if sub_tubid == ann_tubid:
                    self.log(format="found a match, nodeid=%(nodeid)s",
                             nodeid=idlib.nodeid_b2a(sub_tubid),
                             level=log.NOISY, parent=lp2, umid="xsWs1A")
                    # found a match. Does it need info?
                    if not info[0]:
                        self.log(format="replacing info",
                                 level=log.NOISY, parent=lp2, umid="m5kxwA")
                        # yup
                        s[subscriber] = (subscriber_info, info[1])
            # and we don't remember or announce stub_clients beyond what we
            # need to get the subscriber_info set up

    def _get_subscriber_info_from_ann_d(self, ann_d): # for_v1
        sinfo = { "version": ann_d["version"],
                  "nickname": ann_d["nickname"],
                  "app-versions": ann_d["app-versions"],
                  "my-version": ann_d["my-version"],
                  "oldest-supported": ann_d["oldest-supported"],
                  }
        return sinfo

    def remote_subscribe(self, subscriber, service_name): # for_v1
        self.log("introducer: old (v1) subscription[%s] request at %s"
                 % (service_name, subscriber), umid="hJlGUg")
        return self.add_subscriber(SubscriberAdapter_v1(subscriber),
                                   service_name, None)

    def remote_subscribe_v2(self, subscriber, service_name, subscriber_info):
        self.log("introducer: subscription[%s] request at %s"
                 % (service_name, subscriber), umid="U3uzLg")
        return self.add_subscriber(subscriber, service_name, subscriber_info)

    def add_subscriber(self, subscriber, service_name, subscriber_info):
        self._debug_counts["inbound_subscribe"] += 1
        if service_name not in self._subscribers:
            self._subscribers[service_name] = {}
        subscribers = self._subscribers[service_name]
        if subscriber in subscribers:
            self.log("but they're already subscribed, ignoring",
                     level=log.UNUSUAL, umid="Sy9EfA")
            return

        if not subscriber_info: # for_v1
            # v1 clients don't provide subscriber_info, but they should
            # publish a 'stub client' record which contains the same
            # information. If we've already received this, it will be in
            # self._stub_client_announcements
            tubid_b32 = subscriber.getRemoteTubID()
            tubid = base32.a2b(tubid_b32)
            if tubid in self._stub_client_announcements:
                subscriber_info = self._stub_client_announcements[tubid]

        subscribers[subscriber] = (subscriber_info, time.time())
        def _remove():
            self.log("introducer: unsubscribing[%s] %s" % (service_name,
                                                           subscriber),
                     umid="vYGcJg")
            subscribers.pop(subscriber, None)
        subscriber.notifyOnDisconnect(_remove)

        # now tell them about any announcements they're interested in
        announcements = set( [ ann_s
                               for idx,(ann_s,canary,ann_d,when)
                               in self._announcements.items()
                               if idx[0] == service_name] )
        if announcements:
            self._debug_counts["outbound_message"] += 1
            self._debug_counts["outbound_announcements"] += len(announcements)
            self._debug_outstanding += 1
            d = subscriber.callRemote("announce_v2", announcements)
            d.addBoth(self._debug_retired)
            d.addErrback(log.err,
                         format="subscriber errored during subscribe %(anns)s",
                         anns=announcements, facility="tahoe.introducer",
                         level=log.UNUSUAL, umid="mtZepQ")
            return d
