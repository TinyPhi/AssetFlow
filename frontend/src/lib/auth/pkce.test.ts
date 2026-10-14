// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import { afterEach, describe, expect, it } from "vitest";
import {
  LoginTransactionError,
  beginLoginTransaction,
  codeChallengeS256,
  completeLoginTransaction,
} from "./pkce";

afterEach(() => {
  window.sessionStorage.clear();
});

describe("pkce", () => {
  it("computes the RFC 7636 appendix B S256 challenge", async () => {
    expect(await codeChallengeS256("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk")).toBe(
      "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
    );
  });

  it("begins with an S256 challenge, state and nonce and stores only the transaction", async () => {
    const params = await beginLoginTransaction();
    expect(params.codeChallengeMethod).toBe("S256");
    expect(params.codeChallenge).toMatch(/^[A-Za-z0-9_-]{43}$/);
    expect(params.state).not.toBe(params.nonce);
    const txn = completeLoginTransaction(params.state);
    expect(await codeChallengeS256(txn.codeVerifier)).toBe(params.codeChallenge);
    expect(txn.nonce).toBe(params.nonce);
  });

  it("clears the verifier after the return", async () => {
    const params = await beginLoginTransaction();
    completeLoginTransaction(params.state);
    expect(window.sessionStorage.length).toBe(0);
    expect(() => completeLoginTransaction(params.state)).toThrow(LoginTransactionError);
  });

  it("rejects a returned state that does not match and still clears the transaction", async () => {
    await beginLoginTransaction();
    expect(() => completeLoginTransaction("forged")).toThrow(LoginTransactionError);
    expect(window.sessionStorage.length).toBe(0);
  });

  it("rejects a missing state and a damaged stored transaction", async () => {
    await beginLoginTransaction();
    expect(() => completeLoginTransaction(null)).toThrow(LoginTransactionError);
    window.sessionStorage.setItem("af.oidc.txn", "{not json");
    expect(() => completeLoginTransaction("x")).toThrow(LoginTransactionError);
  });
});
