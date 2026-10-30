// npm run check:css
//
// Fails (exit 1) when:
//   1. the SCSS doesn't compile, or Sass prints any warning (deprecations included);
//      this includes the WCAG contrast checks in scss/abstracts/_checks.scss;
//   2. a Django template uses a class that no CSS rule styles (typo or missing style).
// Reports, without failing, CSS classes that no template uses yet.

import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import * as sass from "sass";

const root = path.resolve(import.meta.dirname, "..");
const entry = path.join(root, "scss", "main.scss");
const templatesDir = path.resolve(root, "..", "main", "templates");

// Classes that are hooks only (no styles needed), with the reason.
const UNSTYLED_ON_PURPOSE = new Map([
  ["brand", "<article> wrapper on the brand page"],
  ["review", "<article> wrapper on the review page"],
  ["brand-card", "modifier hook; shares .card"],
  ["review-card", "modifier hook; shares .card"],
  ["brand-summary", "<aside> landmark; its panel is .brand-summary__body"],
]);

function fail(message) {
  console.error(`check:css FAILED\n${message}`);
  process.exit(1);
}

// 1. Compile ----------------------------------------------------------------
const warnings = [];
let css;
try {
  ({ css } = sass.compile(entry, {
    style: "expanded",
    logger: {
      warn: (message, { span }) =>
        warnings.push(span ? `${span.url?.pathname}:${span.start.line + 1}: ${message}` : message),
      debug: () => {},
    },
  }));
} catch (error) {
  fail(error.message);
}
if (warnings.length) fail(`Sass warnings:\n- ${warnings.join("\n- ")}`);

// 2. Template classes vs. CSS classes -----------------------------------------
const cssClasses = new Set([...css.matchAll(/\.(-?[_a-zA-Z][\w-]*)/g)].map((m) => m[1]));

function* htmlFiles(dir) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) yield* htmlFiles(full);
    else if (entry.name.endsWith(".html")) yield full;
  }
}

const used = new Map(); // class -> first template using it
for (const file of htmlFiles(templatesDir)) {
  const html = readFileSync(file, "utf8");
  for (const [, value] of html.matchAll(/class="([^"]*)"/g)) {
    const names = value.replace(/\{[{%].*?[%}]\}/g, " ").split(/\s+/).filter(Boolean);
    for (const name of names) {
      if (!used.has(name)) used.set(name, path.relative(templatesDir, file));
    }
  }
}

const missing = [...used].filter(([name]) => !cssClasses.has(name) && !UNSTYLED_ON_PURPOSE.has(name));
if (missing.length) {
  fail(
    "Template classes with no CSS rule:\n" +
      missing.map(([name, file]) => `- .${name} (${file})`).join("\n") +
      "\nStyle them, fix the typo, or add them to UNSTYLED_ON_PURPOSE with a reason.",
  );
}

const unused = [...cssClasses].filter((name) => !used.has(name)).sort();
const kb = (Buffer.byteLength(css) / 1024).toFixed(1);
console.log(`check:css OK: compiled without warnings (${kb} KB expanded), contrast checks passed,`);
console.log(`  ${used.size} template classes all styled (${UNSTYLED_ON_PURPOSE.size} hooks unstyled on purpose).`);
if (unused.length) console.log(`  Not used by any template yet: ${unused.map((n) => "." + n).join(", ")}`);
