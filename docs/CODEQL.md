# CodeQL source analysis

The `CodeQL` workflow runs the `security-extended` queries on the Python source for every push and pull request, on demand, and every Monday at 04:23 UTC. It uses the `none` build mode, so it installs nothing and starts neither the API nor the client. Actions are pinned to commit hashes, and only the analysis job can publish findings.

To use it, switch any CodeQL **default setup** to [advanced setup](https://docs.github.com/en/code-security/how-tos/find-and-fix-code-vulnerabilities/configure-code-scanning/configuring-advanced-setup-for-code-scanning) first, because the two should not run together, private repositories also need GitHub Code Security. Findings appear under **Security → Code scanning**, next to the Trivy findings from CI. Fix confirmed issues, with a regression test where it makes sense, and dismiss false positives one by one with a reason rather than disabling a query. A green run only means the scan finished, blocking merges on alerts is a separate repository setting.

## Full report on your machine

`bash scripts/codeql_local.sh` runs the broader `security-and-quality` suite locally and prints every finding, so quality results stay out of public CI logs. It downloads the CodeQL bundle on first use and writes results to `~/.cache/codeql-local/`, never into the repository: `results.sarif` is the printed report and `results-unfiltered.sarif` is CodeQL's complete output. The script lists the queries and known false positives it leaves out, each with its reason.
