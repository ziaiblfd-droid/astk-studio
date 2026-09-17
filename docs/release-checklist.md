# Release checklist

## Repository

- [ ] Confirm the GitHub account and create the `astk-studio` repository.
- [ ] Keep the repository public unless a private review period is needed.
- [ ] Add maintainer names, contact details, and `CITATION.cff`.
- [ ] Confirm the paper citation, DOI, and dataset links.
- [ ] Review `README.md`, `LICENSE`, `SECURITY.md`, and `CONTRIBUTING.md`.
- [ ] Enable GitHub Pages with GitHub Actions as the source.
- [ ] Restore automatic Pages deployment on pushes to `main` when the repository is ready for public release.

## Validation

- [ ] Run Python unit tests, JavaScript syntax check, and the Pages build.
- [ ] Test desktop and mobile layouts in the deployed Pages site.
- [ ] Confirm that Pages clearly identifies itself as a no-upload demo.
- [ ] Validate Docker build and real ASTK execution on a Linux host.
- [ ] Test all seven event types with a small shareable dataset.
- [ ] Confirm result ZIP contents and failure messages.

## Operations and security

- [ ] Mount references read-only and persist the job data volume.
- [ ] Put the service behind HTTPS and an authenticated reverse proxy if public.
- [ ] Set upload, worker, CPU, memory, and timeout limits.
- [ ] Confirm the retention period and automatic cleanup behavior.
- [ ] Document backup, monitoring, and incident response ownership.
- [ ] Obtain institutional approval before exposing campus infrastructure.

## Publication

- [ ] Tag the tested release and record the deployed commit.
- [ ] Archive a release in a long-term repository if required by the journal.
- [ ] Add the website, source repository, and self-hosting instructions to the paper.
- [ ] Verify external links from a network outside the institution.
