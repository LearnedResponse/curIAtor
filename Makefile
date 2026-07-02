.PHONY: install up watch serve demo demo-up demo-gif demo-capture annotation-dogfood narrated-dogfood release-prepare release-check release-launch-check release-evidence paper-stats reset-demo walkthrough test
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
demo-capture:   ## capture docs/demo.gif from a real Brave-rendered gallery
	python scripts/capture_demo_gif.py
annotation-dogfood:  ## validate screenshot annotation capture through a real Brave-rendered shell
	python scripts/dogfood_annotations_brave.py
narrated-dogfood:  ## validate voice + timed annotation feedback through a real Brave-rendered shell
	python scripts/dogfood_narrated_feedback_brave.py
release-prepare:  ## cut release metadata; use VERSION=0.2.0 DATE=YYYY-MM-DD
	@if [ -z "$(VERSION)" ]; then echo "VERSION=... is required"; exit 2; fi
	python scripts/prepare_release.py "$(VERSION)" $(if $(DATE),--date "$(DATE)")
release-check:  ## local release gate: lint, tests, docs/demo.gif presence, gallery preflight, package build
	rm -rf dist build curiator.egg-info
	ruff check curiator tests scripts
	pytest -q
	python scripts/check_release_docs.py
	curiator release-preflight --fresh-clone --strict
	python -m build
	python -m twine check dist/*
release-launch-check:  ## final public-launch gate: reject generated/paper placeholders and optional-gallery drift
	@set +e; \
	python scripts/check_release_docs.py --strict-launch; docs_status=$$?; \
	curiator release-preflight --include-optional --fresh-clone --strict; preflight_status=$$?; \
	exit $$((docs_status || preflight_status))
release-evidence:  ## write gitignored JSON/Markdown evidence snapshots under release-evidence/
	curiator release-preflight --fresh-clone --strict --json --output release-evidence/release-preflight.json
	curiator release-preflight --include-optional --fresh-clone --strict --json --output release-evidence/release-preflight-optional.json
	curiator stats compare galleries/curiator-aviato galleries/curiator-ot galleries/curiator-geometry --markdown --output release-evidence/case-study-stats.md
	curiator stats compare galleries/curiator-aviato galleries/curiator-ot galleries/curiator-geometry --json --output release-evidence/case-study-stats.json
paper-stats: release-evidence  ## refresh the companion paper's tracked case-study stats table
	python scripts/update_paper_stats.py --stats-file release-evidence/case-study-stats.md
reset-demo:     ## rewind for another take: re-break aviato, clear the ledger
	curiator reset-demo
walkthrough:    ## print the demo recording script
	curiator demo
test:
	pytest -q
