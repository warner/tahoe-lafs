
initSES(window, whitelist, atLeastFreeVarNames);
// now Function, eval2, and cajaVM are defined
var modMaker = cajaVM.compileModule(user_s);
// we ignore modMaker.requirements . If we were paying attention to it, we'd
// use modMaker.requirements to figure out what dependencies needed to be
// loaded, then we'd pass a 'require' property into modMaker() that could
// return them.
var exported = {};
// we also ignore returned, which is what comes out of a top-level return()
// in user.js .
var returned = modMaker({exports: exported});

// map inputs to the guest code
function press() {
  exported.press();
}
function evil() {
  exported.evil();
}
// call the guest's setup() when we're ready
$(window).ready(function() { exported.setup(endowments); });
