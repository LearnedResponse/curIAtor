.PHONY: install up watch serve demo demo-up reset-demo walkthrough test
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
reset-demo:     ## rewind for another take: re-break aviato, clear the ledger
	curiator reset-demo
walkthrough:    ## print the demo recording script
	curiator demo
test:
	pytest -q
