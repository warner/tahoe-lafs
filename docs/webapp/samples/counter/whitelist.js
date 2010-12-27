"use strict";

// Copyright (C) 2009 Google Inc.
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
// http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

/**
 * The comment "Harmless whatwg" refers to extensions documented at
 * http://wiki.whatwg.org/wiki/Web_ECMAScript that do seem to be
 * harmless. Note that the RegExp constructor extensions on that page
 * are <b>not harmless</b> and so must not be whitelisted.
 */


var whitelist = {
  "cajaVM": {                        // Caja support
    "log": true,
    "compile": true,
    "compileModule": true,           // experimental
    "protect": true
  },
  "Q": {                             // Dr. SES support
    "get": true,
    "post": true,
    "when": true,
    "near": true,
    "def": true
  },
  "WeakMap": true,                   // ES-Harmony proposal
  "Proxy": {                         // ES-Harmony proposal
    "create": true,
    "createFunction": true
  },
  "escape": true,                    // ES5 Appendix B
  "unescape": true,                  // ES5 Appendix B
  "Object": {
    "getPropertyDescriptor": true,   // ES-Harmony proposal
    "getPropertyNames": true,        // ES-Harmony proposal
    "eq": true,                      // ES-Harmony strawman
    "prototype": {
      "constructor": "*",
      "toString": "*",
      "toLocaleString": "*",
      "valueOf": true,
      "hasOwnProperty": true,
      "isPrototypeOf": true,
      "propertyIsEnumerable": true
    },
    "getPrototypeOf": true,
    "getOwnPropertyDescriptor": true,
    "getOwnPropertyNames": true,
    "create": true,
    "defineProperty": true,
    "defineProperties": true,
    "seal": true,
    "freeze": true,
    "preventExtensions": true,
    "isSealed": true,
    "isFrozen": true,
    "isExtensible": true,
    "keys": true
  },
  "NaN": true,
  "Infinity": true,
  "undefined": true,
  "eval": true,
  "parseInt": true,
  "parseFloat": true,
  "isNaN": true,
  "isFinite": true,
  "decodeURI": true,
  "decodeURIComponent": true,
  "encodeURI": true,
  "encodeURIComponent": true,
  "Function": {
    "prototype": {
      "apply": true,
      "call": true,
      "bind": true,
      "prototype": "*",
      "length": "*",
      "caller": "skip",    // when not poison, could be fatal
      "arguments": "skip", // when not poison, could be fatal
      "arity": "skip",     // non-std, deprecated in favor of length
      "name": "skip"       // non-std
    }
  },
  "Array": {
    "prototype": {
      "concat": true,
      "join": true,
      "pop": true,
      "push": true,
      "reverse": true,
      "shift": true,
      "slice": true,
      "sort": true,
      "splice": true,
      "unshift": true,
      "indexOf": true,
      "lastIndexOf": true,
      "every": true,
      "some": true,
      "forEach": true,
      "map": true,
      "filter": true,
      "reduce": true,
      "reduceRight": true,
      "length": "skip"       // can't be redefined on Mozilla
    },
    "isArray": true
  },
  "String": {
    "prototype": {
      "substr": true,                // ES5 Appendix B
      "anchor": true,                // Harmless whatwg
      "big": true,                   // Harmless whatwg
      "blink": true,                 // Harmless whatwg
      "bold": true,                  // Harmless whatwg
      "fixed": true,                 // Harmless whatwg
      "fontcolor": true,             // Harmless whatwg
      "fontsize": true,              // Harmless whatwg
      "italics": true,               // Harmless whatwg
      "link": true,                  // Harmless whatwg
      "small": true,                 // Harmless whatwg
      "strike": true,                // Harmless whatwg
      "sub": true,                   // Harmless whatwg
      "sup": true,                   // Harmless whatwg
      "trimLeft": true,              // non-standard
      "trimRight": true,             // non-standard
      "valueOf": true,
      "charAt": true,
      "charCodeAt": true,
      "concat": true,
      "indexOf": true,
      "lastIndexOf": true,
      "localeCompare": true,
      "match": true,
      "replace": true,
      "search": true,
      "slice": true,
      "split": true,
      "substring": true,
      "toLowerCase": true,
      "toLocaleLowerCase": true,
      "toUpperCase": true,
      "toLocaleUpperCase": true,
      "trim": true,
      "length": "skip"           // can't be redefined on Mozilla
    },
    "fromCharCode": true
  },
  "Boolean": {
    "prototype": {
      "valueOf": true
    }
  },
  "Number": {
    "prototype": {
      "valueOf": true,
      "toFixed": true,
      "toExponential": true,
      "toPrecision": true
    },
    "MAX_VALUE": true,
    "MIN_VALUE": true,
    "NaN": true,
    "NEGATIVE_INFINITY": true,
    "POSITIVE_INFINITY": true
  },
  "Math": {
    "E": true,
    "LN10": true,
    "LN2": true,
    "LOG2E": true,
    "LOG10E": true,
    "PI": true,
    "SQRT1_2": true,
    "SQRT2": true,

    "abs": true,
    "acos": true,
    "asin": true,
    "atan": true,
    "atan2": true,
    "ceil": true,
    "cos": true,
    "exp": true,
    "floor": true,
    "log": true,
    "max": true,
    "min": true,
    "pow": true,
    "random": true, // questionable
    "round": true,
    "sin": true,
    "sqrt": true,
    "tan": true
  },
  "Date": {        // no-arg Date constructor is questionable
    "prototype": {
      "getYear": true,               // ES5 Appendix B
      "setYear": true,               // ES5 Appendix B
      "toGMTString": true,           // ES5 Appendix B
      "toDateString": true,
      "toTimeString": true,
      "toLocaleString": true,
      "toLocaleDateString": true,
      "toLocaleTimeString": true,
      "getTime": true,
      "getFullYear": true,
      "getUTCFullYear": true,
      "getMonth": true,
      "getUTCMonth": true,
      "getDate": true,
      "getUTCDate": true,
      "getDay": true,
      "getUTCDay": true,
      "getHours": true,
      "getUTCHours": true,
      "getMinutes": true,
      "getUTCMinutes": true,
      "getSeconds": true,
      "getUTCSeconds": true,
      "getMilliseconds": true,
      "getUTCMilliseconds": true,
      "getTimezoneOffset": true,
      "setTime": true,
      "setFullYear": true,
      "setUTCFullYear": true,
      "setMonth": true,
      "setUTCMonth": true,
      "setDate": true,
      "setUTCDate": true,
      "setHours": true,
      "setUTCHours": true,
      "setMinutes": true,
      "setUTCMinutes": true,
      "setSeconds": true,
      "setUTCSeconds": true,
      "setMilliseconds": true,
      "setUTCMilliseconds": true,
      "toUTCString": true,
      "toISOString": true,
      "toJSON": true
    },
    "parse": true,
    "UTC": true,
    "now": true    // questionable
  },
  "RegExp": {
    "prototype": {
      "exec": true,
      "test": true,
      "source": "skip",
      "global": "skip",
      "ignoreCase": "skip",
      "multiline": "skip",
      "lastIndex": "skip",
      "sticky": "skip"       // non-std
    }
  },
  "Error": {
    "prototype": {
      "name": "*",
      "message": "*"
    }
  },
  "EvalError": {
    "prototype": true
  },
  "RangeError": {
    "prototype": true
  },
  "ReferenceError": {
    "prototype": true
  },
  "SyntaxError": {
    "prototype": true
  },
  "TypeError": {
    "prototype": true
  },
  "URIError": {
    "prototype": true
  },
  "JSON": {
    "parse": true,
    "stringify": true
  }
};
