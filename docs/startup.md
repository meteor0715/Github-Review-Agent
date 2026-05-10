## Steps to start the project.

# start smee everytime

smee --url https://smee.io/LncY22VpXNd2BOZF --path /webhook --port 8000

1. to start main app server
   uvicorn app.main:app --reload --port 8000

2. to run locally without starting app server
   python3 local_runner.py --url url
   eg: python3 local_runner.py --url https://github.com/meteor0715/AI-Review_Test/pull/8

3. to run through docker
   (if first time then look in mac test guide milestone 5)
   docker compose down -v -- to stop any running images
   docker compose up --build -d -- to run docker images
   docker compose ps -- for container listing

## Interviewer Demo

One command creates a test PR with deliberate security and quality issues, then runs the full review pipeline on it:

```bash
python demo_pr.py --repo owner/AI-Review_Test --dry-run
```

Remove `--dry-run` to have the bot post real comments on the PR.

See [`demo_pr.py`](demo_pr.py) for full usage.
