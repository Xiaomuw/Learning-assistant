import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

export default defineConfig([
  ...nextVitals,
  ...nextTs,
  // Pre-existing component effects are unchanged during this dependency-only
  // migration. Limit the React 19 new rule's exception to those files; follow
  // up with a separate state-effect refactor rather than risking UI behavior.
  {
    files: [
      "app/login/page.tsx",
      "app/register/page.tsx",
      "app/practice/page.tsx",
      "components/MessageProcessPanel.tsx",
    ],
    rules: { "react-hooks/set-state-in-effect": "off" },
  },
  globalIgnores([".next/**", "out/**", "build/**", "next-env.d.ts"]),
]);
