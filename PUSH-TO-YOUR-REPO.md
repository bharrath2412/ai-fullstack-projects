# Getting this into your repo

This workspace is already a git repository: branch **`main`**, one clean commit,
**121 tracked files**, no junk (caches, `node_modules`, databases and generated artifacts are
git-ignored). Pick the option that matches your situation.

| Option | Use when | Keeps history? |
| --- | --- | --- |
| [1 · Push as a new repo](#option-1--make-this-your-repo) | you want this as its own GitHub repo | yes |
| [2 · Merge into an existing repo](#option-2--merge-into-an-existing-repo) | your repo already has work you must keep | yes |
| [3 · Copy projects into a subfolder](#option-3--copy-the-projects-into-a-subfolder) | your repo has its own top-level layout | no (one commit) |
| [4 · Vendor as a subtree](#option-4--vendor-as-a-git-subtree) | you may want to pull future updates | yes |
| [5 · From the bundle or zips](#option-5--from-the-bundle-or-zip) | you're moving files by hand | bundle: yes |

Everything below assumes you run it inside this workspace (`/home/user`).

---

## Option 1 · Make this your repo

Create an **empty** repo on GitHub (no README, no .gitignore — otherwise you get an instant
conflict), then:

```bash
git remote add origin git@github.com:<you>/<repo>.git
git push -u origin main
```

Or let the script do it (it checks whether the remote is empty first):

```bash
./scripts/push-to-repo.sh git@github.com:<you>/<repo>.git
```

HTTPS works too — use a personal access token as the password:
`https://<user>:<token>@github.com/<you>/<repo>.git`.

---

## Option 2 · Merge into an existing repo

This keeps *both* histories and pushes a merge commit. Nothing in your repo is deleted;
if a file collides you resolve it once.

```bash
cd ~/your-existing-repo
git checkout -b add-ai-portfolio            # work on a branch, open a PR after

# point at this workspace (path, or a clone of the bundle — see Option 5)
git remote add portfolio /home/user
git fetch portfolio

git merge --allow-unrelated-histories portfolio/main
```

Expected conflicts and how to resolve them:

| File | What to do |
| --- | --- |
| `README.md` | keep **yours** as `README.md`; save this one as `PROJECTS.md` (or copy its sections in) |
| `.gitignore` | keep the union of both — the additions here are `node_modules/`, `data/`, `artifacts/models/`, `__pycache__/`, `.cache/`, `.npm/`, `exports/` |
| `.github/workflows/ci.yml` | rename to `ci-projects.yml` if you already have CI |

Then:

```bash
git add -A && git commit -m "Add TaskFlow, AgentForge, churn ML service and DocMind RAG projects"
git push -u origin add-ai-portfolio
```

---

## Option 3 · Copy the projects into a subfolder

Simplest, and usually what you want if your repo is a portfolio or a learning repo:

```bash
cd ~/your-repo
mkdir -p projects
cp -r /home/user/project-01-taskflow-fullstack \
      /home/user/project-02-agentforge-ai-agent \
      /home/user/project-03-churn-ml-service \
      /home/user/project-04-docmind-rag projects/

git add projects && git commit -m "Add four full-stack/AI/ML/RAG projects"
```

Each project is fully self-contained (own README, requirements or package.json, Dockerfile,
tests), so nothing breaks — the monorepo `Makefile` and `docker-compose.yml` are optional extras
you can copy to the repo root or into `projects/`.

---

## Option 4 · Vendor as a git subtree

Lets you pull future fixes without merging the whole history:

```bash
cd ~/your-repo
git subtree add --prefix=projects/taskflow /home/user main --squash
```

(Repeat per project only if you split the repo first — by default the prefix contains *all four*
projects plus the root files.)

---

## Option 5 · From the bundle or zip

`exports/` contains ready-to-move artifacts (regenerate any time with `make export`):

```
exports/portfolio-monorepo.bundle     184 KB  full git history (branch main, 1 commit)
exports/portfolio-monorepo.zip        213 KB  source tree, no .git
exports/project-01-taskflow-fullstack.zip   70 KB
exports/project-02-agentforge-ai-agent.zip  50 KB
exports/project-03-churn-ml-service.zip     37 KB
exports/project-04-docmind-rag.zip          45 KB
```

**Bundle (keeps history):**

```bash
git clone /home/user/exports/portfolio-monorepo.bundle portfolio
cd portfolio
git remote set-url origin git@github.com:<you>/<repo>.git
git push -u origin main
```

**Zip (files only):**

```bash
unzip /home/user/exports/project-04-docmind-rag.zip -d ~/your-repo/projects/
cd ~/your-repo && git add projects && git commit -m "Add DocMind RAG project"
```

> The exports are git-ignored on purpose: they are build outputs, and a 200 KB zip inside a repo
> would go stale. Regenerate with `make export` after changes.

---

## Want me to push it for you?

I can run the push from this sandbox — there is outbound network access here — but GitHub is not
connected to this conversation, so I need:

1. the repo URL (`https://github.com/<you>/<repo>.git`), and
2. a **fine-grained token** with `Contents: write` on that single repo, created for this purpose
   and revoked right after.

Please prefer a token scoped to one repo and a short expiry (1 day). Anything you paste in chat is
visible in the conversation, and I will only use it for `git push` — I won't write it into any file
in the repo.

---

## After pushing — checklist

- [ ] `git log --oneline -3` shows the expected commits; `git status` is clean
- [ ] CI ran: the 4 jobs in `.github/workflows/ci.yml` (web 10 · agent 57 · ML 40 · RAG 44 tests + retrieval gate)
- [ ] `README.md` badges/numbers still match reality (`make test` locally)
- [ ] Secrets are absent: no `.env`, no keys — only `.env.example` files are tracked
- [ ] If you kept this as its own repo, add a short description + topics
      (`react`, `express`, `fastapi`, `rag`, `scikit-learn`, `ai-agent`)

## Verifying the artifacts right now

```bash
make export                      # rebuild bundle + zips from git HEAD
git clone exports/portfolio-monorepo.bundle /tmp/check && cd /tmp/check
git log --oneline && git ls-files | wc -l        # -> 1 commit, 121 files
cd project-04-docmind-rag && pip install -r requirements-dev.txt -q && python -m pytest
```

That exact flow was used to verify this package: the clone contains 121 files, branch `main`, and
the DocMind suite passes from the clone after installing its requirements.
