import { describe, expect, it } from "vitest";
import { parseAnswer } from "./answer";

describe("parseAnswer", () => {
  it("splits a line into text and its citation numbers", () => {
    expect(parseAnswer("Attention replaces recurrence. [2]")).toEqual([
      { text: "Attention replaces recurrence.", refs: [2] },
    ]);
  });

  it("reads a cluster of tags", () => {
    expect(parseAnswer("Both papers agree. [1][3]")[0].refs).toEqual([1, 3]);
  });

  it("keeps lines without tags and skips blank lines", () => {
    expect(parseAnswer("No tag here\n\n   \nTagged. [1]")).toEqual([
      { text: "No tag here", refs: [] },
      { text: "Tagged.", refs: [1] },
    ]);
  });

  it("only treats trailing tags as citations", () => {
    expect(parseAnswer("The array a[0] is first. [1]")[0].text).toBe("The array a[0] is first.");
  });
});
