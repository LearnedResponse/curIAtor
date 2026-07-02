# curIAtor galleries workspace

This directory is for local nested gallery repos named `curiator-*`.

Each gallery remains its own git repository with its own `.git` directory. The parent `curiator`
repo intentionally ignores `galleries/curiator-*/` so private collections and gallery histories are
not accidentally committed into the runner repo.

Current local gallery repos:

- `curiator-Kwisatz` — private research-origin gallery; dirty local work is preserved in the nested copy.
- `curiator-aviato` — mixed-framework app-directory/proxy proof collection.
- `curiator-finance` — seeded finance self-building demo.
- `curiator-geometry` — public-knowledge math/geometry quickstart collection.
- `curiator-ot` — OT/HMI maintenance flagship collection.

Run curIAtor against a nested gallery with:

```bash
CURIATOR_GALLERY=galleries/curiator-geometry/gallery.yaml curiator status
CURIATOR_GALLERY=galleries/curiator-geometry/gallery.yaml curiator up
```

When editing a nested gallery, commit inside that gallery repo, not in the parent runner repo.

Before publishing or moving the public examples, run:

```bash
curiator release-preflight
```

It checks the default public release set (`curiator-aviato`, `curiator-ot`, `curiator-geometry`) for
dirty nested repos, tracked machine-local paths, `curiator doctor` errors, and smoke failures.
