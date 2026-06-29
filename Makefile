.PHONY: install up watch demo test
install:        ## pip install -e . (editable)
	pip install -e .
up:             ## serve the gallery at http://127.0.0.1:8200
	curiator up
watch:          ## arm the feedback -> fix loop (run in a second terminal)
	curiator watch
demo:           ## print the demo walkthrough
	curiator demo
test:
	pytest -q
