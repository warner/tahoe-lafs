
from allmydata.util import keyutil

class InvitationManager(service.MultiService):
    """I keep track of outstanding invitations. You can ask me to issue a new
    invitation, and I will record it on disk and return an invitation code.
    You can also ask me to redeem an invitation code received from some other
    node.
    """
    def __init__(self, basedir):
        service.MultiService.__init__(self)
        self.basedir = basedir
        if not os.path.isdir(self.basedir):
            os.makedirs(self.basedir)

    def create_invitation(self, petname):
        sk_s, vk_s = keyutil.make_keypair()
        vk = sk.get_verifying_key()
        inviteid = sha256(vk_s).hexdigest()
        invite_dir = os.path.join(self.basedir, inviteid)
        os.makedirs(invite_dir)
        open(os.path.join(invite_dir, "sk"),"w").write(sk_s)
        open(os.path.join(invite_dir, "vk"),"w").write(vk_s)
