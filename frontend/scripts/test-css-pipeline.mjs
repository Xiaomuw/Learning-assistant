/** Build-tool compatibility: original temporary sources, actual project theme/globs. */
import assert from "node:assert/strict";
import { after, before, test } from "node:test";
import { mkdtemp, mkdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import postcss from "postcss";
import tailwindcss from "tailwindcss";
import loadConfig from "tailwindcss/loadConfig.js";
import autoprefixer from "autoprefixer";

const projectRoot = dirname(dirname(fileURLToPath(import.meta.url)));
let fixtureDirectory;
let stylesheet;

before(async () => {
  fixtureDirectory = await mkdtemp(join(tmpdir(), "learning-assistant-css-"));
  const sources = {
    "app/nested/page.tsx": '<div className="bg-neo-bg md:grid-cols-2" />',
    "components/Card.jsx": '<div className="select-none hover:bg-neo-accent" />',
    "lib/styles.ts": 'export const classes = "dark:text-neo-ink w-[37px]";',
  };
  for (const [path, content] of Object.entries(sources)) {
    const target = join(fixtureDirectory, path);
    await mkdir(dirname(target), { recursive: true });
    await writeFile(target, content);
  }
  const config = loadConfig(join(projectRoot, "tailwind.config.ts"));
  const result = await postcss([
    tailwindcss({
      ...config,
      content: config.content.map((pattern) => resolve(fixtureDirectory, pattern)),
    }),
    // Fixed test target exercises Browserslist + Autoprefixer deterministically.
    // Production browser targets are unchanged.
    autoprefixer({ overrideBrowserslist: ["Safari 12"] }),
  ]).process("@tailwind utilities;", { from: undefined });
  stylesheet = result.root;
});

after(async () => {
  if (fixtureDirectory) await rm(fixtureDirectory, { recursive: true, force: true });
});

function ruleFor(classSelector) {
  let found;
  stylesheet.walkRules((rule) => {
    if (rule.selector.includes(classSelector)) found = rule;
  });
  assert.ok(found, `missing generated selector: ${classSelector}`);
  return found;
}

function declaration(rule, property) {
  const found = rule.nodes.find((node) => node.type === "decl" && node.prop === property);
  assert.ok(found, `missing ${property} in ${rule.selector}`);
  return found.value;
}

test("project content globs retain custom theme and arbitrary-width utilities", () => {
  assert.match(declaration(ruleFor(".bg-neo-bg"), "background-color"), /255 253 248/);
  assert.equal(declaration(ruleFor(".w-\\[37px\\]"), "width"), "37px");
});

test("responsive, hover and class-based dark variants retain their conditions", () => {
  const responsive = ruleFor(".md\\:grid-cols-2");
  assert.equal(responsive.parent.type, "atrule");
  assert.equal(responsive.parent.name, "media");
  assert.equal(responsive.parent.params, "(min-width: 768px)");
  assert.equal(declaration(responsive, "grid-template-columns"), "repeat(2, minmax(0, 1fr))");
  const hover = ruleFor(".hover\\:bg-neo-accent");
  assert.ok(hover.selector.endsWith(":hover"));
  assert.match(declaration(hover, "background-color"), /255 179 198/);
  const dark = ruleFor(".dark\\:text-neo-ink");
  assert.ok(dark.selector.includes(":is(.dark *)"));
  assert.match(declaration(dark, "color"), /30 41 59/);
});

test("browser-target processing preserves prefixed and standard selection rules", () => {
  const rule = ruleFor(".select-none");
  assert.equal(declaration(rule, "-webkit-user-select"), "none");
  assert.equal(declaration(rule, "user-select"), "none");
});
