"""
Ported to Python 3.
"""
from __future__ import annotations

from twisted.web import http, static
from twisted.internet import defer
from twisted.web.resource import (
    Resource,
    ErrorPage,
)

from allmydata.interfaces import ExistingChildError
from allmydata.monitor import Monitor
from allmydata.immutable.upload import FileHandle
from allmydata.mutable.publish import MutableFileHandle
from allmydata.mutable.common import MODE_READ
from allmydata.util import log, base32
from allmydata.util.encodingutil import quote_output
from allmydata.blacklist import (
    FileProhibited,
    ProhibitedNode,
)

from allmydata.web.common import (
    get_keypair,
    boolean_of_arg,
    exception_to_child,
    get_arg,
    get_filenode_metadata,
    get_format,
    get_mutable_type,
    parse_offset_arg,
    parse_replace_arg,
    render_exception,
    should_create_intermediate_directories,
    text_plain,
    WebError,
    handle_when_done,
)
from allmydata.web.check_results import (
    CheckResultsRenderer,
    CheckAndRepairResultsRenderer,
    LiteralCheckResultsRenderer,
)
from allmydata.web.info import MoreInfo
from allmydata.util import jsonbytes as json

class ReplaceMeMixin:
    def replace_me_with_a_child(self, req, client, replace):
        # a new file is being uploaded in our place.
        file_format = get_format(req, "CHK")
        mutable_type = get_mutable_type(file_format)
        if mutable_type is not None:
            data = MutableFileHandle(req.content)
            keypair = get_keypair(req)
            d = client.create_mutable_file(data, version=mutable_type, unique_keypair=keypair)
            def _uploaded(newnode):
                d2 = self.parentnode.set_node(self.name, newnode,
                                              overwrite=replace)
                d2.addCallback(lambda res: newnode)
                return d2
            d.addCallback(_uploaded)
        else:
            assert file_format == "CHK"
            uploadable = FileHandle(req.content, convergence=client.convergence)
            d = self.parentnode.add_file(self.name, uploadable,
                                         overwrite=replace)
        def _done(filenode):
            log.msg("webish upload complete",
                    facility="tahoe.webish", level=log.NOISY, umid="TCjBGQ")
            if self.node:
                # we've replaced an existing file (or modified a mutable
                # file), so the response code is 200
                req.setResponseCode(http.OK)
            else:
                # we've created a new file, so the code is 201
                req.setResponseCode(http.CREATED)
            return filenode.get_uri()
        d.addCallback(_done)
        return d

    def replace_me_with_a_childcap(self, req, client, replace):
        req.content.seek(0)
        childcap = req.content.read()
        childnode = client.create_node_from_uri(childcap, None, name=self.name)
        d = self.parentnode.set_node(self.name, childnode, overwrite=replace)
        d.addCallback(lambda res: childnode.get_uri())
        return d


    def replace_me_with_a_formpost(self, req, client, replace):
        # create a new file, maybe mutable, maybe immutable
        file_format = get_format(req, "CHK")
        contents = req.fields["file"]
        if file_format in ("SDMF", "MDMF"):
            mutable_type = get_mutable_type(file_format)
            uploadable = MutableFileHandle(contents.file)
            keypair = get_keypair(req)
            d = client.create_mutable_file(uploadable, version=mutable_type, unique_keypair=keypair)
            def _uploaded(newnode):
                d2 = self.parentnode.set_node(self.name, newnode,
                                              overwrite=replace)
                d2.addCallback(lambda res: newnode.get_uri())
                return d2
            d.addCallback(_uploaded)
            return d

        uploadable = FileHandle(contents.file, convergence=client.convergence)
        d = self.parentnode.add_file(self.name, uploadable, overwrite=replace)
        d.addCallback(lambda newnode: newnode.get_uri())
        return d


class PlaceHolderNodeHandler(Resource, ReplaceMeMixin):
    def __init__(self, client, parentnode, name):
        super(PlaceHolderNodeHandler, self).__init__()
        self.client = client
        assert parentnode
        self.parentnode = parentnode
        self.name = name
        self.node = None

    @render_exception
    def render_PUT(self, req):
        t = get_arg(req, b"t", b"").strip()
        replace = parse_replace_arg(get_arg(req, "replace", "true"))

        assert self.parentnode and self.name
        if req.getHeader("content-range"):
            raise WebError("Content-Range in PUT not yet supported",
                           http.NOT_IMPLEMENTED)
        if not t:
            return self.replace_me_with_a_child(req, self.client, replace)
        if t == b"uri":
            return self.replace_me_with_a_childcap(req, self.client, replace)

        raise WebError("PUT to a file: bad t=%s" % str(t, "utf-8"))

    @render_exception
    def render_POST(self, req):
        t = get_arg(req, b"t", b"").strip()
        replace = boolean_of_arg(get_arg(req, b"replace", b"true"))
        if t == b"upload":
            # like PUT, but get the file data from an HTML form's input field.
            # We could get here from POST /uri/mutablefilecap?t=upload,
            # or POST /uri/path/file?t=upload, or
            # POST /uri/path/dir?t=upload&name=foo . All have the same
            # behavior, we just ignore any name= argument
            d = self.replace_me_with_a_formpost(req, self.client, replace)
        else:
            # t=mkdir is handled in DirectoryNodeHandler._POST_mkdir, so
            # there are no other t= values left to be handled by the
            # placeholder.
            raise WebError("POST to a file: bad t=%s" % str(t, "utf-8"))

        return handle_when_done(req, d)


class FileNodeHandler(Resource, ReplaceMeMixin, object):
    def __init__(self, client, node, parentnode=None, name=None):
        super(FileNodeHandler, self).__init__()
        self.client = client
        assert node
        self.node = node
        self.parentnode = parentnode
        self.name = name

    @exception_to_child
    def getChild(self, name, req):
        if isinstance(self.node, ProhibitedNode):
            raise FileProhibited(self.node.reason)
        if should_create_intermediate_directories(req):
                return ErrorPage(
                    http.CONFLICT,
                    u"Cannot create directory %s, because its parent is a file, "
                    u"not a directory" % quote_output(name, encoding='utf-8'),
                    "no details"
                )
        return ErrorPage(
            http.BAD_REQUEST,
            u"Files have no children named %s" % quote_output(name, encoding='utf-8'),
            "no details",
        )

    @render_exception
    def render_GET(self, req):
        t = str(get_arg(req, b"t", b"").strip(), "ascii")

        # t=info contains variable ophandles, so is not allowed an ETag.
        FIXED_OUTPUT_TYPES = ["", "json", "uri", "readonly-uri"]
        if not self.node.is_mutable() and t in FIXED_OUTPUT_TYPES:
            # if the client already has the ETag then we can
            # short-circuit the whole process.
            si = self.node.get_storage_index()
            if si and req.setETag(b'%s-%s' % (base32.b2a(si), t.encode("ascii") or b"")):
                return b""

        if not t:
            # just get the contents
            # the filename arrives as part of the URL or in a form input
            # element, and will be sent back in a Content-Disposition header.
            # Different browsers use various character sets for this name,
            # sometimes depending upon how language environment is
            # configured. Firefox sends the equivalent of
            # urllib.quote(name.encode("utf-8")), while IE7 sometimes does
            # latin-1. Browsers cannot agree on how to interpret the name
            # they see in the Content-Disposition header either, despite some
            # 11-year old standards (RFC2231) that explain how to do it
            # properly. So we assume that at least the browser will agree
            # with itself, and echo back the same bytes that we were given.
            filename = get_arg(req, "filename", self.name) or "unknown"
            d = self.node.get_best_readable_version()
            d.addCallback(lambda dn: FileDownloader(dn, filename))
            return d
        if t == "json":
            # We do this to make sure that fields like size and
            # mutable-type (which depend on the file on the grid and not
            # just on the cap) are filled in. The latter gets used in
            # tests, in particular.
            #
            # TODO: Make it so that the servermap knows how to update in
            # a mode specifically designed to fill in these fields, and
            # then update it in that mode.
            if self.node.is_mutable():
                d = self.node.get_servermap(MODE_READ)
            else:
                d = defer.succeed(None)
            if self.parentnode and self.name:
                d.addCallback(lambda ignored:
                    self.parentnode.get_metadata_for(self.name))
            else:
                d.addCallback(lambda ignored: None)
            d.addCallback(lambda md: _file_json_metadata(req, self.node, md))
            return d
        if t == "info":
            return MoreInfo(self.node)
        if t == "uri":
            return _file_uri(req, self.node)
        if t == "readonly-uri":
            return _file_read_only_uri(req, self.node)
        raise WebError("GET file: bad t=%s" % t)

    @render_exception
    def render_HEAD(self, req):
        t = get_arg(req, b"t", b"").strip()
        if t:
            raise WebError("HEAD file: bad t=%s" % t)
        filename = get_arg(req, b"filename", self.name) or "unknown"
        d = self.node.get_best_readable_version()
        d.addCallback(lambda dn: FileDownloader(dn, filename))
        return d

    @render_exception
    def render_PUT(self, req):
        t = get_arg(req, b"t", b"").strip()
        replace = parse_replace_arg(get_arg(req, b"replace", b"true"))
        offset = parse_offset_arg(get_arg(req, b"offset", None))

        if not t:
            if not replace:
                # this is the early trap: if someone else modifies the
                # directory while we're uploading, the add_file(overwrite=)
                # call in replace_me_with_a_child will do the late trap.
                raise ExistingChildError()

            if self.node.is_mutable():
                # Are we a readonly filenode? We shouldn't allow callers
                # to try to replace us if we are.
                if self.node.is_readonly():
                    raise WebError("PUT to a mutable file: replace or update"
                                   " requested with read-only cap")
                if offset is None:
                    return self.replace_my_contents(req)

                if offset >= 0:
                    return self.update_my_contents(req, offset)

                raise WebError("PUT to a mutable file: Invalid offset")

            else:
                if offset is not None:
                    raise WebError("PUT to a file: append operation invoked "
                                   "on an immutable cap")

                assert self.parentnode and self.name
                return self.replace_me_with_a_child(req, self.client, replace)

        if t == b"uri":
            if not replace:
                raise ExistingChildError()
            assert self.parentnode and self.name
            return self.replace_me_with_a_childcap(req, self.client, replace)

        raise WebError("PUT to a file: bad t=%s" % str(t, "utf-8"))

    @render_exception
    def render_POST(self, req):
        t = get_arg(req, b"t", b"").strip()
        replace = boolean_of_arg(get_arg(req, b"replace", b"true"))
        if t == b"check":
            d = self._POST_check(req)
        elif t == b"upload":
            # like PUT, but get the file data from an HTML form's input field
            # We could get here from POST /uri/mutablefilecap?t=upload,
            # or POST /uri/path/file?t=upload, or
            # POST /uri/path/dir?t=upload&name=foo . All have the same
            # behavior, we just ignore any name= argument
            if self.node.is_mutable():
                d = self.replace_my_contents_with_a_formpost(req)
            else:
                if not replace:
                    raise ExistingChildError()
                assert self.parentnode and self.name
                d = self.replace_me_with_a_formpost(req, self.client, replace)
        else:
            raise WebError("POST to file: bad t=%s" % str(t, "ascii"))

        return handle_when_done(req, d)

    def _maybe_literal(self, res, Results_Class):
        if res:
            return Results_Class(self.client, res)
        return LiteralCheckResultsRenderer(self.client)

    def _POST_check(self, req):
        verify = boolean_of_arg(get_arg(req, "verify", "false"))
        repair = boolean_of_arg(get_arg(req, "repair", "false"))
        add_lease = boolean_of_arg(get_arg(req, "add-lease", "false"))
        if repair:
            d = self.node.check_and_repair(Monitor(), verify, add_lease)
            d.addCallback(self._maybe_literal, CheckAndRepairResultsRenderer)
        else:
            d = self.node.check(Monitor(), verify, add_lease)
            d.addCallback(self._maybe_literal, CheckResultsRenderer)
        return d

    @render_exception
    def render_DELETE(self, req):
        assert self.parentnode and self.name
        d = self.parentnode.delete(self.name)
        d.addCallback(lambda res: self.node.get_uri())
        return d

    def replace_my_contents(self, req):
        req.content.seek(0)
        new_contents = MutableFileHandle(req.content)
        d = self.node.overwrite(new_contents)
        d.addCallback(lambda res: self.node.get_uri())
        return d


    def update_my_contents(self, req, offset):
        req.content.seek(0)
        added_contents = MutableFileHandle(req.content)

        d = self.node.get_best_mutable_version()
        d.addCallback(lambda mv:
            mv.update(added_contents, offset))
        d.addCallback(lambda ignored:
            self.node.get_uri())
        return d


    def replace_my_contents_with_a_formpost(self, req):
        # we have a mutable file. Get the data from the formpost, and replace
        # the mutable file's contents with it.
        new_contents = req.fields['file']
        new_contents = MutableFileHandle(new_contents.file)

        d = self.node.overwrite(new_contents)
        d.addCallback(lambda res: self.node.get_uri())
        return d


class FileDownloader(Resource, object):
    def __init__(self, filenode, filename):
        super(FileDownloader, self).__init__()
        self.filenode = filenode
        self.filename = filename

    def parse_range_header(self, range_header):
        # Parse a byte ranges according to RFC 2616 "14.35.1 Byte
        # Ranges".  Returns None if the range doesn't make sense so it
        # can be ignored (per the spec).  When successful, returns a
        # list of (first,last) inclusive range tuples.

        filesize = self.filenode.get_size()
        assert isinstance(filesize, int), filesize

        try:
            # byte-ranges-specifier
            units, rangeset = range_header.split('=', 1)
            if units != 'bytes':
                return None     # nothing else supported

            def parse_range(r):
                first, last = r.split('-', 1)

                if first == '':
                    # suffix-byte-range-spec
                    first = filesize - int(last)
                    last = filesize - 1
                else:
                    # byte-range-spec

                    # first-byte-pos
                    first = int(first)

                    # last-byte-pos
                    if last == '':
                        last = filesize - 1
                    else:
                        last = int(last)

                if last < first:
                    raise ValueError

                return (first, last)

            # byte-range-set
            #
            # Note: the spec uses "1#" for the list of ranges, which
            # implicitly allows whitespace around the ',' separators,
            # so strip it.
            return [ parse_range(r.strip()) for r in rangeset.split(',') ]
        except ValueError:
            return None

    @render_exception
    def render(self, req):
        gte = static.getTypeAndEncoding
        ctype, encoding = gte(self.filename,
                              static.File.contentTypes,
                              static.File.contentEncodings,
                              defaultType="text/plain")
        req.setHeader("content-type", ctype)
        if encoding:
            req.setHeader("content-encoding", encoding)

        if boolean_of_arg(get_arg(req, "save", "False")):
            # tell the browser to save the file rather display it we don't
            # try to encode the filename, instead we echo back the exact same
            # bytes we were given in the URL. See the comment in
            # FileNodeHandler.render_GET for the sad details.
            req.setHeader("content-disposition",
                          b'attachment; filename="%s"' % self.filename)

        filesize = self.filenode.get_size()
        assert isinstance(filesize, int), filesize
        first, size = 0, None
        contentsize = filesize
        req.setHeader("accept-ranges", "bytes")

        # TODO: for mutable files, use the roothash. For LIT, hash the data.
        # or maybe just use the URI for CHK and LIT.
        rangeheader = req.getHeader('range')
        if rangeheader:
            ranges = self.parse_range_header(rangeheader)

            # ranges = None means the header didn't parse, so ignore
            # the header as if it didn't exist.  If is more than one
            # range, then just return the first for now, until we can
            # generate multipart/byteranges.
            if ranges is not None:
                first, last = ranges[0]

                if first >= filesize:
                    raise WebError('First beyond end of file',
                                   http.REQUESTED_RANGE_NOT_SATISFIABLE)
                else:
                    first = max(0, first)
                    last = min(filesize-1, last)

                    req.setResponseCode(http.PARTIAL_CONTENT)
                    req.setHeader('content-range',"bytes %s-%s/%s" %
                                  (str(first), str(last),
                                   str(filesize)))
                    contentsize = last - first + 1
                    size = contentsize

        req.setHeader("content-length", b"%d" % contentsize)
        if req.method == b"HEAD":
            return b""

        d = self.filenode.read(req, first, size)

        def _error(f):
            if f.check(defer.CancelledError):
                # The HTTP connection was lost and we no longer have anywhere
                # to send our result.  Let this pass through.
                return f
            if req.startedWriting:
                # The content-type is already set, and the response code has
                # already been sent, so we can't provide a clean error
                # indication. We can emit text (which a browser might
                # interpret as something else), and if we sent a Size header,
                # they might notice that we've truncated the data. Keep the
                # error message small to improve the chances of having our
                # error response be shorter than the intended results.
                #
                # We don't have a lot of options, unfortunately.
                return b"problem during download\n"
            else:
                # We haven't written anything yet, so we can provide a
                # sensible error message.
                return f
        d.addCallbacks(
            lambda ignored: None,
            _error,
        )
        return d


def _file_json_metadata(req, filenode, edge_metadata):
    rw_uri = filenode.get_write_uri()
    ro_uri = filenode.get_readonly_uri()
    data = ("filenode", get_filenode_metadata(filenode))
    if ro_uri:
        data[1]['ro_uri'] = ro_uri
    if rw_uri:
        data[1]['rw_uri'] = rw_uri
    verifycap = filenode.get_verify_cap()
    if verifycap:
        data[1]['verify_uri'] = verifycap.to_string()
    if edge_metadata is not None:
        data[1]['metadata'] = edge_metadata

    return text_plain(json.dumps(data, indent=1) + "\n", req)


def _file_uri(req, filenode):
    return text_plain(filenode.get_uri(), req)


def _file_read_only_uri(req, filenode):
    if filenode.is_readonly():
        return text_plain(filenode.get_uri(), req)
    return text_plain(filenode.get_readonly_uri(), req)


class FileNodeDownloadHandler(FileNodeHandler):

    @exception_to_child
    def getChild(self, name, req):
        return FileNodeDownloadHandler(self.client, self.node, name=name)
