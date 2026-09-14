### Summary

### Checklist

- [ ] `./scripts/verify.sh` passes locally (the same gates CI runs)
- [ ] `CHANGELOG.md` entry under `## Unreleased` for user-visible changes
- [ ] No hand-edited versions — `scripts/bump_version.py` owns all pins and version prose in the stamped docs
- [ ] New plugin? Updated `PLUGINS` in *both* `scripts/validate_marketplace.py` and `scripts/bump_version.py`, added its lines to `scripts/verify.sh`, and its directory to `.github/dependabot.yml`
- [ ] Security-relevant behavior checked against `SECURITY.md`; anything sensitive reported privately, not via issues
