#! /usr/bin/python

def read(fn): return open(fn).read()

# the output of this program will be evaluated in a document in which the SES
# setup libraries have been loaded: whitelist.js, atLeastFreeVarNames.js,
# WeakMap.js, and initSES.js .

# user.js is expected to be a CommonJS module that exports a 'main' function.
# This function will be invoked with one argument, 'endowments', which is an
# object whose contents depend upon the environment in which user.js is being
# loaded.

# demo environment: we call setup(endowments) at startup, then later we call
# press() when a button is pressed. The only endowment is a function named
# count().

print read("endowments.js") # this defines 'endowments'
user = read("user.js")
user_s = 'var user_s = "%s";' % user.replace('"', '\\"').replace("\n","\\n")
print user_s
print read("kernel.js")

