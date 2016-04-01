
import sys
from collections import namedtuple

from allmydata.util.dbutil import get_db, DBError


# magic-folder db schema version 1
SCHEMA_v1 = """
CREATE TABLE version
(
 version INTEGER  -- contains one row, set to 1
);

CREATE TABLE local_files
(
 path                VARCHAR(1024) PRIMARY KEY, -- UTF-8 filename relative to local magic folder dir
 -- note that size is before mtime and ctime here, but after in function parameters
 size                INTEGER,                   -- ST_SIZE, or NULL if the file has been deleted
 mtime               NUMBER,                      -- ST_MTIME
 ctime               NUMBER,                      -- ST_CTIME
 version             INTEGER,
 last_uploaded_uri   VARCHAR(256),                -- URI:CHK:...
 last_downloaded_uri VARCHAR(256),                -- URI:CHK:...
 last_downloaded_timestamp TIMESTAMP
);
"""


def get_magicfolderdb(dbfile, stderr=sys.stderr,
                      create_version=(SCHEMA_v1, 1), just_create=False):
    # Open or create the given backupdb file. The parent directory must
    # exist.
    try:
        (sqlite3, db) = get_db(dbfile, stderr, create_version,
                               just_create=just_create, dbname="magicfolderdb")
        if create_version[1] in (1, 2):
            return MagicFolderDB(sqlite3, db)
        else:
            print >>stderr, "invalid magicfolderdb schema version specified"
            return None
    except DBError, e:
        print >>stderr, e
        return None

PathEntry = namedtuple('PathEntry', 'size mtime ctime version last_uploaded_uri last_downloaded_uri last_downloaded_timestamp')

class MagicFolderDB(object):
    VERSION = 1

    def __init__(self, sqlite_module, connection):
        self.sqlite_module = sqlite_module
        self.connection = connection
        self.cursor = connection.cursor()

    def get_db_entry(self, relpath_u):
        """
        Retrieve the entry in the database for a given path, or return None
        if there is no such entry.
        """
        c = self.cursor
        c.execute("SELECT size, mtime, ctime, version, last_uploaded_uri, last_downloaded_uri, last_downloaded_timestamp"
                  " FROM local_files"
                  " WHERE path=?",
                  (relpath_u,))
        row = self.cursor.fetchone()
        if not row:
            print "no dbentry for %r" % (relpath_u,)
            return None
        else:
            (size, mtime, ctime, version, last_uploaded_uri, last_downloaded_uri, last_downloaded_timestamp) = row
            return PathEntry(size=size, mtime=mtime, ctime=ctime, version=version,
                             last_uploaded_uri=last_uploaded_uri,
                             last_downloaded_uri=last_downloaded_uri,
                             last_downloaded_timestamp=last_downloaded_timestamp)

    def get_all_relpaths(self):
        """
        Retrieve a set of all relpaths of files that have had an entry in magic folder db
        (i.e. that have been downloaded at least once).
        """
        self.cursor.execute("SELECT path FROM local_files")
        rows = self.cursor.fetchall()
        return set([r[0] for r in rows])

    def did_upload_version(self, relpath_u, version, last_uploaded_uri, last_downloaded_uri, last_downloaded_timestamp, pathinfo):
        print "%r.did_upload_version(%r, %r, %r, %r, %r, %r)" % (self, relpath_u, version, last_uploaded_uri, last_downloaded_uri, last_downloaded_timestamp, pathinfo)
        try:
            print "insert"
            self.cursor.execute("INSERT INTO local_files VALUES (?,?,?,?,?,?,?,?)",
                                (relpath_u, pathinfo.size, pathinfo.mtime, pathinfo.ctime, version, last_uploaded_uri, last_downloaded_uri, last_downloaded_timestamp))
        except (self.sqlite_module.IntegrityError, self.sqlite_module.OperationalError):
            print "err... update"
            self.cursor.execute("UPDATE local_files"
                                " SET size=?, mtime=?, ctime=?, version=?, last_uploaded_uri=?, last_downloaded_uri=?, last_downloaded_timestamp=?"
                                " WHERE path=?",
                                (pathinfo.size, pathinfo.mtime, pathinfo.ctime, version, last_uploaded_uri, last_downloaded_uri, last_downloaded_timestamp, relpath_u))
        self.connection.commit()
        print "committed"
