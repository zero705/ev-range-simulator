# Security policy

## Reporting a vulnerability

Please report a security problem privately, through GitHub's private vulnerability reporting
for this repository (the **Security** tab, then **Report a vulnerability**), and not in a public
issue. Include the file or page concerned, the steps that reproduce the problem and the impact
you expect.

Only the latest version on the `main` branch is supported.

## What the project exposes, and how it is protected

- **The app** has no accounts and stores nothing. It accepts no uploads and no free text, and
  it makes no outbound requests. Every input is a choice from a fixed list or a bounded slider,
  checked again by the model, and every number is computed from the data in this repository.
  No HTML is rendered, and a link is made only for a plain HTTPS address. Visitors see a
  generic message if something fails; details go to the server log only
  (`.streamlit/config.toml`).
- **The scripts in `tools/`** download public documents and query the EEA's public, read-only
  service. They accept HTTPS only, redirects included, and cap the size of every download.
  They put a document in place only if its SHA-256 fingerprint matches the one recorded in the
  repository, and they parse a document only after that check. Spreadsheets are parsed with
  defusedxml, against XML attacks.
- **The supply chain.** The app's deployment dependencies are pinned in `requirements.txt` and
  tested in CI as pinned. Dependabot proposes updates to them and to the pinned GitHub Actions
  once a release is a week old. CI audits the dependencies with pip-audit and lints the code
  with the flake8-bandit security rules. CodeQL scans the Python code and the workflows. The
  workflows can only read the repository (CodeQL may also upload its findings to code
  scanning), use no secrets, and keep no credentials. The Actions they call are pinned to
  full commit SHAs.
