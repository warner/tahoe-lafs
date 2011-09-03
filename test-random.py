#! /usr/bin/python

import os, sys, httplib, base64, itertools
from hashlib import md5

host = "localhost"
port = 3456
# create the file with 'dd if=/dev/zero bs=1048576 count=4 |tahoe put -m --mutable-type=mdmf' -
filecap = "URI:MDMF:vvukmpmb4yjhe7nddfmngdiwj4:7dlgggsv5jmungltqlfonkj2odig6tpc3n6ftksk5htu3woas7ya:3:131073"
seed = "1"
M = 1024*1024
FILESIZE = 4*M
LENRANGE = 1*M
firststep = 0
if len(sys.argv) > 1:
    firststep = int(sys.argv[1])

def PRAG(seed, length):
    chunks = []
    count = 0
    while length > 0:
        chunkseed = md5("%s:%d"%(seed,count)).digest()
        data = base64.b64encode(chunkseed).strip("=")
        count += 1
        use = data[:max(length, len(data))]
        chunks.append(use)
        length -= len(use)
    return "".join(chunks)

def make_operation(step):
    assert FILESIZE <= 16**6
    assert LENRANGE <= 16**6
    opseed = "%s:%d" % (seed, step)
    opdata = md5(opseed).hexdigest() # 16 bytes, 32 hex chars
    offset = int(opdata[0:6], 16) % FILESIZE
    datalen = int(opdata[6:12], 16) % LENRANGE
    data = PRAG(opdata[12:16], datalen)
    return (offset, data)

def GET():
    c = httplib.HTTPConnection("localhost", 3456)
    c.putrequest("GET", "/uri/%s" % (filecap,))
    c.putheader("Accept", "text/plain, application/octet-stream")
    c.putheader("Connection", "close")
    c.putheader("Content-Length", "0")
    c.endheaders()
    r = c.getresponse()
    if r.status < 200 or r.status >= 300:
        print "Error during GET"
        print r.status, r.reason
        print r.read()
        raise RuntimeError
    return r.read()

def PUT(offset, data):
    c = httplib.HTTPConnection("localhost", 3456)
    c.putrequest("PUT", "/uri/%s?offset=%d" % (filecap, offset))
    c.putheader("Accept", "text/plain, application/octet-stream")
    c.putheader("Connection", "close")
    c.putheader("Content-Length", str(len(data)))
    c.endheaders()
    c.send(data)
    r = c.getresponse()
    if r.status < 200 or r.status >= 300:
        print "Error during PUT"
        print r.status, r.reason
        print r.read()
        raise RuntimeError

def test():
    old = GET()
    for step in itertools.count(firststep):
        (offset, data) = make_operation(step)
        print "step %d: write %d bytes at offset %d (%s..%s)" % (
            step, len(data), offset, data[:20], data[-20:])
        expected = (old[:offset] + data + old[offset+len(data):])
        PUT(offset, data)
        new = GET()
        if new != expected:
            print "content mismatch"
            open("test-random-old.data", "wb").write(old)
            open("test-random-expected.data", "wb").write(expected)
            open("test-random-new.data", "wb").write(new)
            print "see test-random-{old,expected,new}.data"
            break
        old = new




if __name__ == '__main__':
    test()

