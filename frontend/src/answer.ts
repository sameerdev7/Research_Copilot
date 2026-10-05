// trailing citation tags like "[2]" or "[1][3]"
const TRAILING_TAGS = /\s*((?:\[\d+\]\s*)+)$/;

export interface Line {
  text: string;
  refs: number[];
}

export function parseAnswer(content: string): Line[] {
  return content
    .split("\n")
    .filter((line) => line.trim())
    .map((line) => {
      const match = line.match(TRAILING_TAGS);
      if (!match) return { text: line, refs: [] };
      return {
        text: line.slice(0, match.index),
        refs: [...match[1].matchAll(/\d+/g)].map((m) => Number(m[0])),
      };
    });
}
