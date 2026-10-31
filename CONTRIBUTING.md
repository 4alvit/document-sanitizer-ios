# Contributing

Use synthetic fixtures only. The repository must never contain user documents,
private household data, signing credentials, Terraform state or harness traces.
Make small changes on a branch and open a pull request. Include how the issue
was reproduced and which independent export checks cover it.

Run the Swift tests, the independent corpus checks and the iOS build as described
in README.md. A passing parser check does not prove that a mask is correctly
positioned; include pixel comparisons for geometry changes. Keep all source
documents unchanged. Do not log filenames or document contents in the app.

By contributing, you agree that your contribution is provided under the MIT
license included in this repository. Do not copy proprietary competitor code,
screenshots, branding or documentation.

