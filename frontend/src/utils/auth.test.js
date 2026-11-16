// Futtatás: npm test (node --test, külső függőség nélkül)
import assert from "node:assert/strict";
import test from "node:test";

import { isOwnPath } from "./auth.js";

const ORIGIN = "https://ev.energiafelho.hu";

test("return_to: saját útvonal elfogadva", () => {
  for (const p of ["/toltesek", "/", "/?cp=3f2a", "/charging/12?t=v1i.a.b.c", "/a//b"]) {
    assert.equal(isOwnPath(p, ORIGIN), true, p);
  }
});

test("return_to: idegen oldalra vivő érték elutasítva (nyílt átirányítás)", () => {
  const bad = [
    "//tamado.hu", "/\\tamado.hu", "/\\/tamado.hu", "\\\\tamado.hu", "/\t/tamado.hu", "/\n/tamado.hu",
    "https://tamado.hu", "javascript:alert(1)", "toltesek", "", null, undefined, 5,
  ];
  for (const p of bad) assert.equal(isOwnPath(p, ORIGIN), false, String(p));
});
