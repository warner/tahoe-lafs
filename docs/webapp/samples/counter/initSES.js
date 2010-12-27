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
 * Cleanse this frame or die trying.
 *
 * <p>Should be called before any other potentially dangerous script
 * is executed in this frame. If it succeeds, the new global bindings
 * for <tt>eval</tt> and <tt>Function</tt> in this frame will only
 * load code according to the <i>loader isolation</i> rules of the
 * object-capability model. If all other code executed directly in
 * this frame (i.e., other than through these <tt>eval</tt> and
 * <tt>Function</tt> bindings) takes care to uphold object-capability
 * rules, then untrusted code loaded via <tt>eval</tt> and
 * <tt>Function</tt> will be constrained by those rules.
 *
 * <p>On a pre-ES5 browser, this script will fail cleanly, leaving the
 * frame intact. Otherwise, if this script fails, it may leave this
 * frame in an unusable state. All following description assumes this
 * script succeeds and that the browser conforms to the ES5 spec. The
 * ES5 spec allows browsers to implement more than is specified as
 * long as certain invariants are maintained. We further assume that
 * these extensions are not maliciously designed to obey the letter of
 * these invariants while subverting the intent of the spec. In other
 * words, even on an ES5 conformant browser, we do not presume to
 * defend ourselves from a browser that is out to get us.
 *
 * @param global ::Record(any) Assumed to be the real global object for
 *        this frame. Since initSES will allow global variable
 *        references that appear at the top level of the whitelist,
 *        our safety depends on these variables being frozen as a side
 *        effect of freezing the corresponding properties of
 *        <tt>global</tt>. These properties are also duplicated onto a
 *        <i>root accessible primordial</i>, which is provided as the
 *        <tt>this</tt> binding for hermetic eval calls -- emulating
 *        the safe subset of the normal global object.
 * @param whitelist ::Record(Permit)
 *            where Permit = true | "*" | "skip" | Record(Permit).
 *        Describes the subset of naming paths starting from the root
 *        that should be accessible. The <i>accessible primordials</i>
 *        are this root plus all values found by navigating these paths
 *        starting from this root. All non-whitelisted properties of
 *        accessible primordials are deleted, and then all accessible
 *        primordials are frozen with the whitelisted properties
 *        frozen as data properties.
 * @param atLeastFreeVarNames ::F([string], Record(true))
 *        Given the sourceText for a strict Program,
 *        atLeastFreeVarNames(sourceText) returns a Record whose
 *        enumerable property names must include the names of all the
 *        free variables occuring in sourceText. It can include as
 *        many other strings as is convenient so long as it includes
 *        these. The value of each of these properties should be
 *        {@code true}.
 */
function initSES(global, whitelist, atLeastFreeVarNames) {


  /////////////// KLUDGE SWITCHES ///////////////

  //var ENUMERABILITY_SHOULD_BE_FALSE = false;
  var ENUMERABILITY_SHOULD_BE_FALSE = true;


  /////////////////////////////////
  // The following are only the minimal kludges needed for the current
  // Mozilla Minefield (Firefox Beta) or Chromium Beta. At the time of
  // this writing, these are Mozilla 4.0b5pre and Chromium 6.0.490.0
  // (3135). As these move forward, kludges can be removed until we
  // simply rely on ES5.

  //var SHOULD_BE_EVAL = 'eval';
  var SHOULD_BE_EVAL = 'eval2';


  //var SHOULD_BE_NULL = null;
  var SHOULD_BE_NULL = Object.prototype;

  //var REQUIRE_STRICT = true;
  var REQUIRE_STRICT = false;

  //var FREEZE_EARLY = undefined;
  var FREEZE_EARLY = Array.prototype.forEach;

  //////////////// END KLUDGE SWITCHES ///////////

  var dirty = true;

  function fail(str) { throw new EvalError(str); }

  if (REQUIRE_STRICT && function(){return this;}()) {
    fail('Requires at least ES5 support');
  }

  delete whitelist.eval;
  whitelist[SHOULD_BE_EVAL] = true;

  /**
   * Code being eval'ed sees <tt>root</tt> as its <tt>this</tt>, as if
   * <tt>root</tt> were the global object.
   *
   * <p>Root's properties are exactly the whitelistes global variable
   * references. These properties, both as they appear on the global
   * object and on this root object, are frozen and so cannot
   * diverge. This preserves the illusion.
   */
  var root = Object.create(SHOULD_BE_NULL);

  // Repair phase -- monkey patch safe replacements
  (function() {

    // The unsafe* variables hold precious values that must not escape
    // to untrusted code. When {@code eval} is invoked via {@code
    // unsafeEval}, this is a call to the indirect eval function, not
    // the direct eval operator.
    var unsafeEval = eval;
    var UnsafeFunction = Function;

    /**
     * Fails if {@code programSrc} does not parse as a strict Program
     * production.
     *
     * <p>Uses Ankur Taly's trick to cheaply check that a program
     * parses using the platform's parser, as implicitly accessed by
     * the original eval function, while nevertheless ensuring that no
     * code from {@code programSrc} executes in the process.
     */
    function verifyStrictProgram(programSrc) {
      try {
        unsafeEval('"use strict";\n' +
                   'throw "NotASyntaxError";\n' +
                   programSrc);
      } catch (ex) {
        if (ex !== 'NotASyntaxError') {
          throw ex;
        }
      }
    }

    /**
     * Fails if {@code exprSource} does not parse as a strict
     * Expression production.
     */
    function verifyStrictExpression(exprSrc) {
      verifyStrictProgram(exprSrc + ';');
      verifyStrictProgram('(\n' + exprSrc + '\n);');
    }

    /**
     * For all the enumerable own properties of {@code from}, copy
     * their descriptors to {@code virtualGlobal}, except that the
     * property added to {@code virtualGlobal} is unconditionally
     * non-enumerable and (for the moment) configurable.
     *
     * <p>By copying descriptors rather than values, any accessor
     * properties of {@code env} becomes an accessors of {code
     * virtualGlobal} with the same getter and setter. If these do not
     * use their {@code this} value, then the original any copied
     * properties are effectively joined.
     *
     * <p>We make these configurable so that {@code virtualGlobal} can
     * be further configured before being frozen. We make these
     * non-enumerable in order to emulate the normal behavior of
     * built-in properties of typical global objects, such as the
     * browser's {@code window} object.
     */
    function initGlobalProperties(from, virtualGlobal) {
      for (var name in from) {
        var desc = Object.getOwnPropertyDescriptor(from, name);
        if (desc) {
          desc.enumerable = ENUMERABILITY_SHOULD_BE_FALSE;
          desc.configurable = true;
          Object.defineProperty(virtualGlobal, name, desc);
        }
      }
    }

    /**
     * Make a frozen virtual global object whose properties are the
     * union of the whitelisted globals and the enumerable own
     * properties of {@code env}.
     *
     * <p>If there is a collision, the property from {@code env}
     * shadows the whitelisted global. We shadow by overwriting rather
     * than inheritance so that shadowing makes the original binding
     * inaccessible.
     */
    function makeVirtualGlobal(env) {
      var virtualGlobal = Object.create(SHOULD_BE_NULL);
      initGlobalProperties(root, virtualGlobal);
      initGlobalProperties(env, virtualGlobal);
      return Object.freeze(virtualGlobal);
    }

    /**
     * Make a frozen scope object which inherits from
     * {@code virtualGlobal}, for use by {@code with} to prevent
     * access to any {@code freeNames} other than those found on the.
     * {@code virtualGlobal}.
     */
    function makeScopeObject(virtualGlobal, freeNames) {
      var scopeObject = Object.create(virtualGlobal);
      for (var name in freeNames) {
        if (!(name in virtualGlobal)) {
          (function(name) {
            Object.defineProperty(scopeObject, name, {
              get: function() {
                throw new ReferenceError('"' + name + '" not in scope');
              },
              set: function(ignored) {
                throw new TypeError('Can\'t set "' + name + '"');
              },
              enumerable: true
            });
          })(name);
        }
      }
      return Object.freeze(scopeObject);
    }


    /**
     * Compile {@code exprSrc} as a strict expression into a function
     * of an environment {@code env}, that when called evaluates
     * {@code exprSrc} in a virtual global environment consisting only
     * of the whitelisted globals and a snapshot of the enumerable own
     * properties of {@code env}.
     *
     * <p>When SES {@code compile} is provided primitively, it should
     * accept a Program and return a function that evaluates it to the
     * Program's completion value. Unfortunately, this is not
     * practical as a library without some non-standard support from
     * the platform such as an parser API that provides an AST.
     *
     * <p>Thanks to Mike Samuel and Ankur Taly for this trick of using
     * {@code with} together with RegExp matching to intercept free
     * variable access without parsing.
     */
    function compile(exprSrc) {
      if (dirty) { fail('Initial cleaning failed'); }
      verifyStrictExpression(exprSrc);
      var freeNames = atLeastFreeVarNames(exprSrc);
      var wrapperSrc =
        '(function() {\n' +
        // non-strict code, where this === scopeObject
        '  with (this) {\n' +
        '    return function() {\n' +
        '      "use strict";\n' +
        '      return (\n' +
        // strict code, where this === virtualGlobal
        '        ' + exprSrc + '\n' +
        '      );\n' +
        '    };\n' +
        '  }\n' +
        '})';
      var wrapper = unsafeEval(wrapperSrc);
      return function(env) {
        var virtualGlobal = makeVirtualGlobal(env);
        var scopeObject = makeScopeObject(virtualGlobal, freeNames);
        return wrapper.call(scopeObject).call(virtualGlobal);
      };
    }

    var directivePattern = (/^\s*['"](?:\w|\s)*['"]\s*$/m);

    var requirePattern = (/^\s*(?:\w*\s*(?:\w|\$|\.)*\s*=\s*)?\s*require\s*\(\s*['"]((?:\w|\$|\.|\/)+)['"]\s*\)\s*$/m);

    /**
     * As an experiment, recognize a stereotyped prelude of the
     * CommonJS module system.
     */
    function getRequirements(modSrc) {
      var result = [];
      var stmts = modSrc.split(';');
      var i = 0, ilen = stmts.length;
      for (; i < ilen; i++) {
        if (!directivePattern.test(stmts[i])) { break; }
      }
      for (; i < ilen; i++) {
      var m = requirePattern.exec(stmts[i]);
        if (!m) { break; }
        result.push(m[1]);
      }
      return Object.freeze(result);
    }

    /**
     * A module source is actually any valid FunctionBody, and thus any valid
     * Program.
     *
     * <p>In addition, in case the module source happens to begin with
     * a streotyped prelude of the CommonJS module system, the
     * function resulting from module compilation has an additional
     * {@code "requirements"} property whose value is a list of the
     * module names being required by that prelude. These requirements
     * are the module's "immediate synchronous dependencies".
     *
     * <p>This {@code "requirements"} property is adequate to
     * bootstrap support for a CommonJS module system, since a loader
     * can first load and compile the transitive closure of an initial
     * module's synchronous depencies before actually executing any of
     * these module functions.
     *
     * <p>With a similarly lightweight RegExp, we should be able to
     * similarly recognize the {@code "load"} syntax of <a href=
     * "http://wiki.ecmascript.org/doku.php?id=strawman:simple_modules#syntax"
     * >Sam and Dave's module proposal for ES-Harmony</a>. However,
     * since browsers do not currently accept this syntax,
     * {@code getRequirements} above would also have to extract these
     * from the text to be compiled.
     */
    function compileModule(modSrc) {
      var moduleMaker = compile('(function() {' + modSrc + '}).call(this)');
      moduleMaker.requirements = getRequirements(modSrc);
      Object.freeze(moduleMaker.prototype);
      return Object.freeze(moduleMaker);
    }

    /**
     * A safe form of the {@code Function} constructor, which
     * constructs strict functions that can only refer freely to the
     * whitelisted globals.
     *
     * <p>The returned function is strict whether or not it declares
     * itself to be.
     */
    function FakeFunction(var_args) {
      var params = [].slice.call(arguments, 0);
      var body = params.pop();
      body = String(body || '');
      params = params.join(',');
      var exprSrc = '(function(' + params + '\n){' + body + '})';
      return compile(exprSrc)({});
    }
    FakeFunction.prototype = UnsafeFunction.prototype;
    FakeFunction.prototype.constructor = FakeFunction;
    global.Function = FakeFunction;

    /**
     * A safe form of the indirect {@code eval} function, which
     * evaluates {@code src} as strict code that can only refer freely
     * to the whitelisted globals.
     *
     * <p>Given our parserless methods of verifying untrusted sources,
     * we unfortunately have no practical way to obtain the completion
     * value of a safely evaluated Program. Instead, we adopt a
     * compromise based on the following observation. All Expressions
     * are valid Programs, and all Programs are valid
     * FunctionBodys. If {@code src} parses as a strict expression,
     * then we evaluate it as an expression it and correctly return its
     * completion value, since that is simply the value of the
     * expression.
     *
     * <p>Otherwise, we evaluate {@code src} as a FunctionBody and
     * return what that would return from its implicit enclosing
     * function. If {@code src} is simply a Program, then it would not
     * have an explicit {@code return} statement, and so we fail to
     * return its completion value. This is sufficient for using
     * {@code eval} to emulate script tags, since script tags also
     * lose the completion value.
     *
     * <p>When SES {@code eval} is provided primitively, it should
     * accept a Program and evaluate it to the Program's completion
     * value. Unfortunately, this is not practical as a library
     * without some non-standard support from the platform such as an
     * parser API that provides an AST.
     */
    function fakeEval(src) {
      try {
        verifyStrictExpression(src);
      } catch (x) {
        src = '(function() {' + src + '}).call(this)';
      }
      return compile(src)({});
    }
    global[SHOULD_BE_EVAL] = fakeEval;

    var solids = WeakMap();

    global.cajaVM = {
      log: function(str) {
        if (typeof console !== 'undefined' &&
            typeof console.log === 'function') {
          console.log(str);
        }
      },

      compile: compile,
      compileModule: compileModule,

      protect: function(root) {
        var protecting = WeakMap();
        var memo = [];
        function recur(val) {
          if (val !== Object(val)) { return; }
          if (solids.get(val)) { return; }
          if (protecting.get(val)) { return; }
          protecting.set(val, true);
          memo.push(val);
          Object.freeze(val);
          recur(Object.getPrototypeOf(val));
          Object.getOwnPropertyNames(val).forEach(function(name) {
            recur(Object.getOwnPropertyDescriptor(val));
          });
        }
        recur(root);
        memo.forEach(function(obj) { solids.set(obj, true); });
        return root;
      }
    };

  })();

  var cantNeuter = [];

  /**
   * Read the current value of base[name], and freeze that property as
   * a data property to ensure that all further reads of that same
   * property from that base produce the same value.
   *
   * <p>The frozen property should preserve the enumerability of the
   * original property.
   */
  function read(base, name) {
    var desc = Object.getOwnPropertyDescriptor(base, name);
    if (desc && 'value' in desc && !desc.writable && !desc.configurable) {
      return desc.value;
    }

    var result = base[name];
    try {
      Object.defineProperty(base, name, {
        value: result, writable: false, configurable: false
      });
    } catch (ex) {
      cantNeuter.push({base: base, name: name, err: ex});
    }
    return result;
  }

  // initialize accessible global variables and root
  Object.keys(whitelist).forEach(function(name) {
    var desc = Object.getOwnPropertyDescriptor(global, name);
    if (desc) {
      var permit = whitelist[name];
      if (permit) {
        var value = read(global, name);
        Object.defineProperty(root, name, {
          value: value,
          writable: false,
          configurable: false,
          enumerable: true //desc.enumerable
        });
      }
    }
  });

  // the whiteTable should map from each path-accessible
  // primordial object to the permit that describes how it should be
  // cleaned. To ensure that each subsequent traverse obtains the
  // same values, these paths become paths of frozen data
  // properties.
  var whiteTable = WeakMap();
  function register(value, permit) {
    if (value !== Object(value)) { return; }
    var oldPermit = whiteTable.get(value);
    if (typeof permit !== 'object' && typeof oldPermit === 'object') {
      return;
    }
    whiteTable.set(value, permit);
    if (typeof permit === 'object') {
      Object.keys(permit).forEach(function(name) {
        if (permit[name] !== 'skip') {
          var sub = read(value, name);
          register(sub, permit[name]);
        }
      });
    }
  }
  register(root, whitelist);

  // We initialize the whiteTable only so that we can process "*" and
  // "skip" inheritance in the whitelist, by walking actual superclass
  // chains.
  function isPermitted(base, name) {
    var permit = whiteTable.get(base);
    if (permit && permit[name]) { return permit[name]; }
    while (true) {
      base = Object.getPrototypeOf(base);
      if (base === null) { return false; }
      permit = whiteTable.get(base);
      if (typeof permit === 'object' && name in permit) {
        var result = permit[name];
        if (result === '*' || result === 'skip') {
          return result;
        } else {
          return false;
        }
      }
    }
  }

  var cleaning = WeakMap();

  var skipped = [];
  var goodDeletions = [];
  var badDeletions = [];

  // Assumes all super objects are otherwise accessible and so will
  // be independently cleaned.
  function clean(value, n) {
    if (value !== Object(value)) { return; }
    if (cleaning.get(value)) { return; }
    cleaning.set(value, true);
    Object.getOwnPropertyNames(value).forEach(function(name) {
      var path = n + (n ? '.' : '') + name;
      var p = isPermitted(value, name);
      if (p) {
        if (p === 'skip') {
          skipped.push(path);
        } else {
          var sub = read(value, name);
          clean(sub, path);
        }
      } else {
        // Strict delete throws on failure, which we can't count on yet
        var success;
        try {
          success = delete value[name];
        } catch (x) {
          success = false;
        }
        if (success) {
          goodDeletions.push(path);
        } else {
          badDeletions.push(path);
        }
      }
    });
    if (value !== FREEZE_EARLY) {
      Object.freeze(value);
    }
  }
  if (FREEZE_EARLY) { Object.freeze(FREEZE_EARLY); }
  clean(root, '');
  // cajaVM.log('Skipped ' + skipped.join(' '));
  cajaVM.log('Deleted ' + goodDeletions.sort().join(' '));

  if (cantNeuter.length >= 1) {
    var complaint = cantNeuter.map(function(p) {
      var desc = Object.getPropertyDescriptor(p.base, p.name);
      if (!desc) {
        return '  Missing ' + p.name;
      }
      return p.name + '(' + p.err + '): ' +
        Object.getOwnPropertyNames(desc).map(function(attrName) {
          var v = desc[attrName];
          if (v === Object(v)) { v = 'a ' + typeof v; }
          return attrName + ': ' + v;
        }).join(', ');

    });
    cajaVM.log("Can't neuter:" + complaint.sort().join('\n'));
  }

  if (badDeletions.length >= 1) {
    cajaVM.log("Can't delete " + badDeletions.sort().join(' '));
  } else {
    // We succeeded. Enable safe Function, eval, and compile to work.
    dirty = false;
  }
}
