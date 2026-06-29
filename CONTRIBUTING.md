# Contributing to curIAtor

Thanks for helping make the curator better! Here's how to get set up — and the two rules for PRs.

## Develop

```bash
git clone https://github.com/LearnedResponse/curiator && cd curiator
pip install -e ".[dev]"          # editable install + pytest & ruff
make test                        # run the suite (pytest)
ruff check curiator tests        # lint
```

Run `make test` and `ruff check` **before opening a PR** — CI runs both on Python 3.10–3.12 and gates
on a DCO sign-off (below). Try the loop locally with `make demo` (resets the broken `aviato`, starts
the gallery + the fix loop at http://127.0.0.1:8300).

## Add an app / start a collection

- **Add an app to a gallery:** drop `apps/<name>.py` exposing `build_app() -> dash.Dash` (plus a
  module-level `app`), then add an entry to `gallery.yaml`. Working examples live in `examples/dash/`.
- **Start your own collection:** `curiator init my-collection` scaffolds a `gallery.yaml` + a sample
  app + a feedback dir. Full guide: [`docs/USING_CURIATOR.md`](docs/USING_CURIATOR.md).
- **Improve the runner itself:** with `runner: { mode: checkout }`, feedback on the **◆ General**
  channel patches curiator's own source — curIAtor maintains curIAtor. Or just open a PR.

## 1. Sign off your commits (DCO)

We use the [Developer Certificate of Origin](https://developercertificate.org/) — a simple,
sign-off-based way to certify you have the right to submit your contribution. **There is no CLA
to sign.** You just add a `Signed-off-by` line to each commit:

```bash
git commit -s -m "your message"
```

which appends (using your `git config` name + email):

```
Signed-off-by: Your Name <your.email@example.com>
```

By signing off, you certify the Developer Certificate of Origin 1.1 (full text below). Pull
requests whose commits aren't signed off can't be merged. (`git rebase --signoff` can fix a
branch after the fact.)

## 2. License of contributions

Contributions are accepted under the project's license, **Apache-2.0** (see `LICENSE`). You keep
your copyright; you license your contribution to the project under Apache-2.0.

---

```
Developer Certificate of Origin
Version 1.1

Copyright (C) 2004, 2006 The Linux Foundation and its contributors.

Everyone is permitted to copy and distribute verbatim copies of this
license document, but changing it is not allowed.


Developer's Certificate of Origin 1.1

By making a contribution to this project, I certify that:

(a) The contribution was created in whole or in part by me and I
    have the right to submit it under the open source license
    indicated in the file; or

(b) The contribution is based upon previous work that, to the best
    of my knowledge, is covered under an appropriate open source
    license and I have the right under that license to submit that
    work with modifications, whether created in whole or in part
    by me, under the same open source license (unless I am
    permitted to submit under a different license), as indicated
    in the file; or

(c) The contribution was provided directly to me by some other
    person who certified (a), (b) or (c) and I have not modified
    it.

(d) I understand and agree that this project and the contribution
    are public and that a record of the contribution (including all
    personal information I submit with it, including my sign-off) is
    maintained indefinitely and may be redistributed consistent with
    this project or the open source license(s) involved.
```
