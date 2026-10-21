# Security Policy

Learning Assistant is under development. No stable or long-term-supported release has been designated. Do not assume that the default branch has undergone a professional security audit.

## Reporting a vulnerability

**Do not post exploit details, active credentials, personal information or proof-of-concept payloads in a public issue or pull request.**

1. Check the repository's **Security** tab. If GitHub private vulnerability reporting is available, use **Report a vulnerability**.
2. If private vulnerability reporting is unavailable, create a public issue titled **"Request a private security reporting channel"** *without including vulnerability details*. The maintainer can then arrange a non-public reporting method.
3. Provide steps to reproduce, affected version or commit, likely impact and proposed mitigations through the private channel only.

Private vulnerability reporting is not claimed to be enabled until the maintainer checks the repository settings.

## Scope and safe handling

Authentication, cookies, API keys, file ingestion, RAG retrieval, user data isolation, and MCP/web-search tooling are security-sensitive. Use synthetic test data and isolated environments for reports. Do not test against other people's accounts or deployments without permission.

The maintainer will assess reports based on available capacity. This project does not currently promise a response time, security bounty or coordinated-disclosure SLA.
