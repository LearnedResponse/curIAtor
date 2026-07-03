# Git-log provenance excerpt

Source command, run from the curIAtor runner checkout after the local `curiator-phylogenetics`
seed loop completed:

```bash
git -C galleries/curiator-phylogenetics log --grep='^curator' --format='%h %s%n%b----' -3
```

Excerpt:

```text
b1b3586 curator(tinnik_dash): Added a visible paper-story section map with anchors for CF ternary, qua
Feedback: "Split the Dash explorer into focused tabs or sections matching the paper story: CF ternary, quartet detail, NC = D, Lemma 9, and continuous walls."   (★★★)
Changed: edited apps/tinnik_dash_explorer      Smoke-test: passed

Curiator-App: tinnik_dash
Curiator-Feedback: d6580f43
Feedback-From: phylogeneticist@local
Co-Authored-By: curiator[codex] <noreply@curiator.dev>
Signed-off-by: Adam Guetz <curiator@local>
----
5d3d384 curator(tinnik_static): Added a browser-side CF triple classifier: users can paste or edit CF1,
Feedback: "Let me paste or edit a small quartet CF triple and classify it as cut/non-cut, with the genericity caveat shown inline."   (★★★)
Changed: edited apps/tinnik_pyodide_static      Smoke-test: passed

Curiator-App: tinnik_static
Curiator-Feedback: b76b2d6c
Feedback-From: phylogeneticist@local
Co-Authored-By: curiator[codex] <noreply@curiator.dev>
Signed-off-by: Adam Guetz <curiator@local>
----
d20725b curator(tinnik_dash): Added a visible claim-boundary panel near the top of the Dash explorer s
Feedback: "Add a visible claim-boundary panel that says the restricted-Voronoi continuous-wall route is open and is not what this companion is claiming."   (★★★★)
Changed: edited apps/tinnik_dash_explorer      Smoke-test: passed

Curiator-App: tinnik_dash
Curiator-Feedback: 77b96b87
Feedback-From: phylogeneticist@local
Co-Authored-By: curiator[codex] <noreply@curiator.dev>
Signed-off-by: Adam Guetz <curiator@local>
----
```

Use this figure to show the paper's "git as memory" claim: a feedback item, source scope, smoke-test
result, app name, feedback id, author, agent co-author, and signoff are tied to one normal git commit.
