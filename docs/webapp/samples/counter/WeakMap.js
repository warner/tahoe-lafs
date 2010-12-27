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

/**
 * If this is an ES5 platform and the ES-Harmony {@code WeakMap} is
 * absent, install an approximate emulation.
 *
 * <p>See {@code WeakMap} for documentation of the garbage collection
 * properties of this emulation.
 *
 * <p>Will also install some other elements of ES5 as needed to bring
 * an almost ES5 platform (such as Firefox Minefield 4.0b5pre or
 * Chromium beta 6.0.490.0 (3135)) to be a more complete emulation of
 * ES5. Some elements of these emulations lose SES safety.
 */
(function(global) {
  var hop = Object.prototype.hasOwnProperty;
  var slice = Array.prototype.slice;
  var push = Array.prototype.push;
  var defProp = Object.defineProperty;
  var classProp = Object.prototype.toString;

  var real = {};
  Object.getOwnPropertyNames(Object).forEach(function(name) {
    real[name] = Object[name];
  });

  function defMissingProp(base, name, missingFunc) {
    if (!(name in base)) {
      defProp(base, name, {
        value: missingFunc,
        writable: true,
        enumerable: false,
        configurable: true
      });
      if (base === Object) {
        real[name] = missingFunc;
      }
    }
  }

  function eq(x, y) {
    if (x === y) {
      // 0 === -0, but they are not identical
      return x !== 0 || 1/x === 1/y;
    } else {
      // NaN !== NaN, but they are identical.
      // NaNs are the only non-reflexive value, i.e., if x !== x,
      // then x is a NaN.
      return x !== x && y !== y;
    }
  }

  /////////////// KLUDGE SWITCHES ///////////////

  /////////////////////////////////
  // The following are only the minimal kludges needed for the current
  // Mozilla Minefield (Firefox Beta) or Chromium Beta. At the time of
  // this writing, these are Mozilla 4.0b5pre and Chromium 6.0.490.0
  // (3135). As these move forward, kludges can be removed until we
  // simply rely on ES5.


  /**
   * Work around for https://bugzilla.mozilla.org/show_bug.cgi?id=591846
   * as applied to the RegExp constructor.
   */
  var UnsafeRegExp = RegExp;
  function FakeRegExp(pattern, flags) {
    switch (arguments.length) {
      case 0: {
        return UnsafeRegExp();
      }
      case 1: {
        return UnsafeRegExp(pattern);
      }
      default: {
        return UnsafeRegExp(pattern, flags);
      }
    }
  }
  FakeRegExp.prototype = UnsafeRegExp.prototype;
  FakeRegExp.prototype.constructor = FakeRegExp;
  global.RegExp = FakeRegExp;

  /**
   * Work around for http://code.google.com/p/google-caja/issues/detail?id=528
   */
  var unsafeRegExpExec = RegExp.prototype.exec;
  var unsafeRegExpTest = RegExp.prototype.test;
  RegExp.prototype.exec = function(specimen) {
    return unsafeRegExpExec.call(this, String(specimen));
  };
  RegExp.prototype.test = function(specimen) {
    return unsafeRegExpTest.call(this, String(specimen));
  };

  /**
   * Work around https://bugzilla.mozilla.org/show_bug.cgi?id=591838
   */
  function goodDefProp(base, name, desc) {
    if (base === global &&
        (name === 'NaN' || name === 'Infinity' || name === 'undefined')) {
      var oldDesc = real.getOwnPropertyDescriptor(base, name);
      if (oldDesc) {
        function test(attrName) {
          if (!attrName in desc) { return true; }
          return eq(oldDesc.attrName, desc.attrName);
        }
        if ('value' in desc && 'value' in oldDesc &&
            test('value') && test('writable') &&
            test('enumerable') && test('configurable')) {
          return;
        }
      }
    }
    defProp(base, name, desc);
  }
  real.defineProperty = goodDefProp;
  defProp(Object, 'defineProperty', { value: goodDefProp });


  defMissingProp(Object, 'freeze', function(obj) { return obj; });
  defMissingProp(Object, 'seal', function(obj) { return obj; });
  defMissingProp(Object, 'preventExtensions', function(obj) { return obj; });
  defMissingProp(Object, 'isFrozen', function(obj) { return false; });
  defMissingProp(Object, 'isSealed', function(obj) { return false; });
  defMissingProp(Object, 'isExtensible', function(obj) { return true; });
  defMissingProp(Function.prototype, 'bind', function(self, var_args) {
    var thisFunc = this;
    var leftArgs = slice.call(arguments, 1);
    function funcBound(var_args) {
      var args = leftArgs.concat(slice.call(arguments, 0));
      return thisFunc.apply(self, args);
    }
    delete funcBound.prototype;
    return funcBound;
  });

  //////////////// END KLUDGE SWITCHES ///////////

  //////////////// New ES-Harmony methods ///////////

  defMissingProp(Object, 'getPropertyDescriptor', function(obj, name) {
    while (obj !== null) {
      var result = real.getOwnPropertyDescriptor(obj, name);
      if (result) { return result; }
      obj = real.getPrototypeOf(obj);
    }
    return undefined;
  });

  defMissingProp(Object, 'getPropertyNames', function(obj) {
    var result = [];
    while (obj !== null) {
      push.apply(result, real.getOwnPropertyNames(obj));
      obj = real.getPrototypeOf(obj);
    }
    return result;
  });

  /**
   * Still strawman rather than official proposal.
   */
  defMissingProp(Object, 'eq', eq);

  //////////////// END New ES-Harmony methods ///////////


  if (typeof WeakMap === 'function') { return; }

  var NO_IDENT = 'noident:0';

  /**
   * Gets a value which is either NO_IDENT or uniquely identifies the
   * key object, for use in making maps keyed by this key object.
   *
   * Two keys that are {@code eq} MUST have the same {@code
   * identity}. Two keys that are not {@code eq} MUST either have
   * different identities, or one of their identities MUST be
   * {@code NO_IDENT}. An identity is either a string or a frozen
   * one-element array containing a mostly-unique string. The identity
   * of an object is always either NO_IDENT or such an array. The
   * identity of the array itself is used to resolve collisions on the
   * name in the array.
   *
   * When a map stores a key's identity rather than the key itself,
   * the map does not cause the key to be retained. See the emulated
   * {@code WeakMap} below for the resulting gc properties.
   *
   * <p>To identify objects with reasonable efficiency on ES5 by
   * itself (i.e., without any object-keyed collections), we need to
   * add a reasonably hidden property to such key objects when we
   * can. This raises two issues:
   * <ul>
   * <li>arranging to add this property to objects before we lose the
   *     chance, and
   * <li>reasonably hiding the existence of this new property from
   *     most JavaScript code.
   * </ul>
   * We do so by
   * <ul>
   * <li>Making the hidden property non-enumerable, so we need not
   *     worry about for-in loops or {@code Object.keys},
   * <li>monkey patching those standard methods that would
   *     prevent extensions, to add this hidden property first,
   * <li>monkey patching those methods that would reveal this
   *     hidden property, and
   * <li>monkey patching those methods that would overwrite this
   *     hidden property.
   * </ul>
   * Remaining non-transparencies which are not easily fixed
   * <ul>
   * <li>The property can still be overridden by assignment. This
   *     could be repaired by installing the property as an accessor
   *     and pre-installing it on {@code Object.prototype}. However,
   *     the benefit seems small compared to the cost. OTOH, since
   *     {@code identity}'s invariant can be destroyed by such
   *     assignment, this may lead to an exploitable vulnerability,
   *     which would justify the expense.
   * <li>The {@code delete}, {@code in}, and property access
   *     ({@code []}, and {@code .}) operations would each reveal the
   *     presence of the hidden property. The property access
   *     operations also reveal the randomness provided by
   *     {@code Math.random}. This not currently an issue but may
   *     become one if SES otherwise seeks to hide Math.random.
   * </ul>
   */
  function identity(key) {
    if (key === Object(key)) {
      if (hop.call(key, 'ident___')) { return key.ident___; }
      if (!real.isExtensible(key)) { return NO_IDENT; }
      var result = real.freeze(['hash:' + Math.random()]);
      defProp(key, 'ident___', {
        value: result,
        writable: false,
        enumerable: false,
        configurable: false
      });
      return result;
    }
    if (typeof key === 'string') { return 'str:' + key; }
    return 'lit:' + key;
  }

  /**
   * Monkey patch operations that would make their first argument
   * non-extensible.
   */
  function identifyFirst(base, name) {
    var oldFunc = base[name];
    defProp(base, name, {
      value: function(obj, var_args) {
        identity(obj);
        return oldFunc.apply(this, arguments);
      }
    });
  }
  identifyFirst(Object, 'freeze');
  identifyFirst(Object, 'seal');
  identifyFirst(Object, 'preventExtensions');
  identifyFirst(Object, 'defineProperty');
  identifyFirst(Object, 'defineProperties');

  defProp(Object, 'getOwnPropertyNames', {
    value: function(obj) {
      var result = real.getOwnPropertyNames(obj);
      var i = result.indexOf('ident___');
      if (i >= 0) { result.splice(i, 1); }
      return result;
    }
  });

  defProp(Object, 'getPropertyNames', {
    value: function(obj) {
      var result = real.getPropertyNames(obj);
      var i = result.indexOf('ident___');
      if (i >= 0) { result.splice(i, 1); }
      return result;
    }
  });

  defProp(Object, 'getOwnPropertyDescriptor', {
    value: function(obj, name) {
      if (name === 'ident___') { return undefined; }
      return real.getOwnPropertyDescriptor(obj, name);
    }
  });

  defProp(Object, 'getPropertyDescriptor', {
    value: function(obj, name) {
      if (name === 'ident___') { return undefined; }
      return real.getPropertyDescriptor(obj, name);
    }
  });

  defProp(Object, 'create', {
    value: function(parent, pdmap) {
      var result = real.create(parent);
      identity(result);
      if (pdmap) {
        real.defineProperties(result, pdmap);
      }
      return result;
    }
  });

  function constFunc(func) {
    Object.freeze(func.prototype);
    return Object.freeze(func);
  }

  /**
   * This {@code WeakMap} emulation is observably equivalent to the
   * ES-Harmony WeakMap, but with leakier garbage collection properties.
   *
   * <p>As with true WeakMaps, in this emulation, a key does not
   * retain maps indexed by that key and (crucially) a map does not
   * retain the keys it indexes. A key by itself also does not retain
   * the values associated with that key.
   *
   * <p>However, the values placed in an emulated WeakMap are retained
   * so long as that map is retained and those associations are not
   * overridden. For example, when used to support membranes, all
   * values exported from a given membrane will live for the lifetime
   * of the membrane. But when the membrane is revoked, all objects
   * encapsulated within that membrane will still be collected. This
   * is the best we can do without VM support.
   */
  defMissingProp(global, 'WeakMap', constFunc(function() {
    var identities = {};
    var values = {};
     return Object.freeze({
      get: constFunc(function(key) {
        var id = identity(key);
        var name;
        if (typeof id === 'string') {
          name = id;
          id = key;
        } else {
          name = id[0];
        }
        var ids = identities[name] || [];
        var i = ids.indexOf(id);
        return (i < 0) ? undefined : values[name][i];
      }),
      set: constFunc(function(key, value) {
        if (key !== Object(key)) {
          throw new TypeError('Key must not be a value type: ' + key);
        }
        var id = identity(key);
        var name;
        if (typeof id === 'string') {
          name = id;
          id = key;
        } else {
          name = id[0];
        }
        var ids = identities[name] || (identities[name] = []);
        var vals = values[name] || (values[name] = []);
        var i = ids.indexOf(id);
        if (i < 0) { i = ids.length; }
        ids[i] = id;
        vals[i] = value;
      })
    });
  }));

})(this);
