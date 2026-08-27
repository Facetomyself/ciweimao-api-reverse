import { describe, expect, it } from "vitest";
import { categoryLabel, formatBytes, shortHash } from "./format";

describe("format helpers", () => {
  it("formats storage sizes", () => {
    expect(formatBytes(1024)).toBe("1.0 KB");
    expect(formatBytes(10 * 1024 * 1024)).toBe("10 MB");
  });

  it("keeps operational labels human readable", () => {
    expect(categoryLabel("risk_rejected")).toBe("风控拒绝");
    expect(shortHash("1234567890abcdef")).toBe("1234567890ab…");
  });
});
