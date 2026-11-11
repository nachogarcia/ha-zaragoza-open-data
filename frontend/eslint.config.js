import { defineConfig } from "eslint/config";
import tseslint from "typescript-eslint";

export default defineConfig(
  { ignores: ["node_modules/", "dist/"] },
  tseslint.configs.strictTypeChecked,
  {
    languageOptions: {
      parserOptions: { projectService: true, tsconfigRootDir: import.meta.dirname },
    },
    rules: {
      "@typescript-eslint/no-explicit-any": "error",
    },
  },
  {
    // This file itself is plain JavaScript, outside the TypeScript project.
    files: ["**/*.js"],
    extends: [tseslint.configs.disableTypeChecked],
  },
);
