# Next.js security migration — Draft PR

**Review-only status: no production deployments and no merge into main.**

## Reason

The existing web client pins Next.js `14.2.29`, an unsupported major version affected by published security advisories. This branch proposes **Next.js 16.4.2** (released 2026-10-15, after the 16.4.1 security fixes) and **React 19.3.0**, updating the Next.js ESLint integration as well. Do not claim a vulnerability is exploited in this project simply because its version falls in an affected range.

Official references:
- https://nextjs.org/support-policy
- https://github.com/vercel/next.js/security/advisories
- https://github.com/vercel/next.js/releases/tag/v16.4.2
- https://nextjs.org/docs/app/guides/upgrading/version-16

## Breaking changes addressed

- Removed `next lint`; use the ESLint 9 CLI with the Next.js 16 flat ESLint config.
- Move `middleware.ts` to `proxy.ts` and export `proxy` to use the supported Node runtime convention.
- Use Node 22 in the CI/npm resolution workflow and the two production/development Dockerfiles.
- Use TypeScript type declarations compatible with React 19.

## Dependency lockfile

The package lock must be regenerated from actual npm registry metadata. A narrowly scoped branch-only GitHub Actions workflow updates **only** `frontend/package-lock.json`, automatically committing to this draft branch. This avoids hand-editing integrity hashes; GitHub Actions might be blocked from pushing by repository permission settings. Do not merge without a committed, verified lockfile that passes `npm ci`.

## Verification matrix

- [ ] `npm ci` with package/lock consistency
- [ ] `npm run lint`
- [ ] `npm run typecheck`
- [ ] `npm run build` (Turbopack and/or an intentional webpack fallback)
- [ ] Tests for protected route redirect, login, logout, and cookie refresh
- [ ] Verify `/api/:path*` internal proxy and SSE response behavior
- [ ] Verify `next/image` usages, mobile layout and 404 handling
- [ ] `npm audit --omit=dev` and remaining advisory review
- [ ] Clean build of `frontend/Dockerfile.prod` with correctly configured API routing

CI build passing does not replace these manual behavioral tests. Avoid public deployment until all outstanding security issues are independently reviewed.
