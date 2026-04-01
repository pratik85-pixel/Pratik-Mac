type LogArgs = unknown[];

/**
 * Minimal logger to avoid flooding the JS thread in production.
 * - `debug` is a no-op outside __DEV__.
 * - `info` is also dev-only (can be promoted later if needed).
 * - `warn`/`error` always log (keeps visibility for unexpected issues).
 */
export const log = {
  debug: (...args: LogArgs) => {
    if (__DEV__) console.log(...args);
  },
  info: (...args: LogArgs) => {
    if (__DEV__) console.log(...args);
  },
  warn: (...args: LogArgs) => {
    console.warn(...args);
  },
  error: (...args: LogArgs) => {
    console.error(...args);
  },
} as const;

