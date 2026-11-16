# Quickstart · push these projects to `bharrath2412/ai-fullstack-projects`

Everything is committed and tested in this workspace. Two steps from you, no token shared with me.

---

## Step 1 — create an **empty** repo

Open this pre-filled link:

**https://github.com/new?name=ai-fullstack-projects&description=Four%20production-shaped%20projects%3A%20React%2BExpress%20web%20app%2C%20AI%20agent%2C%20ML%20service%2C%20RAG%20app&visibility=public**

Leave **Add a README file**, **Add .gitignore** and **Choose a license** *unchecked* — this repo
already has a README, a `.gitignore` and an MIT license, and an initialised remote would create a
merge conflict on the first push.

Prefer a different name? Any name works, just pass it to the script in step 2.

## Step 2 — push

**With HTTPS** (git asks for username + a personal access token as the password):

```bash
cd /home/user
./scripts/push-to-github.sh
```

**With SSH** (if you have a key added to GitHub):

```bash
cd /home/user
./scripts/push-to-github.sh --ssh
```

**Custom name / different owner:**

```bash
./scripts/push-to-github.sh my-own-name
GITHUB_OWNER=someorg ./scripts/push-to-github.sh --ssh
```

The script checks the working tree is clean, verifies the remote is reachable, and then delegates
to `scripts/push-to-repo.sh`, which pushes as `main` when the remote is empty (or merges if it is
not). It never force-pushes and never deletes branches.

If you have no personal access token yet: **GitHub → Settings → Developer settings → Personal
access tokens → Fine-grained tokens → Generate new token**, scope it to *only* this repository,
permission **Contents: Read and write**, expiry 7 days. Use the token where git asks for a
password. Revoke it afterwards; nothing here stores it.

---

## What will land in the repo

```
README.md                     project index + measured results + how to run everything
PUSH-TO-YOUR-REPO.md          this import guide
Makefile                      make test · make export · make push REPO=<url>
docker-compose.yml            all four services: :8080 :8000 :8100 :8200
.github/workflows/ci.yml      4 parallel CI jobs, no API keys required
LICENSE                       MIT
project-01-taskflow-fullstack/   React+Vite · Express · SQLite · JWT · 10 tests
project-02-agentforge-ai-agent/  FastAPI agent · sandboxed tools · SSE · 57 tests
project-03-churn-ml-service/     sklearn · registry · PSI drift · AUC 0.822 · 40 tests
project-04-docmind-rag/          hybrid RAG · citations · Hit@5 100% · 44 tests
```

First commit: `Four production-shaped projects: full-stack web app, AI agent, ML service, RAG app`.
151 tests pass locally; the CI workflow re-runs all four suites on every push.

## After the first push — 3 minutes of polish

Paste this into the **About** panel (⚙︎ next to About on the repo page):

> Four production-shaped projects: a React + Express full-stack app, a tool-using AI agent, an
> ML churn service and a hybrid RAG application — each with tests, Docker and CI.

Suggested **topics** (click ⚙︎ → Topics):

```
react  express  nodejs  typescript  python  fastapi  scikit-learn  machine-learning
rag  llm  ai-agent  sqlite  docker  rag-pipeline  vector-search  portfolio-project
```

Then confirm CI is green: **Actions** tab → 4 jobs should pass
(`TaskFlow`, `AgentForge`, `Churn ML service`, `DocMind`).

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `Repository not found` | The repo name is wrong, or (private) you are not authenticated for it. |
| `Authentication failed` | HTTPS needs a **token**, not your GitHub password. Or use `--ssh`. |
| `Permission denied (publickey)` | No SSH key on GitHub: `ssh-keygen -t ed25519`, add the `.pub` to GitHub → SSH keys, or use HTTPS. |
| `failed to push some refs` | The remote already has commits (e.g. you let GitHub add a README). Either delete the repo and recreate **empty**, or run `./scripts/push-to-repo.sh https://github.com/bharrath2412/ai-fullstack-projects.git` which merges instead of overwriting. |
| `src refspec main does not match any` | You are in the wrong directory — run the script from `/home/user`. |
| CI fails on `npm ci` | The lockfiles are committed; a failing `npm ci` usually means the remote branch is behind — pull and retry. |
| Want the projects in a subfolder | `cp -r project-0* ~/your-repo/projects/` then commit; see `PUSH-TO-YOUR-REPO.md` Option 3. |

## If you'd rather not use the terminal

Download `exports/portfolio-monorepo.zip` (219 KB) from the workspace, then on GitHub's empty repo
page use **uploading an existing file** → drag the unzipped contents in → commit. For larger trees
that is tedious but it works; the terminal path above is far less error-prone.
