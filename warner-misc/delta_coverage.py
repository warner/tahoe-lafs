#! /usr/bin/python

import os, sys
from coverage import coverage
from coverage.report import Reporter

def load(fn):
    c = coverage(data_file=fn)
    c.load()
    r = Reporter(c)
    r.find_code_units(None, ["/System", "/Library", "/usr/lib",
                             "support/lib", "src/allmydata/test"])

    return c, r.code_units

def get_coverage(c, cu):
    (fn, executable, missing, mf) = c.analysis(cu)
    code_linenumbers = set(executable)
    uncovered_linenumbers = set(missing)
    covered_linenumbers = code_linenumbers - uncovered_linenumbers
    return (code_linenumbers, uncovered_linenumbers, covered_linenumbers)

fn1,fn2 = sys.argv[1], sys.argv[2]
c1,cu1 = load(fn1); c2,cu2 = load(fn2)
c1_names = dict([(cu.name,cu) for cu in cu1])
c2_names = dict([(cu.name,cu) for cu in cu2])
all_names = set(c1_names.keys()) | set(c2_names.keys())

for name in sorted(all_names):
    if len(sys.argv) < 4:
        if name not in sys.argv[3:]:
            continue
    if name not in c1_names:
        print "%s: not in %s" % (name, fn1)
    elif name not in c2_names:
        print "%s: not in %s" % (name, fn2)
    else:
        code1, uncovered1, covered1 = get_coverage(c1, c1_names[name])
        code2, uncovered2, covered2 = get_coverage(c2, c2_names[name])
        in_1_not_2 = covered1 - covered2
        in_2_not_1 = covered2 - covered1
        if not in_1_not_2 and not in_2_not_1:
            continue
        print "%s:" % name
        if in_1_not_2:
            print " covered in %s but not in %s:" % (sys.argv[1], sys.argv[2])
            print " ", ",".join([str(ln) for ln in sorted(in_1_not_2)])
        if in_2_not_1:
            print " covered in %s but not in %s:" % (sys.argv[2], sys.argv[1])
            print " ", ",".join([str(ln) for ln in sorted(in_2_not_1)])

