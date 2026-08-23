# Contributing

Keep changes evidence-first and small enough to verify.

1. Add or update a test for observable behavior.
2. Preserve the observed/third-party/calculated/prediction/assumption labels.
3. Never join information backward across a gameweek deadline.
4. Do not add a paid or scraped source without terms, provenance, failure handling, and
   a zero-cost operating case.
5. Run `python -m unittest discover -v` and `python -m compileall -q src tests`.
6. Never commit database credentials, public-manager personal data dumps, or raw API archives.

Model changes need a new version and an evaluation comparison against the current model.
