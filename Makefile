.PHONY: install up watch serve demo demo-up demo-gif release-prepare release-check reset-demo walkthrough test
install:        ## pip install -e . (editable)
	pip install -e .
up:             ## serve the gallery at http://127.0.0.1:8300
	curiator up
watch:          ## arm the feedback -> fix loop (run in a second terminal)
	curiator watch
serve:          ## gallery + fix loop together (one process)
	curiator serve
demo:           ## record-ready: reset the demo, then serve (gallery + watcher) at :8300
	curiator demo-up
demo-gif:       ## render the README demo GIF storyboard to docs/demo.gif
	python scripts/render_demo_gif.py
release-prepare:  ## cut release metadata; use VERSION=0.2.0 DATE=YYYY-MM-DD
	@if [ -z "$(VERSION)" ]; then echo "VERSION=... is required"; exit 2; fi
	python scripts/prepare_release.py "$(VERSION)" $(if $(DATE),--date "$(DATE)")
release-check:  ## local release gate: lint, tests, demo gif, gallery preflight, package build
	rm -rf dist build curiator.egg-info
	ruff check curiator tests scripts
	pytest -q
	python scripts/check_release_docs.py
	curiator release-preflight --fresh-clone
	python scripts/render_demo_gif.py
	python -m build
	python -m twine check dist/*
reset-demo:     ## rewind for another take: re-break aviato, clear the ledger
	curiator reset-demo
walkthrough:    ## print the demo recording script
	curiator demo
test:
	pytest -q
