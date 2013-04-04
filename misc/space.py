import sys, gzip, copy, math

prefix = sys.argv[1]
if prefix.endswith("/"):
    prefix = prefix[:-1]
prefixbits = prefix.split("/")

class Directory:
    __slots__ = ["frontend_bytes",
                 "backend_bytes",
                 "num_files",
                 "num_dirs",
                 "num_objects",
                 "full_upload_time",
                 "null_upload_time",
                 "children"
                 ]

class File:
    __slots__ = ["frontend_bytes",
                 "backend_bytes",
                 "full_upload_time",
                 "null_upload_time",
                 ]

def backend_bytes(bytes):
    # 2275 frontend -> 3529 share, FS rounds up to 512-byte boundary
    backend_file_bytes = bytes + 1254
    backend_block_bytes = 512*math.ceil(backend_file_bytes/512.0)
    # add 4 blocks for the bucket directory
    return 4*512 + backend_block_bytes
def full_upload_time(bytes):
    # 60ms for tiny files, plus about 3.5MBps
    return .060 + bytes / 3.5e6
def null_upload_time(bytes):
    # this is really fast, I haven't quite measured it yet
    return .001

def add_to(s, isdir, bytes):
    # use the size of directories as a proxy for the size of the DIR-CHK
    # we'll need to hold it.
    s["frontend_bytes"] += bytes
    s["backend_bytes"] += backend_bytes(bytes)
    s["num_objects"] += 1
    if isdir:
        s["num_dirs"] += 1
    else:
        s["num_files"] += 1
    s["full_upload_time"] += full_upload_time(bytes)
    s["null_upload_time"] += null_upload_time(bytes)

# 2m08s to 'find ~ -ls'

# 11s to walk all 2M lines
#f = gzip.open("all-files-10-feb-2013.txt.gz", "rb")
lineno = 0
for line in sys.stdin.readlines():
    lineno += 1
    if lineno % 10000 == 0:
        print lineno
    bits = line.rstrip("\n").split(None, 10)
    inodeno, blocks, perms, links, owner, group, bytes = bits[0:7]
    blocks = int(blocks)
    bytes = int(bytes)
    isdir = perms.startswith("d")
    mtime_s = bits[7:10]
    path = bits[10]
    #print path
    if perms.startswith("l"):
        continue # skip symlinks
    if not path.startswith(prefix+"/"):
        continue
    pathbits = path.split("/")
    if len(pathbits) == len(prefixbits):
        continue
    if len(pathbits) == len(prefixbits)+1:
        if not isdir:
            add_to(prefix_space, isdir, bytes)
            continue
    subdir_name = pathbits[len(prefixbits)]
    if subdir_name not in subdirs:
        subdirs[subdir_name] = copy.copy(subdir_template)
    add_to(subdirs[subdir_name], isdir, bytes)
    add_to(prefix_space, isdir, bytes)

subdirs[""] = prefix_space
maxsubdirname = max([len(subdir) for subdir in subdirs])
hdrstr = "%%%ds" % maxsubdirname + " %12s %12s %7s %7s %7s %10s %7s"
fmtstr = "%%%ds" % maxsubdirname + " %12d %12d %7d %7d %7d %10.1f %7.1f"
print hdrstr % ("name", "frontend", "backend", "files", "dirs", "objs", " full_up", "null_up")
print hdrstr % ("----", "--------", "-------", "-----", "----", "----", "--------", "-------")
for subdir in reversed(sorted(subdirs, key=lambda subdir: subdirs[subdir]["full_upload_time"])):
    s = subdirs[subdir]
    print fmtstr % (subdir, s["frontend_bytes"], s["backend_bytes"],
                    s["num_files"], s["num_dirs"], s["num_objects"],
                    s["full_upload_time"], s["null_upload_time"])
