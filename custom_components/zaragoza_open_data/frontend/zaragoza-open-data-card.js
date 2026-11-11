// node_modules/@lit/reactive-element/css-tag.js
/**
* @license
* Copyright 2019 Google LLC
* SPDX-License-Identifier: BSD-3-Clause
*/
var e = globalThis, t = e.ShadowRoot && (e.ShadyCSS === void 0 || e.ShadyCSS.nativeShadow) && "adoptedStyleSheets" in Document.prototype && "replace" in CSSStyleSheet.prototype, n = Symbol(), r = /* @__PURE__ */ new WeakMap(), i = class {
	constructor(e, t, r) {
		if (this._$cssResult$ = !0, r !== n) throw Error("CSSResult is not constructable. Use `unsafeCSS` or `css` instead.");
		this.cssText = e, this.t = t;
	}
	get styleSheet() {
		let e = this.o, n = this.t;
		if (t && e === void 0) {
			let t = n !== void 0 && n.length === 1;
			t && (e = r.get(n)), e === void 0 && ((this.o = e = new CSSStyleSheet()).replaceSync(this.cssText), t && r.set(n, e));
		}
		return e;
	}
	toString() {
		return this.cssText;
	}
}, a = (e) => new i(typeof e == "string" ? e : e + "", void 0, n), o = (e, ...t) => new i(e.length === 1 ? e[0] : t.reduce((t, n, r) => t + ((e) => {
	if (!0 === e._$cssResult$) return e.cssText;
	if (typeof e == "number") return e;
	throw Error("Value passed to 'css' function must be a 'css' function result: " + e + ". Use 'unsafeCSS' to pass non-literal values, but take care to ensure page security.");
})(n) + e[r + 1], e[0]), e, n), s = (n, r) => {
	if (t) n.adoptedStyleSheets = r.map((e) => e instanceof CSSStyleSheet ? e : e.styleSheet);
	else for (let t of r) {
		let r = document.createElement("style"), i = e.litNonce;
		i !== void 0 && r.setAttribute("nonce", i), r.textContent = t.cssText, n.appendChild(r);
	}
}, c = t ? (e) => e : (e) => e instanceof CSSStyleSheet ? ((e) => {
	let t = "";
	for (let n of e.cssRules) t += n.cssText;
	return a(t);
})(e) : e, { is: l, defineProperty: u, getOwnPropertyDescriptor: d, getOwnPropertyNames: ee, getOwnPropertySymbols: te, getPrototypeOf: ne } = Object, f = globalThis, re = f.trustedTypes, ie = re ? re.emptyScript : "", ae = f.reactiveElementPolyfillSupport, p = (e, t) => e, m = {
	toAttribute(e, t) {
		/**
		* @license
		* Copyright 2017 Google LLC
		* SPDX-License-Identifier: BSD-3-Clause
		*/
		switch (t) {
			case Boolean:
				e = e ? ie : null;
				break;
			case Object:
			case Array: e = e == null ? e : JSON.stringify(e);
		}
		return e;
	},
	fromAttribute(e, t) {
		let n = e;
		switch (t) {
			case Boolean:
				n = e !== null;
				break;
			case Number:
				n = e === null ? null : Number(e);
				break;
			case Object:
			case Array: try {
				n = JSON.parse(e);
			} catch {
				n = null;
			}
		}
		return n;
	}
}, h = (e, t) => !l(e, t), oe = {
	attribute: !0,
	type: String,
	converter: m,
	reflect: !1,
	useDefault: !1,
	hasChanged: h
};
Symbol.metadata ??= Symbol("metadata"), f.litPropertyMetadata ??= /* @__PURE__ */ new WeakMap();
var g = class extends HTMLElement {
	static addInitializer(e) {
		this._$Ei(), (this.l ??= []).push(e);
	}
	static get observedAttributes() {
		return this.finalize(), this._$Eh && [...this._$Eh.keys()];
	}
	static createProperty(e, t = oe) {
		if (t.state && (t.attribute = !1), this._$Ei(), this.prototype.hasOwnProperty(e) && ((t = Object.create(t)).wrapped = !0), this.elementProperties.set(e, t), !t.noAccessor) {
			let n = Symbol(), r = this.getPropertyDescriptor(e, n, t);
			r !== void 0 && u(this.prototype, e, r);
		}
	}
	static getPropertyDescriptor(e, t, n) {
		let { get: r, set: i } = d(this.prototype, e) ?? {
			get() {
				return this[t];
			},
			set(e) {
				this[t] = e;
			}
		};
		return {
			get: r,
			set(t) {
				let a = r?.call(this);
				i?.call(this, t), this.requestUpdate(e, a, n);
			},
			configurable: !0,
			enumerable: !0
		};
	}
	static getPropertyOptions(e) {
		return this.elementProperties.get(e) ?? oe;
	}
	static _$Ei() {
		if (this.hasOwnProperty(p("elementProperties"))) return;
		let e = ne(this);
		e.finalize(), e.l !== void 0 && (this.l = [...e.l]), this.elementProperties = new Map(e.elementProperties);
	}
	static finalize() {
		if (this.hasOwnProperty(p("finalized"))) return;
		if (this.finalized = !0, this._$Ei(), this.hasOwnProperty(p("properties"))) {
			let e = this.properties, t = [...ee(e), ...te(e)];
			for (let n of t) this.createProperty(n, e[n]);
		}
		let e = this[Symbol.metadata];
		if (e !== null) {
			let t = litPropertyMetadata.get(e);
			if (t !== void 0) for (let [e, n] of t) this.elementProperties.set(e, n);
		}
		this._$Eh = /* @__PURE__ */ new Map();
		for (let [e, t] of this.elementProperties) {
			let n = this._$Eu(e, t);
			n !== void 0 && this._$Eh.set(n, e);
		}
		this.elementStyles = this.finalizeStyles(this.styles);
	}
	static finalizeStyles(e) {
		let t = [];
		if (Array.isArray(e)) {
			let n = new Set(e.flat(1 / 0).reverse());
			for (let e of n) t.unshift(c(e));
		} else e !== void 0 && t.push(c(e));
		return t;
	}
	static _$Eu(e, t) {
		let n = t.attribute;
		return !1 === n ? void 0 : typeof n == "string" ? n : typeof e == "string" ? e.toLowerCase() : void 0;
	}
	constructor() {
		super(), this._$Ep = void 0, this.isUpdatePending = !1, this.hasUpdated = !1, this._$Em = null, this._$Ev();
	}
	_$Ev() {
		this._$ES = new Promise((e) => this.enableUpdating = e), this._$AL = /* @__PURE__ */ new Map(), this._$E_(), this.requestUpdate(), this.constructor.l?.forEach((e) => e(this));
	}
	addController(e) {
		(this._$EO ??= /* @__PURE__ */ new Set()).add(e), this.renderRoot !== void 0 && this.isConnected && e.hostConnected?.();
	}
	removeController(e) {
		this._$EO?.delete(e);
	}
	_$E_() {
		let e = /* @__PURE__ */ new Map(), t = this.constructor.elementProperties;
		for (let n of t.keys()) this.hasOwnProperty(n) && (e.set(n, this[n]), delete this[n]);
		e.size > 0 && (this._$Ep = e);
	}
	createRenderRoot() {
		let e = this.shadowRoot ?? this.attachShadow(this.constructor.shadowRootOptions);
		return s(e, this.constructor.elementStyles), e;
	}
	connectedCallback() {
		this.renderRoot ??= this.createRenderRoot(), this.enableUpdating(!0), this._$EO?.forEach((e) => e.hostConnected?.());
	}
	enableUpdating(e) {}
	disconnectedCallback() {
		this._$EO?.forEach((e) => e.hostDisconnected?.());
	}
	attributeChangedCallback(e, t, n) {
		this._$AK(e, n);
	}
	_$ET(e, t) {
		let n = this.constructor.elementProperties.get(e), r = this.constructor._$Eu(e, n);
		if (r !== void 0 && !0 === n.reflect) {
			let i = (n.converter?.toAttribute === void 0 ? m : n.converter).toAttribute(t, n.type);
			this._$Em = e, i == null ? this.removeAttribute(r) : this.setAttribute(r, i), this._$Em = null;
		}
	}
	_$AK(e, t) {
		let n = this.constructor, r = n._$Eh.get(e);
		if (r !== void 0 && this._$Em !== r) {
			let e = n.getPropertyOptions(r), i = typeof e.converter == "function" ? { fromAttribute: e.converter } : e.converter?.fromAttribute === void 0 ? m : e.converter;
			this._$Em = r;
			let a = i.fromAttribute(t, e.type);
			this[r] = a ?? this._$Ej?.get(r) ?? a, this._$Em = null;
		}
	}
	requestUpdate(e, t, n, r = !1, i) {
		if (e !== void 0) {
			let a = this.constructor;
			if (!1 === r && (i = this[e]), n ??= a.getPropertyOptions(e), !((n.hasChanged ?? h)(i, t) || n.useDefault && n.reflect && i === this._$Ej?.get(e) && !this.hasAttribute(a._$Eu(e, n)))) return;
			this.C(e, t, n);
		}
		!1 === this.isUpdatePending && (this._$ES = this._$EP());
	}
	C(e, t, { useDefault: n, reflect: r, wrapped: i }, a) {
		n && !(this._$Ej ??= /* @__PURE__ */ new Map()).has(e) && (this._$Ej.set(e, a ?? t ?? this[e]), !0 !== i || a !== void 0) || (this._$AL.has(e) || (this.hasUpdated || n || (t = void 0), this._$AL.set(e, t)), !0 === r && this._$Em !== e && (this._$Eq ??= /* @__PURE__ */ new Set()).add(e));
	}
	async _$EP() {
		this.isUpdatePending = !0;
		try {
			await this._$ES;
		} catch (e) {
			Promise.reject(e);
		}
		let e = this.scheduleUpdate();
		return e != null && await e, !this.isUpdatePending;
	}
	scheduleUpdate() {
		return this.performUpdate();
	}
	performUpdate() {
		if (!this.isUpdatePending) return;
		if (!this.hasUpdated) {
			if (this.renderRoot ??= this.createRenderRoot(), this._$Ep) {
				for (let [e, t] of this._$Ep) this[e] = t;
				this._$Ep = void 0;
			}
			let e = this.constructor.elementProperties;
			if (e.size > 0) for (let [t, n] of e) {
				let { wrapped: e } = n, r = this[t];
				!0 !== e || this._$AL.has(t) || r === void 0 || this.C(t, void 0, n, r);
			}
		}
		let e = !1, t = this._$AL;
		try {
			e = this.shouldUpdate(t), e ? (this.willUpdate(t), this._$EO?.forEach((e) => e.hostUpdate?.()), this.update(t)) : this._$EM();
		} catch (t) {
			throw e = !1, this._$EM(), t;
		}
		e && this._$AE(t);
	}
	willUpdate(e) {}
	_$AE(e) {
		this._$EO?.forEach((e) => e.hostUpdated?.()), this.hasUpdated || (this.hasUpdated = !0, this.firstUpdated(e)), this.updated(e);
	}
	_$EM() {
		this._$AL = /* @__PURE__ */ new Map(), this.isUpdatePending = !1;
	}
	get updateComplete() {
		return this.getUpdateComplete();
	}
	getUpdateComplete() {
		return this._$ES;
	}
	shouldUpdate(e) {
		return !0;
	}
	update(e) {
		this._$Eq &&= this._$Eq.forEach((e) => this._$ET(e, this[e])), this._$EM();
	}
	updated(e) {}
	firstUpdated(e) {}
};
g.elementStyles = [], g.shadowRootOptions = { mode: "open" }, g[p("elementProperties")] = /* @__PURE__ */ new Map(), g[p("finalized")] = /* @__PURE__ */ new Map(), ae?.({ ReactiveElement: g }), (f.reactiveElementVersions ??= []).push("2.1.2");
// node_modules/lit-html/lit-html.js
/**
* @license
* Copyright 2017 Google LLC
* SPDX-License-Identifier: BSD-3-Clause
*/
var _ = globalThis, se = (e) => e, v = _.trustedTypes, ce = v ? v.createPolicy("lit-html", { createHTML: (e) => e }) : void 0, le = "$lit$", y = `lit$${Math.random().toFixed(9).slice(2)}$`, ue = "?" + y, de = `<${ue}>`, b = document, x = () => b.createComment(""), S = (e) => e === null || typeof e != "object" && typeof e != "function", C = Array.isArray, fe = (e) => C(e) || typeof e?.[Symbol.iterator] == "function", pe = "[ 	\n\f\r]", w = /<(?:(!--|\/[^a-zA-Z])|(\/?[a-zA-Z][^>\s]*)|(\/?$))/g, me = /-->/g, he = />/g, T = RegExp(`>|${pe}(?:([^\\s"'>=/]+)(${pe}*=${pe}*(?:[^ \t\n\f\r"'\`<>=]|("|')|))|$)`, "g"), ge = /'/g, _e = /"/g, ve = /^(?:script|style|textarea|title)$/i, E = ((e) => (t, ...n) => ({
	_$litType$: e,
	strings: t,
	values: n
}))(1), D = Symbol.for("lit-noChange"), O = Symbol.for("lit-nothing"), ye = /* @__PURE__ */ new WeakMap(), k = b.createTreeWalker(b, 129);
function be(e, t) {
	if (!C(e) || !e.hasOwnProperty("raw")) throw Error("invalid template strings array");
	return ce === void 0 ? t : ce.createHTML(t);
}
var xe = (e, t) => {
	let n = e.length - 1, r = [], i, a = t === 2 ? "<svg>" : t === 3 ? "<math>" : "", o = w;
	for (let t = 0; t < n; t++) {
		let n = e[t], s, c, l = -1, u = 0;
		for (; u < n.length && (o.lastIndex = u, c = o.exec(n), c !== null);) u = o.lastIndex, o === w ? c[1] === "!--" ? o = me : c[1] === void 0 ? c[2] === void 0 ? c[3] !== void 0 && (o = T) : (ve.test(c[2]) && (i = RegExp("</" + c[2], "g")), o = T) : o = he : o === T ? c[0] === ">" ? (o = i ?? w, l = -1) : c[1] === void 0 ? l = -2 : (l = o.lastIndex - c[2].length, s = c[1], o = c[3] === void 0 ? T : c[3] === "\"" ? _e : ge) : o === _e || o === ge ? o = T : o === me || o === he ? o = w : (o = T, i = void 0);
		let d = o === T && e[t + 1].startsWith("/>") ? " " : "";
		a += o === w ? n + de : l >= 0 ? (r.push(s), n.slice(0, l) + le + n.slice(l) + y + d) : n + y + (l === -2 ? t : d);
	}
	return [be(e, a + (e[n] || "<?>") + (t === 2 ? "</svg>" : t === 3 ? "</math>" : "")), r];
}, A = class e {
	constructor({ strings: t, _$litType$: n }, r) {
		let i;
		this.parts = [];
		let a = 0, o = 0, s = t.length - 1, c = this.parts, [l, u] = xe(t, n);
		if (this.el = e.createElement(l, r), k.currentNode = this.el.content, n === 2 || n === 3) {
			let e = this.el.content.firstChild;
			e.replaceWith(...e.childNodes);
		}
		for (; (i = k.nextNode()) !== null && c.length < s;) {
			if (i.nodeType === 1) {
				if (i.hasAttributes()) for (let e of i.getAttributeNames()) if (e.endsWith(le)) {
					let t = u[o++], n = i.getAttribute(e).split(y), r = /([.?@])?(.*)/.exec(t);
					c.push({
						type: 1,
						index: a,
						name: r[2],
						strings: n,
						ctor: r[1] === "." ? Ce : r[1] === "?" ? we : r[1] === "@" ? Te : N
					}), i.removeAttribute(e);
				} else e.startsWith(y) && (c.push({
					type: 6,
					index: a
				}), i.removeAttribute(e));
				if (ve.test(i.tagName)) {
					let e = i.textContent.split(y), t = e.length - 1;
					if (t > 0) {
						i.textContent = v ? v.emptyScript : "";
						for (let n = 0; n < t; n++) i.append(e[n], x()), k.nextNode(), c.push({
							type: 2,
							index: ++a
						});
						i.append(e[t], x());
					}
				}
			} else if (i.nodeType === 8) {
				if (i.data === ue) c.push({
					type: 2,
					index: a
				});
				else {
					let e = -1;
					for (; (e = i.data.indexOf(y, e + 1)) !== -1;) c.push({
						type: 7,
						index: a
					}), e += y.length - 1;
				}
			}
			a++;
		}
	}
	static createElement(e, t) {
		let n = b.createElement("template");
		return n.innerHTML = e, n;
	}
};
function j(e, t, n = e, r) {
	if (t === D) return t;
	let i = r === void 0 ? n._$Cl : n._$Co?.[r], a = S(t) ? void 0 : t._$litDirective$;
	return i?.constructor !== a && (i?._$AO?.(!1), a === void 0 ? i = void 0 : (i = new a(e), i._$AT(e, n, r)), r === void 0 ? n._$Cl = i : (n._$Co ??= [])[r] = i), i !== void 0 && (t = j(e, i._$AS(e, t.values), i, r)), t;
}
var Se = class {
	constructor(e, t) {
		this._$AV = [], this._$AN = void 0, this._$AD = e, this._$AM = t;
	}
	get parentNode() {
		return this._$AM.parentNode;
	}
	get _$AU() {
		return this._$AM._$AU;
	}
	u(e) {
		let { el: { content: t }, parts: n } = this._$AD, r = (e?.creationScope ?? b).importNode(t, !0);
		k.currentNode = r;
		let i = k.nextNode(), a = 0, o = 0, s = n[0];
		for (; s !== void 0;) {
			if (a === s.index) {
				let t;
				s.type === 2 ? t = new M(i, i.nextSibling, this, e) : s.type === 1 ? t = new s.ctor(i, s.name, s.strings, this, e) : s.type === 6 && (t = new Ee(i, this, e)), this._$AV.push(t), s = n[++o];
			}
			a !== s?.index && (i = k.nextNode(), a++);
		}
		return k.currentNode = b, r;
	}
	p(e) {
		let t = 0;
		for (let n of this._$AV) n !== void 0 && (n.strings === void 0 ? n._$AI(e[t]) : (n._$AI(e, n, t), t += n.strings.length - 2)), t++;
	}
}, M = class e {
	get _$AU() {
		return this._$AM?._$AU ?? this._$Cv;
	}
	constructor(e, t, n, r) {
		this.type = 2, this._$AH = O, this._$AN = void 0, this._$AA = e, this._$AB = t, this._$AM = n, this.options = r, this._$Cv = r?.isConnected ?? !0;
	}
	get parentNode() {
		let e = this._$AA.parentNode, t = this._$AM;
		return t !== void 0 && e?.nodeType === 11 && (e = t.parentNode), e;
	}
	get startNode() {
		return this._$AA;
	}
	get endNode() {
		return this._$AB;
	}
	_$AI(e, t = this) {
		e = j(this, e, t), S(e) ? e === O || e == null || e === "" ? (this._$AH !== O && this._$AR(), this._$AH = O) : e !== this._$AH && e !== D && this._(e) : e._$litType$ === void 0 ? e.nodeType === void 0 ? fe(e) ? this.k(e) : this._(e) : this.T(e) : this.$(e);
	}
	O(e) {
		return this._$AA.parentNode.insertBefore(e, this._$AB);
	}
	T(e) {
		this._$AH !== e && (this._$AR(), this._$AH = this.O(e));
	}
	_(e) {
		this._$AH !== O && S(this._$AH) ? this._$AA.nextSibling.data = e : this.T(b.createTextNode(e)), this._$AH = e;
	}
	$(e) {
		let { values: t, _$litType$: n } = e, r = typeof n == "number" ? this._$AC(e) : (n.el === void 0 && (n.el = A.createElement(be(n.h, n.h[0]), this.options)), n);
		if (this._$AH?._$AD === r) this._$AH.p(t);
		else {
			let e = new Se(r, this), n = e.u(this.options);
			e.p(t), this.T(n), this._$AH = e;
		}
	}
	_$AC(e) {
		let t = ye.get(e.strings);
		return t === void 0 && ye.set(e.strings, t = new A(e)), t;
	}
	k(t) {
		C(this._$AH) || (this._$AH = [], this._$AR());
		let n = this._$AH, r, i = 0;
		for (let a of t) i === n.length ? n.push(r = new e(this.O(x()), this.O(x()), this, this.options)) : r = n[i], r._$AI(a), i++;
		i < n.length && (this._$AR(r && r._$AB.nextSibling, i), n.length = i);
	}
	_$AR(e = this._$AA.nextSibling, t) {
		for (this._$AP?.(!1, !0, t); e !== this._$AB;) {
			let t = se(e).nextSibling;
			se(e).remove(), e = t;
		}
	}
	setConnected(e) {
		this._$AM === void 0 && (this._$Cv = e, this._$AP?.(e));
	}
}, N = class {
	get tagName() {
		return this.element.tagName;
	}
	get _$AU() {
		return this._$AM._$AU;
	}
	constructor(e, t, n, r, i) {
		this.type = 1, this._$AH = O, this._$AN = void 0, this.element = e, this.name = t, this._$AM = r, this.options = i, n.length > 2 || n[0] !== "" || n[1] !== "" ? (this._$AH = Array(n.length - 1).fill(/* @__PURE__ */ new String()), this.strings = n) : this._$AH = O;
	}
	_$AI(e, t = this, n, r) {
		let i = this.strings, a = !1;
		if (i === void 0) e = j(this, e, t, 0), a = !S(e) || e !== this._$AH && e !== D, a && (this._$AH = e);
		else {
			let r = e, o, s;
			for (e = i[0], o = 0; o < i.length - 1; o++) s = j(this, r[n + o], t, o), s === D && (s = this._$AH[o]), a ||= !S(s) || s !== this._$AH[o], s === O ? e = O : e !== O && (e += (s ?? "") + i[o + 1]), this._$AH[o] = s;
		}
		a && !r && this.j(e);
	}
	j(e) {
		e === O ? this.element.removeAttribute(this.name) : this.element.setAttribute(this.name, e ?? "");
	}
}, Ce = class extends N {
	constructor() {
		super(...arguments), this.type = 3;
	}
	j(e) {
		this.element[this.name] = e === O ? void 0 : e;
	}
}, we = class extends N {
	constructor() {
		super(...arguments), this.type = 4;
	}
	j(e) {
		this.element.toggleAttribute(this.name, !!e && e !== O);
	}
}, Te = class extends N {
	constructor(e, t, n, r, i) {
		super(e, t, n, r, i), this.type = 5;
	}
	_$AI(e, t = this) {
		if ((e = j(this, e, t, 0) ?? O) === D) return;
		let n = this._$AH, r = e === O && n !== O || e.capture !== n.capture || e.once !== n.once || e.passive !== n.passive, i = e !== O && (n === O || r);
		r && this.element.removeEventListener(this.name, this, n), i && this.element.addEventListener(this.name, this, e), this._$AH = e;
	}
	handleEvent(e) {
		typeof this._$AH == "function" ? this._$AH.call(this.options?.host ?? this.element, e) : this._$AH.handleEvent(e);
	}
}, Ee = class {
	constructor(e, t, n) {
		this.element = e, this.type = 6, this._$AN = void 0, this._$AM = t, this.options = n;
	}
	get _$AU() {
		return this._$AM._$AU;
	}
	_$AI(e) {
		j(this, e);
	}
}, De = _.litHtmlPolyfillSupport;
De?.(A, M), (_.litHtmlVersions ??= []).push("3.3.3");
var Oe = (e, t, n) => {
	let r = n?.renderBefore ?? t, i = r._$litPart$;
	if (i === void 0) {
		let e = n?.renderBefore ?? null;
		r._$litPart$ = i = new M(t.insertBefore(x(), e), e, void 0, n ?? {});
	}
	return i._$AI(e), i;
}, ke = globalThis, P = class extends g {
	constructor() {
		/**
		* @license
		* Copyright 2017 Google LLC
		* SPDX-License-Identifier: BSD-3-Clause
		*/
		super(...arguments), this.renderOptions = { host: this }, this._$Do = void 0;
	}
	createRenderRoot() {
		let e = super.createRenderRoot();
		return this.renderOptions.renderBefore ??= e.firstChild, e;
	}
	update(e) {
		let t = this.render();
		this.hasUpdated || (this.renderOptions.isConnected = this.isConnected), super.update(e), this._$Do = Oe(t, this.renderRoot, this.renderOptions);
	}
	connectedCallback() {
		super.connectedCallback(), this._$Do?.setConnected(!0);
	}
	disconnectedCallback() {
		super.disconnectedCallback(), this._$Do?.setConnected(!1);
	}
	render() {
		return D;
	}
};
P._$litElement$ = !0, P.finalized = !0, ke.litElementHydrateSupport?.({ LitElement: P });
var Ae = ke.litElementPolyfillSupport;
Ae?.({ LitElement: P }), (ke.litElementVersions ??= []).push("4.2.2");
// node_modules/@lit/reactive-element/decorators/property.js
/**
* @license
* Copyright 2017 Google LLC
* SPDX-License-Identifier: BSD-3-Clause
*/ var je = {
	attribute: !0,
	type: String,
	converter: m,
	reflect: !1,
	hasChanged: h
}, Me = (e = je, t, n) => {
	let { kind: r, metadata: i } = n, a = globalThis.litPropertyMetadata.get(i);
	if (a === void 0 && globalThis.litPropertyMetadata.set(i, a = /* @__PURE__ */ new Map()), r === "setter" && ((e = Object.create(e)).wrapped = !0), a.set(n.name, e), r === "accessor") {
		let { name: r } = n;
		return {
			set(n) {
				let i = t.get.call(this);
				t.set.call(this, n), this.requestUpdate(r, i, e, !0, n);
			},
			init(t) {
				return t !== void 0 && this.C(r, void 0, e, t), t;
			}
		};
	}
	if (r === "setter") {
		let { name: r } = n;
		return function(n) {
			let i = this[r];
			t.call(this, n), this.requestUpdate(r, i, e, !0, n);
		};
	}
	throw Error("Unsupported decorator location: " + r);
};
function Ne(e) {
	return (t, n) => typeof n == "object" ? Me(e, t, n) : ((e, t, n) => {
		let r = t.hasOwnProperty(n);
		return t.constructor.createProperty(n, e), r ? Object.getOwnPropertyDescriptor(t, n) : void 0;
	})(e, t, n);
}
// node_modules/@lit/reactive-element/decorators/state.js
/**
* @license
* Copyright 2017 Google LLC
* SPDX-License-Identifier: BSD-3-Clause
*/ function F(e) {
	return Ne({
		...e,
		state: !0,
		attribute: !1
	});
}
// src/guards.ts
function I(e) {
	return typeof e == "object" && !!e && !Array.isArray(e);
}
function L(e) {
	return typeof e == "string";
}
function R(e) {
	return typeof e == "number" && Number.isFinite(e);
}
// src/api.ts
var Pe = "zaragoza_open_data", Fe = class extends Error {
	constructor(e) {
		super(e.message), this.name = "ActionError", this.code = e.code, this.translationKey = e.translation_key ?? void 0, this.translationDomain = e.translation_domain ?? void 0, this.translationPlaceholders = e.translation_placeholders ?? {};
	}
}, Ie = class extends Error {
	constructor(e) {
		super(`Unexpected response from ${Pe}.${e}`), this.service = e, this.name = "UnexpectedResponseError";
	}
};
async function Le(e, t) {
	let n = { kind: t.kind };
	return t.query !== void 0 && (n.query = t.query), t.latitude !== void 0 && (n.latitude = t.latitude, n.longitude = t.longitude), t.limit !== void 0 && (n.limit = t.limit), (await z(e, "find_stops", n, He)).stops;
}
function Re(e, t, n) {
	return z(e, "get_arrivals", {
		mode: t,
		stop: n
	}, We);
}
function ze(e, t) {
	return z(e, "get_bizi_station", { station: t }, Ke);
}
async function z(e, t, n, r) {
	let i;
	try {
		i = await e.connection.sendMessagePromise({
			type: "call_service",
			domain: Pe,
			service: t,
			service_data: n,
			return_response: !0
		});
	} catch (e) {
		throw Be(e) ? new Fe(e) : e;
	}
	let a = I(i) ? i.response : void 0;
	if (!r(a)) throw new Ie(t);
	return a;
}
function Be(e) {
	return I(e) && L(e.code) && L(e.message) && U(e.translation_key, L) && U(e.translation_domain, L) && U(e.translation_placeholders, Ve);
}
function Ve(e) {
	return I(e) && Object.values(e).every(L);
}
function He(e) {
	return I(e) && W(e.stops, Ue);
}
function Ue(e) {
	return I(e) && L(e.code) && L(e.name) && H(e.direction, L) && W(e.lines, L) && B(e.distance_m) && R(e.latitude) && R(e.longitude);
}
function We(e) {
	if (!I(e)) return !1;
	let t = e.stop;
	return I(t) && L(t.code) && L(t.name) && H(t.direction, L) && W(e.arrivals, Ge) && L(e.source) && V(e.updated);
}
function Ge(e) {
	return I(e) && L(e.line) && L(e.destination) && B(e.minutes) && V(e.time);
}
function Ke(e) {
	if (!I(e)) return !1;
	let t = e.station;
	return I(t) && L(t.code) && L(t.name) && B(e.bikes) && H(e.electric, B) && H(e.mechanical, B) && B(e.docks) && qe(e.renting) && qe(e.returning) && L(e.source) && V(e.updated);
}
function B(e) {
	return Number.isInteger(e);
}
function qe(e) {
	return typeof e == "boolean";
}
function V(e) {
	return L(e) && !Number.isNaN(Date.parse(e));
}
function H(e, t) {
	return e === null || t(e);
}
function U(e, t) {
	return e == null || t(e);
}
function W(e, t) {
	return Array.isArray(e) && e.every(t);
}
// src/config.ts
var G = [
	"tram",
	"bus",
	"bizi"
], K = {
	min: 1,
	max: 10,
	default: 5
}, Je = "zone.home";
function q(e) {
	return G.some((t) => t === e);
}
function J(e) {
	let t = Ye(e.modes), n = Y(e, "default_mode", q, "one of tram, bus, bizi"), r = Y(e, "nearest", R, "a number"), i = Y(e, "home_zone", L, "an entity id, such as zone.home"), a = Y(e, "show_zones", Xe, "true or false"), o = Y(e, "my_location_entity", L, "an entity id, such as person.ana");
	return {
		modes: t,
		defaultMode: n !== void 0 && t.includes(n) ? n : t[0],
		nearest: Math.min(Math.max(Math.round(r ?? K.default), K.min), K.max),
		homeZone: i ?? Je,
		showZones: a ?? !0,
		myLocationEntity: o === "" ? void 0 : o
	};
}
function Ye(e) {
	if (e === void 0) return G;
	let t = Array.isArray(e) ? e.filter(q) : [];
	if (!Array.isArray(e) || t.length !== e.length) throw Error("modes must be a list of tram, bus and bizi");
	let [n, ...r] = [...new Set(t)];
	if (n === void 0) throw Error("modes must list at least one of tram, bus and bizi");
	return [n, ...r];
}
function Y(e, t, n, r) {
	let i = e[t];
	if (i === void 0 || n(i)) return i;
	throw Error(`${t} must be ${r}`);
}
function Xe(e) {
	return typeof e == "boolean";
}
// src/translations/en.json
var X = {
	"card.name": "Zaragoza Open Data",
	"card.description": "Find any tram or bus stop or Bizi station and see what comes next.",
	"mode.tram": "Tram",
	"mode.bus": "Bus",
	"mode.bizi": "Bizi",
	"origin.me": "My location",
	"origin.home": "Home",
	"origin.zone": "Zone",
	"origin.text": "Type a stop…",
	"search.placeholder": "Stop name or number",
	"list.loading": "Searching…",
	"list.empty": "No stop found",
	"location.unknown": "Home Assistant doesn't know where that is right now",
	"stop.distance": "{distance} m away",
	"stop.direction": "towards {direction}",
	"board.loading": "Loading…",
	"arrivals.minutes": "{minutes} min",
	"arrivals.none": "Nothing coming right now",
	"bizi.electric": "Electric",
	"bizi.mechanical": "Mechanical",
	"bizi.bikes": "Bikes",
	"bizi.docks": "Free docks",
	"bizi.not_renting": "Not lending bikes right now",
	"bizi.not_returning": "Not taking bikes back right now",
	"action.retry": "Retry",
	"error.generic": "Something went wrong talking to Home Assistant: try again",
	"error.unexpected_response": "Home Assistant sent an answer this card can't read: update the integration and reload the page",
	"error.tram_unavailable": "The city's tram arrivals can't be reached",
	"error.bus_unavailable": "No bus stop has arrivals from the last 10 minutes: neither the operator nor the city answers",
	"error.bizi_unavailable": "Neither the Bizi operator nor the city's Bizi list can be reached",
	"error.road_works_unavailable": "The city's road works lists can't be reached",
	"error.pharmacies_unavailable": "The city's list of pharmacies on duty can't be reached",
	"error.air_quality_unavailable": "The city's air quality readings can't be reached",
	"error.pollen_unavailable": "The city's pollen levels can't be reached",
	"error.unknown_stop": "No stop or station has the code {code}",
	"error.kind_disabled": "That kind of stop is switched off in the integration's options",
	"error.source_unavailable": "The source of this data can't be reached right now",
	"error.station_without_counts": "The source answering now has no bike or dock counts for station {code}",
	"error.not_loaded": "Zaragoza Open Data isn't running: reload it and try again",
	"editor.modes": "Modes",
	"editor.default_mode": "Mode shown first",
	"editor.nearest": "Nearest stops listed",
	"editor.home_zone": "Home zone",
	"editor.show_zones": "Show zones",
	"editor.my_location_entity": "Person for “My location” (by default, whoever is looking)",
	"footer.zaragoza_city": "Data source: Ayuntamiento de Zaragoza",
	"footer.avanza": "Data source: Avanza Zaragoza",
	"footer.gbfs": "Data source: Bizi Zaragoza"
}, Ze = {
	"card.name": "Zaragoza Open Data",
	"card.description": "Busca cualquier parada de tranvía o autobús o estación Bizi y mira qué llega.",
	"mode.tram": "Tranvía",
	"mode.bus": "Bus",
	"mode.bizi": "Bizi",
	"origin.me": "Mi ubicación",
	"origin.home": "Casa",
	"origin.zone": "Zona",
	"origin.text": "Escribir parada…",
	"search.placeholder": "Nombre o número de la parada",
	"list.loading": "Buscando…",
	"list.empty": "No se ha encontrado ninguna parada",
	"location.unknown": "Home Assistant no sabe ahora dónde está",
	"stop.distance": "a {distance} m",
	"stop.direction": "hacia {direction}",
	"board.loading": "Cargando…",
	"arrivals.minutes": "{minutes} min",
	"arrivals.none": "Ahora no hay llegadas",
	"bizi.electric": "Eléctricas",
	"bizi.mechanical": "Mecánicas",
	"bizi.bikes": "Bicis",
	"bizi.docks": "Anclajes libres",
	"bizi.not_renting": "Ahora no presta bicis",
	"bizi.not_returning": "Ahora no admite devoluciones",
	"action.retry": "Reintentar",
	"error.generic": "Algo ha fallado al hablar con Home Assistant: vuelve a intentarlo",
	"error.unexpected_response": "Home Assistant ha enviado una respuesta que esta tarjeta no entiende: actualiza la integración y recarga la página",
	"error.tram_unavailable": "No se pueden obtener las llegadas del tranvía del Ayuntamiento",
	"error.bus_unavailable": "Ninguna parada de autobús tiene llegadas de los últimos 10 minutos: no responden ni el operador ni el Ayuntamiento",
	"error.bizi_unavailable": "No responden ni el operador de Bizi ni la lista de Bizi del Ayuntamiento",
	"error.road_works_unavailable": "No se pueden obtener las obras y cortes del Ayuntamiento",
	"error.pharmacies_unavailable": "No se puede obtener la lista de farmacias de guardia del Ayuntamiento",
	"error.air_quality_unavailable": "No se pueden obtener las mediciones de calidad del aire del Ayuntamiento",
	"error.pollen_unavailable": "No se pueden obtener los niveles de polen del Ayuntamiento",
	"error.unknown_stop": "Ninguna parada ni estación tiene el código {code}",
	"error.kind_disabled": "Ese tipo de parada está desactivado en las opciones de la integración",
	"error.source_unavailable": "La fuente de estos datos no responde ahora mismo",
	"error.station_without_counts": "La fuente que responde ahora no da bicis ni anclajes de la estación {code}",
	"error.not_loaded": "Zaragoza Open Data no está en marcha: recárgala y vuelve a intentarlo",
	"editor.modes": "Modos",
	"editor.default_mode": "Modo al abrir",
	"editor.nearest": "Paradas cercanas que se listan",
	"editor.home_zone": "Zona de casa",
	"editor.show_zones": "Mostrar zonas",
	"editor.my_location_entity": "Persona de «Mi ubicación» (por defecto, quien mira)",
	"footer.zaragoza_city": "Origen de los datos: Ayuntamiento de Zaragoza",
	"footer.avanza": "Origen de los datos: Avanza Zaragoza",
	"footer.gbfs": "Origen de los datos: Bizi Zaragoza"
};
function Qe(e) {
	return Object.hasOwn(X, e);
}
function Z(e, t, n = {}) {
	return (e.locale.language.startsWith("es") ? Ze[t] : X[t]).replace(/\{(\w+)\}/g, (e, t) => Object.hasOwn(n, t) ? String(n[t]) : e);
}
// \0@oxc-project+runtime@0.156.0/helpers/esm/decorate.js
function Q(e, t, n, r) {
	var i = arguments.length, a = i < 3 ? t : r === null ? r = Object.getOwnPropertyDescriptor(t, n) : r, o;
	if (typeof Reflect == "object" && typeof Reflect.decorate == "function") a = Reflect.decorate(e, t, n, r);
	else for (var s = e.length - 1; s >= 0; s--) (o = e[s]) && (a = (i < 3 ? o(a) : i > 3 ? o(t, n, a) : o(t, n)) || a);
	return i > 3 && a && Object.defineProperty(t, n, a), a;
}
// src/editor.ts
var $e = "zaragoza-open-data-card-editor", et = {
	modes: "editor.modes",
	default_mode: "editor.default_mode",
	nearest: "editor.nearest",
	home_zone: "editor.home_zone",
	show_zones: "editor.show_zones",
	my_location_entity: "editor.my_location_entity"
}, tt = {
	tram: "mode.tram",
	bus: "mode.bus",
	bizi: "mode.bizi"
}, nt = class extends P {
	constructor(...e) {
		super(...e), this.computeLabel = (e) => this.hass === void 0 ? e.name : Z(this.hass, et[e.name]), this.onValueChanged = (e) => {
			let t = e instanceof CustomEvent ? e.detail : void 0, n = I(t) ? t.value : void 0;
			if (this.config === void 0 || !I(n)) return;
			let r = at(this.config, n);
			this.config = r, this.dispatchEvent(new CustomEvent("config-changed", {
				detail: { config: r },
				bubbles: !0,
				composed: !0
			}));
		};
	}
	setConfig(e) {
		J(e), this.config = e;
	}
	render() {
		if (this.hass === void 0 || this.config === void 0) return O;
		let e = J(this.config);
		return E`<ha-form
      .hass=${this.hass}
      .data=${rt(e)}
      .schema=${it(this.hass, e)}
      .computeLabel=${this.computeLabel}
      @value-changed=${this.onValueChanged}
    ></ha-form>`;
	}
};
Q([Ne({ attribute: !1 })], nt.prototype, "hass", void 0), Q([F()], nt.prototype, "config", void 0);
function rt(e) {
	return {
		modes: [...e.modes],
		default_mode: e.defaultMode,
		nearest: e.nearest,
		home_zone: e.homeZone,
		show_zones: e.showZones,
		...e.myLocationEntity === void 0 ? {} : { my_location_entity: e.myLocationEntity }
	};
}
function it(e, t) {
	let n = (t) => ({
		value: t,
		label: Z(e, tt[t])
	});
	return [
		{
			name: "modes",
			required: !0,
			selector: { select: {
				multiple: !0,
				mode: "list",
				options: G.map(n)
			} }
		},
		{
			name: "default_mode",
			selector: { select: {
				mode: "dropdown",
				options: t.modes.map(n)
			} }
		},
		{
			name: "nearest",
			selector: { number: {
				min: K.min,
				max: K.max,
				mode: "slider"
			} }
		},
		{
			name: "home_zone",
			selector: { entity: { filter: { domain: "zone" } } }
		},
		{
			name: "show_zones",
			selector: { boolean: {} }
		},
		{
			name: "my_location_entity",
			selector: { entity: { filter: { domain: "person" } } }
		}
	];
}
function at(e, t) {
	let n = J(e), r = Array.isArray(t.modes) ? t.modes.filter(q) : [], i = r.length > 0 ? r : [...n.modes], a = t.nearest, o = t.home_zone, s = t.show_zones, c = {
		...e,
		modes: i,
		nearest: R(a) ? a : n.nearest,
		home_zone: L(o) && o !== "" ? o : n.homeZone,
		show_zones: typeof s == "boolean" ? s : n.showZones
	}, l = t.default_mode;
	q(l) && i.includes(l) ? c.default_mode = l : delete c.default_mode;
	let u = t.my_location_entity;
	return L(u) && u !== "" ? c.my_location_entity = u : delete c.my_location_entity, c;
}
customElements.get("zaragoza-open-data-card-editor") === void 0 && customElements.define($e, nt);
// src/format.ts
function ot(e, t) {
	let n = e.locale.time_zone === "server" ? { timeZone: e.config.time_zone } : {};
	return new Intl.DateTimeFormat(e.locale.language, {
		hour: "2-digit",
		minute: "2-digit",
		hourCycle: "h23",
		...n
	}).format(new Date(t));
}
function st(e, t) {
	if (t instanceof Ie) return Z(e, "error.unexpected_response");
	if (t instanceof Fe && t.translationDomain === "zaragoza_open_data") {
		let n = `error.${t.translationKey ?? ""}`;
		if (Qe(n)) return Z(e, n, t.translationPlaceholders);
	}
	return Z(e, "error.generic");
}
// src/memory.ts
var ct = "zaragoza-open-data-card.last-stops", lt = 1;
function ut(e) {
	return ft()[e];
}
function dt(e, t) {
	let n = {
		...ft(),
		[e]: {
			code: t.code,
			name: t.name
		}
	};
	try {
		localStorage.setItem(ct, JSON.stringify({
			version: lt,
			stops: n
		}));
	} catch {}
}
function ft() {
	let e;
	try {
		let t = localStorage.getItem(ct);
		e = t === null ? void 0 : JSON.parse(t);
	} catch {
		return {};
	}
	if (!I(e) || e.version !== lt) return {};
	let t = e.stops, n = {};
	if (!I(t)) return n;
	for (let e of G) {
		let r = t[e];
		I(r) && L(r.code) && L(r.name) && (n[e] = {
			code: r.code,
			name: r.name
		});
	}
	return n;
}
// src/places.ts
function pt(e) {
	if (e === void 0) return;
	let t = e.attributes.latitude, n = e.attributes.longitude;
	return R(t) && R(n) ? {
		latitude: t,
		longitude: n
	} : void 0;
}
function mt(e, t) {
	if (t !== void 0) return e.states[t];
	let n = e.user?.id;
	if (n !== void 0) return Object.values(e.states).find((e) => e.entity_id.startsWith("person.") && e.attributes.user_id === n);
}
function ht(e, t) {
	let n = [];
	for (let r of Object.values(e.states)) {
		if (!r.entity_id.startsWith("zone.") || r.entity_id === t) continue;
		let e = pt(r), i = r.attributes.friendly_name;
		e !== void 0 && n.push({
			entityId: r.entity_id,
			name: L(i) ? i : r.entity_id,
			point: e
		});
	}
	return n.sort((t, n) => t.name.localeCompare(n.name, e.locale.language));
}
// src/refresh.ts
var gt = 6e4, _t = 2e3;
function vt(e, t) {
	let n = e === void 0 ? NaN : Date.parse(e);
	return Number.isNaN(n) ? gt : n + (Math.floor((t - n) / gt) + 1) * gt + _t - t;
}
var yt = class {
	constructor(e, t) {
		this.refresh = t, this.connected = !1, this.onVisibilityChange = () => {
			bt() ? this.refresh() : this.stop();
		}, e.addController(this);
	}
	hostConnected() {
		this.connected = !0, document.addEventListener("visibilitychange", this.onVisibilityChange), bt() && this.refresh();
	}
	hostDisconnected() {
		this.connected = !1, document.removeEventListener("visibilitychange", this.onVisibilityChange), this.stop();
	}
	succeeded(e) {
		this.start(e);
	}
	failed() {
		this.stop();
	}
	start(e) {
		this.stop(), this.connected && bt() && (this.timer = setTimeout(() => {
			this.timer = void 0, this.refresh();
		}, e));
	}
	stop() {
		clearTimeout(this.timer), this.timer = void 0;
	}
};
function bt() {
	return document.visibilityState === "visible";
}
// src/styles.ts
var xt = o`
  :host {
    display: block;
  }

  .content {
    display: flex;
    flex-direction: column;
    gap: 12px;
    padding: 16px;
  }

  .chips {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
  }

  button {
    font: inherit;
    color: inherit;
    cursor: pointer;
  }

  button:focus-visible,
  input:focus-visible,
  select:focus-visible {
    outline: 2px solid var(--primary-color);
    outline-offset: 2px;
  }

  .chip {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    height: 32px;
    padding: 0 12px;
    border: 1px solid var(--divider-color);
    border-radius: 16px;
    background: none;
    color: var(--primary-text-color);
    font-size: var(--ha-font-size-s, 14px);
  }

  .chip ha-icon {
    --mdc-icon-size: 18px;
  }

  .chip[aria-pressed="true"] {
    border-color: var(--primary-color);
    background: rgba(var(--rgb-primary-color), 0.12);
    color: var(--primary-color);
  }

  .field {
    box-sizing: border-box;
    width: 100%;
    height: 40px;
    padding: 0 12px;
    border: 1px solid var(--divider-color);
    border-radius: 8px;
    background: var(--secondary-background-color);
    color: var(--primary-text-color);
    font: inherit;
  }

  ul {
    margin: 0;
    padding: 0;
    list-style: none;
  }

  .stop {
    display: grid;
    grid-template-columns: 1fr auto;
    align-items: center;
    gap: 2px 12px;
    width: 100%;
    padding: 8px 0;
    border: none;
    border-bottom: 1px solid var(--divider-color);
    background: none;
    text-align: start;
  }

  .stop .name {
    color: var(--primary-text-color);
  }

  .stop .detail {
    grid-row: 2;
    color: var(--secondary-text-color);
    font-size: var(--ha-font-size-s, 14px);
  }

  .stop .distance {
    grid-row: 1 / span 2;
    grid-column: 2;
    color: var(--secondary-text-color);
    font-size: var(--ha-font-size-s, 14px);
  }

  .lines {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
  }

  .pill {
    display: inline-block;
    min-width: 2.2em;
    padding: 2px 6px;
    border-radius: 4px;
    background: var(--primary-color);
    color: var(--text-primary-color);
    font-weight: 500;
    text-align: center;
  }

  .stop .pill {
    font-size: var(--ha-font-size-xs, 12px);
  }

  .board {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .board-title {
    display: flex;
    align-items: center;
    gap: 12px;
  }

  .board-title ha-icon {
    color: var(--state-icon-color, var(--primary-color));
  }

  .board-name {
    color: var(--primary-text-color);
    font-size: var(--ha-font-size-l, 18px);
    font-weight: 500;
  }

  .board-direction {
    color: var(--secondary-text-color);
  }

  .arrivals li {
    display: grid;
    grid-template-columns: auto 1fr auto auto;
    align-items: center;
    gap: 12px;
    padding: 6px 0;
    border-bottom: 1px solid var(--divider-color);
  }

  .destination {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .minutes {
    font-weight: 500;
  }

  .time {
    color: var(--secondary-text-color);
    font-variant-numeric: tabular-nums;
  }

  .bikes {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(88px, 1fr));
    gap: 8px;
  }

  .bikes li {
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 8px;
    border-radius: 8px;
    background: var(--secondary-background-color);
    text-align: center;
  }

  .count {
    color: var(--primary-text-color);
    font-size: var(--ha-font-size-2xl, 24px);
    font-weight: 500;
  }

  .what,
  .note {
    color: var(--secondary-text-color);
  }

  .note {
    margin: 0;
  }

  .error {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    color: var(--error-color);
  }

  .retry {
    flex: none;
    padding: 6px 12px;
    border: 1px solid var(--primary-color);
    border-radius: 16px;
    background: none;
    color: var(--primary-color);
  }

  .footer {
    padding: 8px 16px;
    border-top: 1px solid var(--divider-color);
    color: var(--secondary-text-color);
    font-size: var(--ha-font-size-xs, 12px);
  }
`, St = "zaragoza-open-data-card", Ct = 500, wt = 2, Tt = 8, Et = {
	tram: {
		label: "mode.tram",
		icon: "mdi:tram"
	},
	bus: {
		label: "mode.bus",
		icon: "mdi:bus"
	},
	bizi: {
		label: "mode.bizi",
		icon: "mdi:bicycle"
	}
}, Dt = {
	me: {
		label: "origin.me",
		icon: "mdi:crosshairs-gps"
	},
	home: {
		label: "origin.home",
		icon: "mdi:home"
	},
	zone: {
		label: "origin.zone",
		icon: "mdi:map-marker-radius"
	},
	text: {
		label: "origin.text",
		icon: "mdi:magnify"
	}
}, $ = class extends P {
	constructor(...e) {
		super(...e), this.query = "", this.searchCall = 0, this.stopCall = 0, this.focusQuery = !1, this.refresh = new yt(this, () => {
			this.fetchOpened();
		}), this.onZoneChange = (e) => {
			let t = e.currentTarget;
			t instanceof HTMLSelectElement && (this.zone = t.value, this.searchAgain());
		}, this.onQueryInput = (e) => {
			let t = e.currentTarget;
			t instanceof HTMLInputElement && (this.query = t.value, clearTimeout(this.typing), this.query.trim().length < wt ? this.clearList() : this.typing = setTimeout(() => {
				this.searchAgain();
			}, Ct));
		};
	}
	static {
		this.styles = xt;
	}
	static getConfigElement() {
		return document.createElement($e);
	}
	static getStubConfig() {
		return { modes: [...G] };
	}
	setConfig(e) {
		this.settings = J(e);
	}
	getCardSize() {
		return 4;
	}
	disconnectedCallback() {
		super.disconnectedCallback(), clearTimeout(this.typing);
	}
	willUpdate() {
		this.hass !== void 0 && this.settings !== void 0 && (this.mode !== void 0 && this.settings.modes.includes(this.mode) || (this.mode = this.settings.defaultMode, this.clearList(), this.reopen(this.mode)));
	}
	updated() {
		this.focusQuery && (this.focusQuery = !1, this.renderRoot.querySelector("input")?.focus());
	}
	render() {
		let { hass: e, settings: t, mode: n } = this;
		if (e === void 0 || t === void 0 || n === void 0) return O;
		let r = t.showZones ? ht(e, t.homeZone) : [], i = [
			...mt(e, t.myLocationEntity) === void 0 ? [] : ["me"],
			...e.states[t.homeZone] === void 0 ? [] : ["home"],
			...r.length === 0 ? [] : ["zone"],
			"text"
		];
		return E`<ha-card>
      <div class="content">
        <div class="chips">
          ${t.modes.map((t) => kt(e, Et[t], t === n, () => {
			this.chooseMode(t);
		}))}
        </div>
        <div class="chips">
          ${i.map((t) => kt(e, Dt[t], t === this.origin, () => {
			this.chooseOrigin(t);
		}))}
        </div>
        ${this.origin === "zone" ? this.renderZones(e, r) : O}
        ${this.origin === "text" ? this.renderQuery(e) : O} ${this.renderList(e, n)}
        ${this.renderBoard(e)}
      </div>
      <div class="footer">${Z(e, Ot(this.board))}</div>
    </ha-card>`;
	}
	renderZones(e, t) {
		return E`<select class="field" aria-label=${Z(e, "origin.zone")} @change=${this.onZoneChange}>
      ${t.map((e) => E`<option value=${e.entityId} ?selected=${e.entityId === this.zone}>${e.name}</option>`)}
    </select>`;
	}
	renderQuery(e) {
		let t = Z(e, "search.placeholder");
		return E`<input
      class="field"
      type="search"
      autocomplete="off"
      enterkeyhint="search"
      .value=${this.query}
      placeholder=${t}
      aria-label=${t}
      @input=${this.onQueryInput}
    />`;
	}
	renderList(e, t) {
		let n = this.list;
		switch (n?.status) {
			case void 0: return O;
			case "loading": return E`<p class="note">${Z(e, "list.loading")}</p>`;
			case "nowhere": return E`<p class="note">${Z(e, "location.unknown")}</p>`;
			case "failed": return jt(e, n.error, () => {
				this.search(n.query);
			});
			case "ready": return n.stops.length === 0 ? E`<p class="note">${Z(e, "list.empty")}</p>` : E`<ul>
          ${n.stops.map((n) => E`<li>
                ${At(e, n, () => {
				this.open({
					kind: t,
					code: n.code,
					name: n.name,
					direction: n.direction
				});
			})}
              </li>`)}
        </ul>`;
		}
	}
	renderBoard(e) {
		let { opened: t, board: n } = this;
		if (t === void 0 || n === void 0) return O;
		let r = n.status === "arrivals" ? n.response.stop : n.status === "bizi" ? {
			name: n.response.station.name,
			direction: null
		} : t;
		return E`<section class="board">
      <div class="board-title">
        <ha-icon .icon=${Et[t.kind].icon}></ha-icon>
        <div>
          <div class="board-name">${r.name}</div>
          ${r.direction === null ? O : E`<div class="board-direction">
                ${Z(e, "stop.direction", { direction: r.direction })}
              </div>`}
        </div>
      </div>
      ${this.renderBoardBody(e, n)}
    </section>`;
	}
	renderBoardBody(e, t) {
		switch (t.status) {
			case "loading": return E`<p class="note">${Z(e, "board.loading")}</p>`;
			case "failed": return jt(e, t.error, () => {
				this.fetchOpened();
			});
			case "arrivals": return Mt(e, t.response);
			case "bizi": return Nt(e, t.response);
		}
	}
	chooseMode(e) {
		e !== this.mode && (this.mode = e, this.searchAgain(), this.reopen(e));
	}
	chooseOrigin(e) {
		if (this.origin = e, this.focusQuery = e === "text", e === "zone") {
			let e = this.zones();
			e.some((e) => e.entityId === this.zone) || (this.zone = e[0]?.entityId);
		}
		this.searchAgain();
	}
	searchAgain() {
		let { settings: e, mode: t, origin: n } = this;
		if (clearTimeout(this.typing), e === void 0 || t === void 0 || n === void 0) return;
		if (n === "text") {
			let e = this.query.trim();
			e.length < wt ? this.clearList() : this.search({
				kind: t,
				query: e,
				limit: Tt
			});
			return;
		}
		let r = this.originPoint(n);
		r === void 0 ? (this.clearList(), this.list = { status: "nowhere" }) : this.search({
			kind: t,
			...r,
			limit: e.nearest
		});
	}
	originPoint(e) {
		let { hass: t, settings: n } = this;
		if (t !== void 0 && n !== void 0) switch (e) {
			case "me": return pt(mt(t, n.myLocationEntity));
			case "home": return pt(t.states[n.homeZone]);
			case "zone": return this.zones().find((e) => e.entityId === this.zone)?.point;
		}
	}
	zones() {
		let { hass: e, settings: t } = this;
		return e === void 0 || t === void 0 ? [] : ht(e, t.homeZone);
	}
	async search(e) {
		let t = this.hass;
		if (t === void 0) return;
		let n = ++this.searchCall;
		this.list = { status: "loading" };
		try {
			let r = await Le(t, e);
			if (n !== this.searchCall) return;
			this.list = {
				status: "ready",
				stops: r
			};
		} catch (t) {
			if (n !== this.searchCall) return;
			this.list = {
				status: "failed",
				error: t,
				query: e
			};
		}
	}
	clearList() {
		this.searchCall++, this.list = void 0;
	}
	open(e) {
		this.clearList(), dt(e.kind, e), this.opened = e, this.board = { status: "loading" }, this.fetchOpened();
	}
	reopen(e) {
		let t = ut(e);
		this.stopCall++, t === void 0 ? (this.opened = void 0, this.board = void 0) : (this.opened = {
			kind: e,
			code: t.code,
			name: t.name,
			direction: null
		}, this.board = { status: "loading" }, document.visibilityState === "visible" && this.fetchOpened());
	}
	async fetchOpened() {
		let { hass: e, opened: t } = this;
		if (e === void 0 || t === void 0) return;
		let n = ++this.stopCall;
		this.board?.status === "failed" && (this.board = { status: "loading" });
		try {
			let r = t.kind === "bizi" ? {
				status: "bizi",
				response: await ze(e, t.code)
			} : {
				status: "arrivals",
				response: await Re(e, t.kind, t.code)
			};
			if (n !== this.stopCall) return;
			this.board = r, this.refresh.succeeded(vt(r.response.updated, Date.now()));
		} catch (e) {
			if (n !== this.stopCall) return;
			this.board = {
				status: "failed",
				error: e
			}, this.refresh.failed();
		}
	}
};
Q([Ne({ attribute: !1 })], $.prototype, "hass", void 0), Q([F()], $.prototype, "settings", void 0), Q([F()], $.prototype, "mode", void 0), Q([F()], $.prototype, "origin", void 0), Q([F()], $.prototype, "zone", void 0), Q([F()], $.prototype, "query", void 0), Q([F()], $.prototype, "list", void 0), Q([F()], $.prototype, "opened", void 0), Q([F()], $.prototype, "board", void 0);
function Ot(e) {
	let t = `footer.${(e?.status === "arrivals" || e?.status === "bizi" ? e.response.source : void 0) ?? "zaragoza_city"}`;
	return Qe(t) ? t : "footer.zaragoza_city";
}
function kt(e, t, n, r) {
	return E`<button class="chip" aria-pressed=${n ? "true" : "false"} @click=${r}>
    <ha-icon .icon=${t.icon}></ha-icon>
    ${Z(e, t.label)}
  </button>`;
}
function At(e, t, n) {
	let r = t.direction === null ? t.lines.length > 0 ? E`<span class="detail lines">${t.lines.map((e) => E`<span class="pill">${e}</span>`)}</span>` : O : E`<span class="detail">${Z(e, "stop.direction", { direction: t.direction })}</span>`;
	return E`<button class="stop" @click=${n}>
    <span class="name">${t.name}</span>
    ${r}
    <span class="distance">${Z(e, "stop.distance", { distance: t.distance_m })}</span>
  </button>`;
}
function jt(e, t, n) {
	return E`<div class="error" role="alert">
    <span>${st(e, t)}</span>
    <button class="retry" @click=${n}>${Z(e, "action.retry")}</button>
  </div>`;
}
function Mt(e, t) {
	return t.arrivals.length === 0 ? E`<p class="note">${Z(e, "arrivals.none")}</p>` : E`<ul class="arrivals">
    ${t.arrivals.map((t) => E`<li>
          <span class="pill">${t.line}</span>
          <span class="destination">${t.destination}</span>
          <span class="minutes">${Z(e, "arrivals.minutes", { minutes: t.minutes })}</span>
          <span class="time">${ot(e, t.time)}</span>
        </li>`)}
  </ul>`;
}
function Nt(e, t) {
	let { electric: n, mechanical: r } = t;
	return E`<ul class="bikes">
      ${[...n === null || r === null ? [[
		"mdi:bicycle",
		t.bikes,
		"bizi.bikes"
	]] : [[
		"mdi:bicycle-electric",
		n,
		"bizi.electric"
	], [
		"mdi:bicycle",
		r,
		"bizi.mechanical"
	]], [
		"mdi:parking",
		t.docks,
		"bizi.docks"
	]].map(([t, n, r]) => E`<li>
            <ha-icon .icon=${t}></ha-icon>
            <span class="count">${n}</span>
            <span class="what">${Z(e, r)}</span>
          </li>`)}
    </ul>
    ${t.renting ? O : E`<p class="note">${Z(e, "bizi.not_renting")}</p>`}
    ${t.returning ? O : E`<p class="note">${Z(e, "bizi.not_returning")}</p>`}`;
}
customElements.get("zaragoza-open-data-card") === void 0 && customElements.define(St, $), window.customCards ??= [], window.customCards.some((e) => e.type === "zaragoza-open-data-card") || window.customCards.push({
	type: St,
	name: X["card.name"],
	description: X["card.description"],
	preview: !0
});
export { St as CARD_TAG, $ as ZaragozaOpenDataCard };
