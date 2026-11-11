// Under Vitest, Lit runs its development build, which says so once on the console. Its
// other development warnings point at real mistakes, so only that one is turned off: Lit
// gives no warning whose code is already in its set of warnings given.
const given: unknown = Reflect.get(globalThis, "litIssuedWarnings");
if (given instanceof Set) given.add("dev-mode");
else Reflect.set(globalThis, "litIssuedWarnings", new Set(["dev-mode"]));
