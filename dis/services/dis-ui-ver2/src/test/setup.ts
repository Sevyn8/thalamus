import '@testing-library/jest-dom'

import { Buffer } from 'node:buffer'
import { webcrypto } from 'node:crypto'
import { TextDecoder, TextEncoder } from 'node:util'

// jsdom installs its own copies of the typed-array and text-encoding globals from
// a separate JS realm and omits SubtleCrypto. That breaks Node-realm libraries
// like jose: its internally encoded payload fails an `instanceof Uint8Array`
// check, and HMAC sign/verify needs crypto.subtle. Align these globals on Node's
// realm so jose behaves under jsdom exactly as it does in the browser. (Node's
// Uint8Array/ArrayBuffer are reached via the Buffer prototype chain, since the
// bare identifiers here already resolve to jsdom's copies.)
const NodeUint8Array = Object.getPrototypeOf(Buffer.prototype).constructor as Uint8ArrayConstructor
const NodeArrayBuffer = new NodeUint8Array(0).buffer.constructor as ArrayBufferConstructor

globalThis.Uint8Array = NodeUint8Array
globalThis.ArrayBuffer = NodeArrayBuffer
globalThis.TextEncoder = TextEncoder
globalThis.TextDecoder = TextDecoder as unknown as typeof globalThis.TextDecoder
if (globalThis.crypto?.subtle === undefined) {
  Object.defineProperty(globalThis, 'crypto', { value: webcrypto, configurable: true })
}

// jsdom omits window.matchMedia. Provide a minimal stub (defaults to light) so any
// consumer that reads the system color scheme mounts without throwing under tests.
if (typeof window !== 'undefined' && window.matchMedia === undefined) {
  window.matchMedia = (query: string) =>
    ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    }) as unknown as MediaQueryList
}
