# Releasing `agent-autopsy` on PyPI

The **PyPI distribution** is [`agent-autopsy`](https://pypi.org/project/agent-autopsy/) (the name `autopsy` is taken). The **Python import** remains `autopsy`; the **CLI** is `agent-autopsy`.

## One-time setup

1. PyPI account + 2FA: https://pypi.org
2. **Trusted publisher** (PyPI → Publishing → Add pending publisher):
   - PyPI project name: `agent-autopsy`
   - Owner: `JNR-10`
   - Repository: `autopsy`
   - Workflow filename: `publish.yml`
3. Add MIT `LICENSE` in repo (required for metadata)

## Each release

1. Ensure CI is green on `main`
2. Bump version in **both** `pyproject.toml` and `autopsy/__init__.py`
3. Move `[Unreleased]` in `CHANGELOG.md` to `## [x.y.z] - date`
4. Commit, tag, push:

```bash
git tag v0.2.0
git push origin main
git push origin v0.2.0
```

5. GitHub → **Releases** → **Draft new release** → publish tag `v0.2.0`

That triggers `.github/workflows/publish.yml` (OIDC upload to PyPI).

## Smoke test locally

```bash
pip install build
python -m build
pip install dist/agent_autopsy-*.whl   # wheel name uses underscore
agent-autopsy --help
python -c "from autopsy import lens; print('ok')"
```

## What users install

```bash
pip install agent-autopsy
pip install "agent-autopsy[server,diagnose,fast]"
```
