// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import "@testing-library/jest-dom";
import { cleanup } from "@testing-library/react";
import { afterAll, afterEach, beforeAll } from "vitest";
import { clearSession, setRefreshHandler } from "@/lib/auth";
import { server } from "./server";

// jsdom brings its own AbortSignal, which Node's built-in `Request` rejects ("Expected signal to be an
// instance of AbortSignal"); React Router's data router creates exactly that pair on every navigation.
// The tests never abort a navigation, so the signal is dropped before it reaches Node's `Request`.
const NodeRequest = globalThis.Request;
class TestRequest extends NodeRequest {
  constructor(input: RequestInfo | URL, init?: RequestInit) {
    super(input, init?.signal ? { ...init, signal: null } : init);
  }
}
globalThis.Request = TestRequest;

beforeAll(() => {
  server.listen({ onUnhandledRequest: "error" });
});

afterEach(() => {
  cleanup();
  server.resetHandlers();
  clearSession();
  setRefreshHandler(null);
  document.documentElement.removeAttribute("data-theme");
  window.localStorage.clear();
});

afterAll(() => {
  server.close();
});
