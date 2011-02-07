
from zope.interface import Interface
from foolscap.api import StringConstraint, TupleOf, SetOf, DictOf, Any, \
    RemoteInterface, Referenceable
from old import RIIntroducerSubscriberClient_v1
FURL = StringConstraint(1000)

# old introducer protocol (v1):
#
# Announcements are (FURL, service_name, remoteinterface_name,
#                    nickname, my_version, oldest_supported)
#  the (FURL, service_name, remoteinterface_name) refer to the service being
#  announced. The (nickname, my_version, oldest_supported) refer to the
#  client as a whole. The my_version/oldest_supported strings can be parsed
#  by an allmydata.util.version.Version instance, and then compared. The
#  first goal is to make sure that nodes are not confused by speaking to an
#  incompatible peer. The second goal is to enable the development of
#  backwards-compatibility code.

Announcement_v1 = TupleOf(FURL, str, str,
                          str, str, str)

# new protocol: Announcements are strings, a JSON serialized 3-tuple of (msg,
# sig, pubkey). More details to come.
Announcement_v2 = str

class RIIntroducerSubscriberClient_v2(RemoteInterface):
    __remote_name__ = "RIIntroducerSubscriberClient_v2.tahoe.allmydata.com"

    def announce_v2(announcements=SetOf(Announcement_v2)):
        """I accept announcements from the publisher."""
        return None

    def set_encoding_parameters(parameters=(int, int, int)):
        """Advise the client of the recommended k-of-n encoding parameters
        for this grid. 'parameters' is a tuple of (k, desired, n), where 'n'
        is the total number of shares that will be created for any given
        file, while 'k' is the number of shares that must be retrieved to
        recover that file, and 'desired' is the minimum number of shares that
        must be placed before the uploader will consider its job a success.
        n/k is the expansion ratio, while k determines the robustness.

        Introducers should specify 'n' according to the expected size of the
        grid (there is no point to producing more shares than there are
        peers), and k according to the desired reliability-vs-overhead goals.

        Note that setting k=1 is equivalent to simple replication.
        """
        return None

SubscriberInfo = DictOf(str, Any())

class RIIntroducerPublisherAndSubscriberService_v2(RemoteInterface):
    """To publish a service to the world, connect to me and give me your
    announcement message. I will deliver a copy to all connected subscribers.
    To hear about services, connect to me and subscribe to a specific
    service_name."""
    __remote_name__ = "RIIntroducerPublisherAndSubscriberService_v2.tahoe.allmydata.com"
    def get_version():
        return DictOf(str, Any())
    def publish(announcement=Announcement_v1):
        return None
    def publish_v2(announcement=Announcement_v2, canary=Referenceable):
        return None
    def subscribe(subscriber=RIIntroducerSubscriberClient_v1, service_name=str):
        return None
    def subscribe_v2(subscriber=RIIntroducerSubscriberClient_v2,
                     service_name=str, subscriber_info=SubscriberInfo):
        """Give me a subscriber reference, and I will call its announce_v2()
        method with any announcements that match the desired service name. I
        will ignore duplicate subscriptions. The subscriber_info dictionary
        tells me about the subscriber, and is used for diagnostic/status
        displays."""
        return None

class IIntroducerClient(Interface):
    """I provide service introduction facilities for a node. I help nodes
    publish their services to the rest of the world, and I help them learn
    about services available on other nodes."""

    def publish(furl, service_name, remoteinterface_name,
                signing_key=None):
        """Once you call this, I will tell the world that the Referenceable
        available at FURL is available to provide a service named
        SERVICE_NAME. The precise definition of the service being provided is
        identified by the Foolscap 'remote interface name' in the last
        parameter: this is supposed to be a globally-unique string that
        identifies the RemoteInterface that is implemented.

        If signing_key= is set to an instance of ecdsa.SigningKey, it will be
        used to sign the announcement."""

    def subscribe_to(service_name, callback, *args, **kwargs):
        """Call this if you will eventually want to use services with the
        given SERVICE_NAME. This will prompt me to subscribe to announcements
        of those services. Your callback will be invoked with at least two
        arguments: a serverid (binary string), and an announcement
        dictionary, followed by any additional callback args/kwargs you give
        me. I will run your callback for both new announcements and for
        announcements that have changed, but you must be prepared to tolerate
        duplicates.

        The announcement dictionary that I give you will have the following
        keys:

         version: 0
         service-name: str('storage')

         FURL: str(furl)
         remoteinterface-name: str(ri_name)
         nickname: unicode
         app-versions: {}
         my-version: str
         oldest-supported: str

        Note that app-version will be an empty dictionary until #466 is done
        and both the introducer and the remote client have been upgraded. For
        current (native) server types, the serverid will always be equal to
        the binary form of the FURL's tubid.
        """

    def connected_to_introducer():
        """Returns a boolean, True if we are currently connected to the
        introducer, False if not."""

