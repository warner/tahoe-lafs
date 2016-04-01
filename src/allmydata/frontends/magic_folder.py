
import sys, os
import os.path
from collections import deque
import time

from twisted.internet import defer, reactor, task
from twisted.python.failure import Failure
from twisted.python import runtime
from twisted.application import service

from allmydata.util import fileutil
from allmydata.interfaces import IDirectoryNode
from allmydata.util import log
from allmydata.util.fileutil import precondition_abspath, get_pathinfo, ConflictError
from allmydata.util.assertutil import precondition, _assert
from allmydata.util.deferredutil import HookMixin
from allmydata.util.encodingutil import listdir_filepath, to_filepath, \
     extend_filepath, unicode_from_filepath, unicode_segments_from, \
     quote_filepath, quote_local_unicode_path, quote_output, FilenameEncodingError
from allmydata.immutable.upload import FileName, Data
from allmydata import magicfolderdb, magicpath

defer.setDebugging(True)
IN_EXCL_UNLINK = 0x04000000L

def get_inotify_module():
    try:
        if sys.platform == "win32":
            from allmydata.windows import inotify
        elif runtime.platform.supportsINotify():
            from twisted.internet import inotify
        else:
            raise NotImplementedError("filesystem notification needed for Magic Folder is not supported.\n"
                                      "This currently requires Linux or Windows.")
        return inotify
    except (ImportError, AttributeError) as e:
        log.msg(e)
        if sys.platform == "win32":
            raise NotImplementedError("filesystem notification needed for Magic Folder is not supported.\n"
                                      "Windows support requires at least Vista, and has only been tested on Windows 7.")
        raise


def is_new_file(pathinfo, db_entry):
    if db_entry is None:
        return True

    if not pathinfo.exists and db_entry.size is None:
        return False

    return ((pathinfo.size, pathinfo.ctime, pathinfo.mtime) !=
            (db_entry.size, db_entry.ctime, db_entry.mtime))


class MagicFolder(service.MultiService):
    name = 'magic-folder'

    def __init__(self, client, upload_dircap, collective_dircap, local_path_u, dbfile, umask,
                 pending_delay=1.0, clock=None):
        precondition_abspath(local_path_u)

        service.MultiService.__init__(self)

        immediate = clock is not None
        clock = clock or reactor
        db = magicfolderdb.get_magicfolderdb(dbfile, create_version=(magicfolderdb.SCHEMA_v1, 1))
        if db is None:
            return Failure(Exception('ERROR: Unable to load magic folder db.'))

        # for tests
        self._client = client
        self._db = db

        upload_dirnode = self._client.create_node_from_uri(upload_dircap)
        collective_dirnode = self._client.create_node_from_uri(collective_dircap)

        self.uploader = Uploader(client, local_path_u, db, upload_dirnode, pending_delay, clock, immediate)
        self.downloader = Downloader(client, local_path_u, db, collective_dirnode,
                                     upload_dirnode.get_readonly_uri(), clock, self.uploader.is_pending, umask)

    def startService(self):
        # TODO: why is this being called more than once?
        if self.running:
            return defer.succeed(None)
        print "%r.startService" % (self,)
        service.MultiService.startService(self)
        return self.uploader.start_monitoring()

    def ready(self):
        """ready is used to signal us to start
        processing the upload and download items...
        """
        self.uploader.start_uploading()  # synchronous
        return self.downloader.start_downloading()

    def finish(self):
        print "finish"
        d = self.uploader.stop()
        d2 = self.downloader.stop()
        d.addCallback(lambda ign: d2)
        return d

    def remove_service(self):
        return service.MultiService.disownServiceParent(self)


class QueueMixin(HookMixin):
    def __init__(self, client, local_path_u, db, name, clock):
        self._client = client
        self._local_path_u = local_path_u
        self._local_filepath = to_filepath(local_path_u)
        self._db = db
        self._name = name
        self._clock = clock
        self._hooks = {'processed': None, 'started': None}
        self.started_d = self.set_hook('started')

        if not self._local_filepath.exists():
            raise AssertionError("The '[magic_folder] local.directory' parameter was %s "
                                 "but there is no directory at that location."
                                 % quote_local_unicode_path(self._local_path_u))
        if not self._local_filepath.isdir():
            raise AssertionError("The '[magic_folder] local.directory' parameter was %s "
                                 "but the thing at that location is not a directory."
                                 % quote_local_unicode_path(self._local_path_u))

        self._deque = deque()
        self._lazy_tail = defer.succeed(None)
        self._stopped = False
        self._turn_delay = 0

    def _get_filepath(self, relpath_u):
        self._log("_get_filepath(%r)" % (relpath_u,))
        return extend_filepath(self._local_filepath, relpath_u.split(u"/"))

    def _get_relpath(self, filepath):
        self._log("_get_relpath(%r)" % (filepath,))
        segments = unicode_segments_from(filepath, self._local_filepath)
        self._log("segments = %r" % (segments,))
        return u"/".join(segments)

    def _count(self, counter_name, delta=1):
        ctr = 'magic_folder.%s.%s' % (self._name, counter_name)
        self._log("%s += %r" % (counter_name, delta))
        self._client.stats_provider.count(ctr, delta)

    def _logcb(self, res, msg):
        self._log("%s: %r" % (msg, res))
        return res

    def _log(self, msg):
        s = "Magic Folder %s %s: %s" % (quote_output(self._client.nickname), self._name, msg)
        self._client.log(s)
        print s
        #open("events", "ab+").write(msg)

    def _turn_deque(self):
        try:
            self._log("_turn_deque")
            if self._stopped:
                self._log("stopped")
                return
            try:
                item = self._deque.pop()
                self._log("popped %r" % (item,))
                self._count('objects_queued', -1)
            except IndexError:
                self._log("deque is now empty")
                self._lazy_tail.addCallback(lambda ign: self._when_queue_is_empty())
            else:
                self._log("_turn_deque else clause")
                def whawhat(result):
                    self._log("whawhat result %r" % (result,))
                    return result
                self._lazy_tail.addBoth(whawhat)
                self._lazy_tail.addCallback(lambda ign: self._process(item))
                self._lazy_tail.addBoth(self._call_hook, 'processed')
                self._lazy_tail.addErrback(log.err)
                self._lazy_tail.addCallback(lambda ign: task.deferLater(self._clock, self._turn_delay, self._turn_deque))
        except Exception as e:
            self._log("turn deque exception %s" % (e,))
            raise


class Uploader(QueueMixin):
    def __init__(self, client, local_path_u, db, upload_dirnode, pending_delay, clock,
                 immediate=False):
        QueueMixin.__init__(self, client, local_path_u, db, 'uploader', clock)

        self.is_ready = False
        self._immediate = immediate

        if not IDirectoryNode.providedBy(upload_dirnode):
            raise AssertionError("The URI in '%s' does not refer to a directory."
                                 % os.path.join('private', 'magic_folder_dircap'))
        if upload_dirnode.is_unknown() or upload_dirnode.is_readonly():
            raise AssertionError("The URI in '%s' is not a writecap to a directory."
                                 % os.path.join('private', 'magic_folder_dircap'))

        self._upload_dirnode = upload_dirnode
        self._inotify = get_inotify_module()
        self._notifier = self._inotify.INotify()
        self._pending = set()  # of unicode relpaths

        self._periodic_full_scan_duration = 10 * 60 # perform a full scan every 10 minutes

        if hasattr(self._notifier, 'set_pending_delay'):
            self._notifier.set_pending_delay(pending_delay)

        # TODO: what about IN_MOVE_SELF and IN_UNMOUNT?
        #
        self.mask = ( self._inotify.IN_CREATE
                    | self._inotify.IN_CLOSE_WRITE
                    | self._inotify.IN_MOVED_TO
                    | self._inotify.IN_MOVED_FROM
                    | self._inotify.IN_DELETE
                    | self._inotify.IN_ONLYDIR
                    | IN_EXCL_UNLINK
                    )
        self._notifier.watch(self._local_filepath, mask=self.mask, callbacks=[self._notify],
                             recursive=True)

    def start_monitoring(self):
        self._log("start_monitoring")
        d = defer.succeed(None)
        d.addCallback(lambda ign: self._notifier.startReading())
        d.addCallback(lambda ign: self._count('dirs_monitored'))
        d.addBoth(self._call_hook, 'started')
        return d

    def stop(self):
        self._log("stop")
        self._notifier.stopReading()
        self._count('dirs_monitored', -1)
        self.periodic_callid.cancel()
        if hasattr(self._notifier, 'wait_until_stopped'):
            d = self._notifier.wait_until_stopped()
        else:
            d = defer.succeed(None)
        d.addCallback(lambda ign: self._lazy_tail)
        return d

    def start_uploading(self):
        self._log("start_uploading")
        self.is_ready = True

        all_relpaths = self._db.get_all_relpaths()
        self._log("all relpaths: %r" % (all_relpaths,))

        for relpath_u in all_relpaths:
            self._add_pending(relpath_u)

        self._full_scan()

    def _extend_queue_and_keep_going(self, relpaths_u):
        self._log("_extend_queue_and_keep_going %r" % (relpaths_u,))
        self._deque.extend(relpaths_u)
        self._count('objects_queued', len(relpaths_u))

        if self.is_ready:
            if self._immediate:  # for tests
                self._turn_deque()
            else:
                self._clock.callLater(0, self._turn_deque)

    def _full_scan(self):
        self.periodic_callid = self._clock.callLater(self._periodic_full_scan_duration, self._full_scan)
        print "FULL SCAN"
        self._log("_pending %r" % (self._pending))
        self._scan(u"")
        self._extend_queue_and_keep_going(self._pending)

    def _add_pending(self, relpath_u):
        self._log("add pending %r" % (relpath_u,))        
        if not magicpath.should_ignore_file(relpath_u):
            self._pending.add(relpath_u)

    def _scan(self, reldir_u):
        # Scan a directory by (synchronously) adding the paths of all its children to self._pending.
        # Note that this doesn't add them to the deque -- that will

        self._log("scan %r" % (reldir_u,))
        fp = self._get_filepath(reldir_u)
        try:
            children = listdir_filepath(fp)
        except EnvironmentError:
            raise Exception("WARNING: magic folder: permission denied on directory %s"
                            % quote_filepath(fp))
        except FilenameEncodingError:
            raise Exception("WARNING: magic folder: could not list directory %s due to a filename encoding error"
                            % quote_filepath(fp))

        for child in children:
            _assert(isinstance(child, unicode), child=child)
            self._add_pending("%s/%s" % (reldir_u, child) if reldir_u != u"" else child)

    def is_pending(self, relpath_u):
        return relpath_u in self._pending

    def _notify(self, opaque, path, events_mask):
        self._log("inotify event %r, %r, %r\n" % (opaque, path, ', '.join(self._inotify.humanReadableMask(events_mask))))
        relpath_u = self._get_relpath(path)

        # We filter out IN_CREATE events not associated with a directory.
        # Acting on IN_CREATE for files could cause us to read and upload
        # a possibly-incomplete file before the application has closed it.
        # There should always be an IN_CLOSE_WRITE after an IN_CREATE, I think.
        # It isn't possible to avoid watching for IN_CREATE at all, because
        # it is the only event notified for a directory creation.

        if ((events_mask & self._inotify.IN_CREATE) != 0 and
            (events_mask & self._inotify.IN_ISDIR) == 0):
            self._log("ignoring event for %r (creation of non-directory)\n" % (relpath_u,))
            return
        if relpath_u in self._pending:
            self._log("not queueing %r because it is already pending" % (relpath_u,))
            return
        if magicpath.should_ignore_file(relpath_u):
            self._log("ignoring event for %r (ignorable path)" % (relpath_u,))
            return

        self._pending.add(relpath_u)
        self._extend_queue_and_keep_going([relpath_u])

    def _when_queue_is_empty(self):
        return defer.succeed(None)

    def _process(self, relpath_u):
        # Uploader
        self._log("_process(%r)" % (relpath_u,))
        if relpath_u is None:
            return
        precondition(isinstance(relpath_u, unicode), relpath_u)
        precondition(not relpath_u.endswith(u'/'), relpath_u)

        d = defer.succeed(None)

        def _maybe_upload(val, now=None):
            self._log("_maybe_upload(%r, now=%r)" % (val, now))
            if now is None:
                now = time.time()
            fp = self._get_filepath(relpath_u)
            pathinfo = get_pathinfo(unicode_from_filepath(fp))

            self._log("about to remove %r from pending set %r" %
                      (relpath_u, self._pending))
            self._pending.remove(relpath_u)
            encoded_path_u = magicpath.path2magic(relpath_u)

            if not pathinfo.exists:
                # FIXME merge this with the 'isfile' case.
                self._log("notified object %s disappeared (this is normal)" % quote_filepath(fp))
                self._count('objects_disappeared')

                db_entry = self._db.get_db_entry(relpath_u)
                if db_entry is None:
                    return None

                last_downloaded_timestamp = now  # is this correct?

                if is_new_file(pathinfo, db_entry):
                    new_version = db_entry.version + 1
                else:
                    self._log("Not uploading %r" % (relpath_u,))
                    self._count('objects_not_uploaded')
                    return

                metadata = { 'version': new_version,
                             'deleted': True,
                             'last_downloaded_timestamp': last_downloaded_timestamp }
                if db_entry.last_downloaded_uri is not None:
                    metadata['last_downloaded_uri'] = db_entry.last_downloaded_uri

                empty_uploadable = Data("", self._client.convergence)
                d2 = self._upload_dirnode.add_file(encoded_path_u, empty_uploadable,
                                                   metadata=metadata, overwrite=True)

                def _add_db_entry(filenode):
                    filecap = filenode.get_uri()
                    last_downloaded_uri = metadata.get('last_downloaded_uri', None)
                    self._db.did_upload_version(relpath_u, new_version, filecap,
                                                last_downloaded_uri, last_downloaded_timestamp,
                                                pathinfo)
                    self._count('files_uploaded')
                d2.addCallback(_add_db_entry)
                return d2
            elif pathinfo.islink:
                self.warn("WARNING: cannot upload symlink %s" % quote_filepath(fp))
                return None
            elif pathinfo.isdir:
                print "ISDIR "
                if not getattr(self._notifier, 'recursive_includes_new_subdirectories', False):
                    self._notifier.watch(fp, mask=self.mask, callbacks=[self._notify], recursive=True)

                uploadable = Data("", self._client.convergence)
                encoded_path_u += magicpath.path2magic(u"/")
                self._log("encoded_path_u =  %r" % (encoded_path_u,))
                upload_d = self._upload_dirnode.add_file(encoded_path_u, uploadable, metadata={"version":0}, overwrite=True)
                def _dir_succeeded(ign):
                    self._log("created subdirectory %r" % (relpath_u,))
                    self._count('directories_created')
                def _dir_failed(f):
                    self._log("failed to create subdirectory %r" % (relpath_u,))
                    return f
                upload_d.addCallbacks(_dir_succeeded, _dir_failed)
                upload_d.addCallback(lambda ign: self._scan(relpath_u))
                upload_d.addCallback(lambda ign: self._extend_queue_and_keep_going(self._pending))
                return upload_d
            elif pathinfo.isfile:
                db_entry = self._db.get_db_entry(relpath_u)

                last_downloaded_timestamp = now

                if db_entry is None:
                    new_version = 0
                elif is_new_file(pathinfo, db_entry):
                    new_version = db_entry.version + 1
                else:
                    self._log("Not uploading %r" % (relpath_u,))
                    self._count('objects_not_uploaded')
                    return None

                metadata = { 'version': new_version,
                             'last_downloaded_timestamp': last_downloaded_timestamp }
                if db_entry is not None and db_entry.last_downloaded_uri is not None:
                    metadata['last_downloaded_uri'] = db_entry.last_downloaded_uri

                uploadable = FileName(unicode_from_filepath(fp), self._client.convergence)
                d2 = self._upload_dirnode.add_file(encoded_path_u, uploadable,
                                                   metadata=metadata, overwrite=True)

                def _add_db_entry(filenode):
                    filecap = filenode.get_uri()
                    last_downloaded_uri = metadata.get('last_downloaded_uri', None)
                    self._db.did_upload_version(relpath_u, new_version, filecap,
                                                last_downloaded_uri, last_downloaded_timestamp,
                                                pathinfo)
                    self._count('files_uploaded')
                d2.addCallback(_add_db_entry)
                return d2
            else:
                self.warn("WARNING: cannot process special file %s" % quote_filepath(fp))
                return None

        d.addCallback(_maybe_upload)

        def _succeeded(res):
            self._count('objects_succeeded')
            return res
        def _failed(f):
            self._count('objects_failed')
            self._log("%s while processing %r" % (f, relpath_u))
            return f
        d.addCallbacks(_succeeded, _failed)
        return d

    def _get_metadata(self, encoded_path_u):
        try:
            d = self._upload_dirnode.get_metadata_for(encoded_path_u)
        except KeyError:
            return Failure()
        return d

    def _get_filenode(self, encoded_path_u):
        try:
            d = self._upload_dirnode.get(encoded_path_u)
        except KeyError:
            return Failure()
        return d


class WriteFileMixin(object):
    FUDGE_SECONDS = 10.0

    def _get_conflicted_filename(self, abspath_u):
        return abspath_u + u".conflict"

    def _write_downloaded_file(self, abspath_u, file_contents, is_conflict=False, now=None):
        self._log("_write_downloaded_file(%r, <%d bytes>, is_conflict=%r, now=%r)"
                  % (abspath_u, len(file_contents), is_conflict, now))

        # 1. Write a temporary file, say .foo.tmp.
        # 2. is_conflict determines whether this is an overwrite or a conflict.
        # 3. Set the mtime of the replacement file to be T seconds before the
        #    current local time.
        # 4. Perform a file replacement with backup filename foo.backup,
        #    replaced file foo, and replacement file .foo.tmp. If any step of
        #    this operation fails, reclassify as a conflict and stop.
        #
        # Returns the path of the destination file.

        precondition_abspath(abspath_u)
        replacement_path_u = abspath_u + u".tmp"  # FIXME more unique
        backup_path_u = abspath_u + u".backup"
        if now is None:
            now = time.time()

        # ensure parent directory exists
        head, tail = os.path.split(abspath_u)

        old_mask = os.umask(self._umask)
        try:
            fileutil.make_dirs(head, (~ self._umask) & 0777)
            fileutil.write(replacement_path_u, file_contents)
        finally:
            os.umask(old_mask)

        os.utime(replacement_path_u, (now, now - self.FUDGE_SECONDS))
        if is_conflict:
            print "0x00 ------------ <><> is conflict; calling _rename_conflicted_file... %r %r" % (abspath_u, replacement_path_u)
            return self._rename_conflicted_file(abspath_u, replacement_path_u)
        else:
            try:
                fileutil.replace_file(abspath_u, replacement_path_u, backup_path_u)
                return abspath_u
            except fileutil.ConflictError:
                return self._rename_conflicted_file(abspath_u, replacement_path_u)

    def _rename_conflicted_file(self, abspath_u, replacement_path_u):
        self._log("_rename_conflicted_file(%r, %r)" % (abspath_u, replacement_path_u))

        conflict_path_u = self._get_conflicted_filename(abspath_u)
        print "XXX rename %r %r" % (replacement_path_u, conflict_path_u)
        if os.path.isfile(replacement_path_u):
            print "%r exists" % (replacement_path_u,)
        if os.path.isfile(conflict_path_u):
            print "%r exists" % (conflict_path_u,)

        fileutil.rename_no_overwrite(replacement_path_u, conflict_path_u)
        return conflict_path_u

    def _rename_deleted_file(self, abspath_u):
        self._log('renaming deleted file to backup: %s' % (abspath_u,))
        try:
            fileutil.rename_no_overwrite(abspath_u, abspath_u + u'.backup')
        except OSError:
            self._log("Already gone: '%s'" % (abspath_u,))
        return abspath_u


class Downloader(QueueMixin, WriteFileMixin):
    REMOTE_SCAN_INTERVAL = 3  # facilitates tests

    def __init__(self, client, local_path_u, db, collective_dirnode,
                 upload_readonly_dircap, clock, is_upload_pending, umask):
        QueueMixin.__init__(self, client, local_path_u, db, 'downloader', clock)

        if not IDirectoryNode.providedBy(collective_dirnode):
            raise AssertionError("The URI in '%s' does not refer to a directory."
                                 % os.path.join('private', 'collective_dircap'))
        if collective_dirnode.is_unknown() or not collective_dirnode.is_readonly():
            raise AssertionError("The URI in '%s' is not a readonly cap to a directory."
                                 % os.path.join('private', 'collective_dircap'))

        self._collective_dirnode = collective_dirnode
        self._upload_readonly_dircap = upload_readonly_dircap
        self._is_upload_pending = is_upload_pending
        self._umask = umask

    def start_downloading(self):
        self._log("start_downloading")
        files = self._db.get_all_relpaths()
        self._log("all files %s" % files)

        d = self._scan_remote_collective(scan_self=True)
        d.addBoth(self._logcb, "after _scan_remote_collective 0")
        self._turn_deque()
        return d

    def stop(self):
        self._stopped = True
        d = defer.succeed(None)
        d.addCallback(lambda ign: self._lazy_tail)
        return d

    def _should_download(self, relpath_u, remote_version):
        """
        _should_download returns a bool indicating whether or not a remote object should be downloaded.
        We check the remote metadata version against our magic-folder db version number;
        latest version wins.
        """
        self._log("_should_download(%r, %r)" % (relpath_u, remote_version))
        if magicpath.should_ignore_file(relpath_u):
            self._log("nope")
            return False
        self._log("yep")
        db_entry = self._db.get_db_entry(relpath_u)
        if db_entry is None:
            return True
        self._log("version %r" % (db_entry.version,))
        return (db_entry.version < remote_version)

    def _get_local_latest(self, relpath_u):
        """
        _get_local_latest takes a unicode path string checks to see if this file object
        exists in our magic-folder db; if not then return None
        else check for an entry in our magic-folder db and return the version number.
        """
        if not self._get_filepath(relpath_u).exists():
            return None
        db_entry = self._db.get_db_entry(relpath_u)
        return None if db_entry is None else db_entry.version

    def _get_collective_latest_file(self, filename):
        """
        _get_collective_latest_file takes a file path pointing to a file managed by
        magic-folder and returns a deferred that fires with the two tuple containing a
        file node and metadata for the latest version of the file located in the
        magic-folder collective directory.
        """
        collective_dirmap_d = self._collective_dirnode.list()
        def scan_collective(result):
            list_of_deferreds = []
            for dir_name in result.keys():
                # XXX make sure it's a directory
                d = defer.succeed(None)
                d.addCallback(lambda x, dir_name=dir_name: result[dir_name][0].get_child_and_metadata(filename))
                list_of_deferreds.append(d)
            deferList = defer.DeferredList(list_of_deferreds, consumeErrors=True)
            return deferList
        collective_dirmap_d.addCallback(scan_collective)
        def highest_version(deferredList):
            max_version = 0
            metadata = None
            node = None
            for success, result in deferredList:
                if success:
                    if result[1]['version'] > max_version:
                        node, metadata = result
                        max_version = result[1]['version']
            return node, metadata
        collective_dirmap_d.addCallback(highest_version)
        return collective_dirmap_d

    def _scan_remote_dmd(self, nickname, dirnode, scan_batch):
        self._log("_scan_remote_dmd nickname %r" % (nickname,))
        d = dirnode.list()
        def scan_listing(listing_map):
            for encoded_relpath_u in listing_map.keys():
                relpath_u = magicpath.magic2path(encoded_relpath_u)
                self._log("found %r" % (relpath_u,))

                file_node, metadata = listing_map[encoded_relpath_u]
                local_version = self._get_local_latest(relpath_u)
                remote_version = metadata.get('version', None)
                self._log("%r has local version %r, remote version %r" % (relpath_u, local_version, remote_version))

                if local_version is None or remote_version is None or local_version < remote_version:
                    self._log("%r added to download queue" % (relpath_u,))
                    if scan_batch.has_key(relpath_u):
                        scan_batch[relpath_u] += [(file_node, metadata)]
                    else:
                        scan_batch[relpath_u] = [(file_node, metadata)]

        d.addCallback(scan_listing)
        d.addBoth(self._logcb, "end of _scan_remote_dmd")
        return d

    def _scan_remote_collective(self, scan_self=False):
        self._log("_scan_remote_collective")
        scan_batch = {}  # path -> [(filenode, metadata)]

        d = self._collective_dirnode.list()
        def scan_collective(dirmap):
            d2 = defer.succeed(None)
            for dir_name in dirmap:
                (dirnode, metadata) = dirmap[dir_name]
                if scan_self or dirnode.get_readonly_uri() != self._upload_readonly_dircap:
                    d2.addCallback(lambda ign, dir_name=dir_name, dirnode=dirnode:
                                   self._scan_remote_dmd(dir_name, dirnode, scan_batch))
                    def _err(f, dir_name=dir_name):
                        self._log("failed to scan DMD for client %r: %s" % (dir_name, f))
                        # XXX what should we do to make this failure more visible to users?
                    d2.addErrback(_err)

            return d2
        d.addCallback(scan_collective)

        def _filter_batch_to_deque(ign):
            self._log("deque = %r, scan_batch = %r" % (self._deque, scan_batch))
            for relpath_u in scan_batch.keys():
                file_node, metadata = max(scan_batch[relpath_u], key=lambda x: x[1]['version'])

                if self._should_download(relpath_u, metadata['version']):
                    self._deque.append( (relpath_u, file_node, metadata) )
                else:
                    self._log("Excluding %r" % (relpath_u,))
                    self._call_hook(None, 'processed')

            self._log("deque after = %r" % (self._deque,))
        d.addCallback(_filter_batch_to_deque)
        return d

    def _when_queue_is_empty(self):
        d = task.deferLater(self._clock, self.REMOTE_SCAN_INTERVAL, self._scan_remote_collective)
        d.addBoth(self._logcb, "after _scan_remote_collective 1")
        d.addCallback(lambda ign: self._turn_deque())
        return d

    def _process(self, item, now=None):
        # Downloader
        self._log("_process(%r)" % (item,))
        if now is None:
            now = time.time()
        (relpath_u, file_node, metadata) = item
        fp = self._get_filepath(relpath_u)
        abspath_u = unicode_from_filepath(fp)
        conflict_path_u = self._get_conflicted_filename(abspath_u)

        d = defer.succeed(None)

        def do_update_db(written_abspath_u):
            filecap = file_node.get_uri()
            last_uploaded_uri = metadata.get('last_uploaded_uri', None)
            last_downloaded_uri = filecap
            last_downloaded_timestamp = now
            written_pathinfo = get_pathinfo(written_abspath_u)

            if not written_pathinfo.exists and not metadata.get('deleted', False):
                raise Exception("downloaded object %s disappeared" % quote_local_unicode_path(written_abspath_u))

            self._db.did_upload_version(relpath_u, metadata['version'], last_uploaded_uri,
                                        last_downloaded_uri, last_downloaded_timestamp, written_pathinfo)
            self._count('objects_downloaded')
        def failed(f):
            self._log("download failed: %s" % (str(f),))
            self._count('objects_failed')
            return f

        if os.path.isfile(conflict_path_u):
            def fail(res):
                raise ConflictError("download failed: already conflicted: %r" % (relpath_u,))
            d.addCallback(fail)
        else:
            is_conflict = False
            db_entry = self._db.get_db_entry(relpath_u)
            dmd_last_downloaded_uri = metadata.get('last_downloaded_uri', None)
            dmd_last_uploaded_uri = metadata.get('last_uploaded_uri', None)
            if db_entry:
                if dmd_last_downloaded_uri is not None and db_entry.last_downloaded_uri is not None:
                    if dmd_last_downloaded_uri != db_entry.last_downloaded_uri:
                        is_conflict = True
                        self._count('objects_conflicted')
                elif dmd_last_uploaded_uri is not None and dmd_last_uploaded_uri != db_entry.last_uploaded_uri:
                    is_conflict = True
                    self._count('objects_conflicted')
                elif self._is_upload_pending(relpath_u):
                    is_conflict = True
                    self._count('objects_conflicted')

            if relpath_u.endswith(u"/"):
                if metadata.get('deleted', False):
                    self._log("rmdir(%r) ignored" % (abspath_u,))
                else:
                    self._log("mkdir(%r)" % (abspath_u,))
                    d.addCallback(lambda ign: fileutil.make_dirs(abspath_u))
                    d.addCallback(lambda ign: abspath_u)
            else:
                if metadata.get('deleted', False):
                    d.addCallback(lambda ign: self._rename_deleted_file(abspath_u))
                else:
                    d.addCallback(lambda ign: file_node.download_best_version())
                    d.addCallback(lambda contents: self._write_downloaded_file(abspath_u, contents,
                                                                               is_conflict=is_conflict))

        d.addCallbacks(do_update_db, failed)

        def trap_conflicts(f):
            f.trap(ConflictError)
            return None
        d.addErrback(trap_conflicts)
        return d
