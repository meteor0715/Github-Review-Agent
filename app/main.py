from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from app.webhook_handler import router
from app.review_store import get_recent_reviews

app = FastAPI(title="GitHub Review Agent")

app.include_router(router)


@app.get("/ping")
async def ping():
    return {"status": "ok"}


@app.get("/reviews")
async def reviews():
    """JSON endpoint returning the last 10 reviews. Useful for scripting/monitoring."""
    return {"reviews": get_recent_reviews()}


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    """
    Simple HTML dashboard showing the last 10 PR reviews.

    Why plain HTML instead of a React/Vue frontend?
    ------------------------------------------------
    We serve a pre-built HTML string directly from FastAPI.
    No build step, no npm, no separate frontend server.
    For a local monitoring page, this is perfectly sufficient and
    dramatically simpler to maintain.

    In production you'd use templates (Jinja2) or a proper frontend.
    """
    import os
    model = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
    embed_model = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")
    _recent_reviews = get_recent_reviews()

    rows = ""
    if not _recent_reviews:
        rows = '<tr><td colspan="7" style="text-align:center;color:#888">No reviews yet — open a PR on a repo where the GitHub App is installed</td></tr>'
    else:
        for r in _recent_reviews:
            state_icon = {"success": "✅", "failure": "❌", "error": "⚠️", "dry-run": "🔍"}.get(r["state"], "⏳")
            rows += f"""
            <tr>
                <td>{r['timestamp']}</td>
                <td><a href="https://github.com/{r['repo']}" target="_blank">{r['repo']}</a></td>
                <td><a href="https://github.com/{r['repo']}/pull/{r['pr']}" target="_blank">#{r['pr']}</a></td>
                <td>{r['comments']}</td>
                <td>{state_icon} {r['state']}</td>
                <td>{r['model']}</td>
                <td>{r['input_tokens']} / {r['output_tokens']}</td>
            </tr>
            """

    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>AI Review Agent Dashboard</title>
        <meta http-equiv="refresh" content="30">  <!-- auto-refresh every 30s -->
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
                   background: #0d1117; color: #c9d1d9; margin: 0; padding: 24px; }}
            h1   {{ color: #58a6ff; margin-bottom: 4px; }}
            .meta {{ color: #8b949e; font-size: 0.85rem; margin-bottom: 24px; }}
            .card {{ background: #161b22; border: 1px solid #30363d;
                    border-radius: 8px; padding: 20px; margin-bottom: 20px; }}
            .stat {{ display: inline-block; margin-right: 32px; }}
            .stat .val {{ font-size: 2rem; font-weight: bold; color: #58a6ff; }}
            .stat .lbl {{ color: #8b949e; font-size: 0.8rem; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 8px; }}
            th    {{ background: #21262d; color: #8b949e; text-align: left;
                    padding: 8px 12px; font-size: 0.8rem; text-transform: uppercase; }}
            td    {{ padding: 10px 12px; border-top: 1px solid #21262d;
                    font-size: 0.9rem; }}
            tr:hover td {{ background: #1c2128; }}
            a  {{ color: #58a6ff; text-decoration: none; }}
            a:hover {{ text-decoration: underline; }}
            .badge {{ display: inline-block; background: #21262d; border-radius: 4px;
                     padding: 2px 8px; font-size: 0.75rem; }}
        </style>
    </head>
    <body>
        <h1>🤖 AI Review Agent</h1>
        <div class="meta">Model: <span class="badge">{model}</span>
            &nbsp; Embed: <span class="badge">{embed_model}</span>
            &nbsp; Auto-refreshes every 30s
        </div>

        <div class="card">
            <div class="stat">
                <div class="val">{len(_recent_reviews)}</div>
                <div class="lbl">Reviews (session)</div>
            </div>
            <div class="stat">
                <div class="val">{sum(r['comments'] for r in _recent_reviews)}</div>
                <div class="lbl">Comments posted</div>
            </div>
            <div class="stat">
                <div class="val">{sum(1 for r in _recent_reviews if r['state'] == 'failure')}</div>
                <div class="lbl">HIGH issue PRs</div>
            </div>
        </div>

        <div class="card">
            <h2 style="margin-top:0;color:#e6edf3">Last 10 Reviews</h2>
            <table>
                <thead>
                    <tr>
                        <th>Time</th>
                        <th>Repo</th>
                        <th>PR</th>
                        <th>Comments</th>
                        <th>Status</th>
                        <th>Model</th>
                        <th>Tokens (in/out)</th>
                    </tr>
                </thead>
                <tbody>
                    {rows}
                </tbody>
            </table>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html)
