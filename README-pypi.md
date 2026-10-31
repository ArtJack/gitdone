# GitDone

<!-- mcp-name: io.github.ArtJack/gitdone -->

A percent done you can defend. Strict and weighted completion from one plan file and one status table, with every claim
held to git: a row is Live when a commit on the default branch or a merged pull request says so, and a commit that would
make the view lie is refused.

```bash
uvx gitdone init --rows "Sign-in, Search, Export" --hook
uvx gitdone shipped 1 abc1234     # refused unless abc1234 is on the default branch
uvx gitdone check                 # the gate; the hook runs it on every commit that touches the tracker
```

Python 3.9 or newer, standard library only, no model calls. It starts `git`, and `gh` when a row names a pull request.

Documentation, the method and the GitHub Action: https://github.com/ArtJack/gitdone

MIT license.
