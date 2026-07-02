# curIAtor companion paper

This folder holds the Zenodo-first companion paper draft and the reproducibility notes for its
case-study numbers.

Current state:

- `curiator-paper.md` is a structured Markdown draft, not a publication-ready manuscript.
- `reproducibility.md` records the commands that must produce every quantitative table in the paper.
- Public-collection numbers are placeholders until the example repositories are published and verified
  from fresh clones.

Release-time checklist:

1. Publish the three example collections.
2. Run the commands in `reproducibility.md` from fresh clones of those public repositories.
3. Replace every `TODO(release)` placeholder in `curiator-paper.md` with command-backed evidence.
4. Build/export the PDF for Zenodo.
5. Add the Zenodo concept DOI to `CITATION.cff` and the README badge.
