# CodeQL source analysis

The `CodeQL` workflow analyzes the repository's Python source with the `security-extended` query suite. It runs on pushes, pull requests, a weekly Monday schedule at 04:23 UTC, and manual dispatch. It is independent of the existing test, type-check, Ruff, and container jobs.

The workflow uses Python 3.14 and the `none` build mode. It does not install application dependencies or start the API or desktop client. Actions are pinned to full commit hashes and tracked by the existing Dependabot configuration. Only the analysis job receives `security-events: write` to publish findings. Pull requests use the normal `pull_request` event, including fork requests; the workflow does not execute pull-request code with elevated secrets through `pull_request_target`.

## Enable and verify

1. Commit and push `.github/workflows/codeql.yml` and this document. Public repositories support CodeQL code scanning. Private repositories require the appropriate GitHub Code Security entitlement.
2. If the repository already has CodeQL **default setup** enabled, switch it to advanced setup first. Default and workflow-based setup should not run together.
3. Open **Actions -> CodeQL -> Python analysis** and confirm initialization and analysis succeed. A scheduled run or manual dispatch is available after the workflow is on the default branch; ordinary push runs also cover the current development branch.
4. Open **Security -> Code scanning** and select CodeQL to review findings. The existing Trivy report is a separate source of alerts.
5. Fix confirmed issues with a regression test where appropriate. For a false positive, dismiss the specific alert with its reason. Do not disable a query or exclude a whole package merely to clear an individual finding.

A successful analysis job means the scan completed. Alert-based merge protection is a separate repository setting and is not added by this change. CodeQL does not replace the test suite or a manual demo rehearsal.

GitHub documents [advanced setup](https://docs.github.com/en/code-security/how-tos/find-and-fix-code-vulnerabilities/configure-code-scanning/configuring-advanced-setup-for-code-scanning) and [workflow options](https://docs.github.com/en/code-security/reference/code-scanning/workflow-configuration-options).
