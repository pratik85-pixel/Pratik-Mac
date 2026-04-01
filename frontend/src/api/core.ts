// Shared API helpers (kept tiny on purpose).

// All endpoint functions return { data: T } so call-sites can uniformly do `res.data`.
export type W<T> = { data: T };
export function wrap<T>(val: T): W<T> {
  return { data: val };
}

