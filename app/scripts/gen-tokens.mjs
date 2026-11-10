// Generates src/tokens.css (Tailwind v4 @theme) from design/tokens.json — the one token source shared
// with the engine's screenshot annotator (SPEC §9.1). Run by `npm run dev|build|test`.
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const t = JSON.parse(readFileSync(resolve(here, "../../design/tokens.json"), "utf8"));

const lines = ["/* Generated from design/tokens.json by scripts/gen-tokens.mjs — do not edit. */", "@theme {"];
for (const [k, v] of Object.entries(t.color.ui)) lines.push(`  --color-${k}: ${v};`);
t.color.ramp.forEach((v, i) => lines.push(`  --color-ramp-${i}: ${v};`));
lines.push(`  --color-accent: ${t.color.accent};`);
lines.push(`  --font-sans: "${t.font.body}", ui-sans-serif, sans-serif;`);
lines.push(`  --font-num: "${t.font.numeral}", "${t.font.body}", sans-serif;`);
lines.push(`  --radius-sheet: ${t.radius.sheet};`);
// exactly three text sizes (direction contract); numerals are sized separately
for (const k of ["title", "body", "small"]) lines.push(`  --text-${k}: ${t.font.size[k]};`);
lines.push("}");
// Dark mode (SPEC §9): same names, charcoal values, following the Windows app theme. Utilities read the
// variables, so every bg-paper / text-ink / border-edge switches without a dark: variant.
if (t.color.ui_dark) {
  lines.push("@media (prefers-color-scheme: dark) {", "  :root {");
  for (const [k, v] of Object.entries(t.color.ui_dark)) if (!k.startsWith("$")) lines.push(`    --color-${k}: ${v};`);
  (t.color.ramp_dark ?? []).forEach((v, i) => lines.push(`    --color-ramp-${i}: ${v};`));
  lines.push("    color-scheme: dark;", "  }", "}");
}
writeFileSync(resolve(here, "../src/tokens.css"), lines.join("\n") + "\n");
console.log("tokens.css written");
