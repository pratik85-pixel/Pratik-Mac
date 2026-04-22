// Jest setup shared by all tests. Keep this file light — big mocks belong
// in the per-test jest.mock() calls.

// react-native-reanimated requires this specific shim.
jest.mock('react-native-reanimated', () =>
  require('react-native-reanimated/mock'),
);

// Gesture handler's setup file installs matchers for integration tests.
// Importing it is a no-op when the module isn't installed (CI may skip).
try {
  require('react-native-gesture-handler/jestSetup');
} catch (_err) {
  /* ok — gesture-handler isn't required for unit tests */
}
