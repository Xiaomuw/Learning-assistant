module.exports = {
  root: true,
  extends: ["taro/react"],
  parser: "@typescript-eslint/parser",
  plugins: ["@typescript-eslint"],
  rules: {
    "react/prop-types": "off",
    "react/react-in-jsx-scope": "off",
    "jsx-quotes": "off",
    "@typescript-eslint/no-explicit-any": "off"
  }
};
