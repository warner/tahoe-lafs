"use strict";

// Copyright (C) 2010 Google Inc.
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

var atLeastFreeVarNames = (function()
{

  /////////////// KLUDGE SWITCHES ///////////////

  function LIMIT_SRC(programSrc) {
    if (!((/^[\u0000-\u007f]*$/m).test(programSrc))) {
      throw new Error('Non-ascii texts not yet supported');
    }
  }

  // This is safe only because of the above LIMIT_SRC
  // To do this right takes quite a lot of unicode machinery. See
  // the "Identifier" production at
  // http://es-lab.googlecode.com/svn/trunk/src/parser/es5parser.ojs
  // which depends on
  // http://es-lab.googlecode.com/svn/trunk/src/parser/unicode.js
  var SHOULD_MATCH_IDENTIFIER = (/(\w|\$)+/gm);


  /////////////////////////////////
  // The following are only the minimal kludges needed for the current
  // Mozilla Minefield (Firefox Beta) or Chromium Beta. At the time of
  // this writing, these are Mozilla 4.0b5pre and Chromium 6.0.490.0
  // (3135). As these move forward, kludges can be removed until we
  // simply rely on ES5.

  //var SHOULD_BE_NULL = null;
  var SHOULD_BE_NULL = Object.prototype;

  //////////////// END KLUDGE SWITCHES ///////////

  /**
   * The result should include at least all the free variable names of
   * {@code programSrc}.
   *
   * Assuming that programSrc that parses as a strict Program,
   * atLeastFreeVarNames(programSrc) returns a Record whose enumerable
   * property names must include the names of all the free variables
   * occuring in programSrc. It can include as many other strings as is
   * convenient so long as it includes these. The value of each of these
   * properties should be {@code true}.
   */
  function atLeastFreeVarNames(programSrc) {
    programSrc = String(programSrc);
    LIMIT_SRC(programSrc);
    // Now that we've temporarily limited our attention to ascii...
    var ident = SHOULD_MATCH_IDENTIFIER;
    var result = Object.create(SHOULD_BE_NULL);
    var a;
    while ((a = ident.exec(programSrc))) {
      result[a[0]] = true;
    }
    return result;
  }
  return atLeastFreeVarNames;

})();
