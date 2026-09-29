from flask import Flask, jsonify, request, send_from_directory, Response
import json
import os
import queue
import threading
from supabase_client import save_research_run, get_history, get_history_detail, is_supabase_configured

app = Flask(__name__, static_folder="web", static_url_path="")


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/status")
def status():
    """Return backend status and integration info for frontend client initialization."""
    from supabase_client import SUPABASE_URL, SUPABASE_KEY
    return jsonify({
        "status": "online",
        "supabase_connected": is_supabase_configured(),
        "supabase_url": SUPABASE_URL if is_supabase_configured() else "",
        "supabase_key": SUPABASE_KEY if is_supabase_configured() else "",
        "service": "ResearchMind"
    })


@app.get("/api/history")
def history_list():
    """Fetch list of previous research investigations."""
    user_id = request.args.get("user_id", "").strip() or None
    items = get_history(limit=25, user_id=user_id)
    return jsonify({"history": items, "supabase": is_supabase_configured()})


@app.get("/api/history/<record_id>")
def history_detail(record_id):
    """Fetch complete research brief for a past investigation."""
    detail = get_history_detail(record_id)
    if detail:
        return jsonify(detail)
    return jsonify({"error": "Investigation record not found"}), 404


@app.post("/api/research")
def research():
    """Backward-compatible synchronous endpoint."""
    payload = request.get_json(silent=True) or {}
    topic = str(payload.get("topic", "")).strip()
    user_id = str(payload.get("user_id", "")).strip() or None
    user_email = str(payload.get("user_email", "")).strip() or None

    if not topic:
        return jsonify({"error": "Enter a research topic first."}), 400
    if len(topic) > 300:
        return jsonify({"error": "Topic cannot exceed 300 characters."}), 400

    try:
        from evidence_pipeline import run_evidence_pipeline

        result = run_evidence_pipeline(topic)
        # Asynchronously persist to Supabase
        save_info = save_research_run(result, user_id=user_id, user_email=user_email)
        result["saved_info"] = save_info
        return jsonify(result)
    except Exception as error:
        app.logger.exception("Evidence pipeline failed")
        return jsonify({"error": str(error)}), 500


@app.get("/api/research/stream")
def research_stream():
    """Server-Sent Events endpoint streaming real-time pipeline stage transitions and final evidence brief."""
    topic = request.args.get("topic", "").strip()
    user_id = request.args.get("user_id", "").strip() or None
    user_email = request.args.get("user_email", "").strip() or None

    if not topic:
        return jsonify({"error": "Enter a research topic first."}), 400
    if len(topic) > 300:
        return jsonify({"error": "Topic cannot exceed 300 characters."}), 400

    def generate():
        q = queue.Queue()
        sentinel = object()

        def on_step(stage: str, status: str) -> None:
            q.put(("step", {"stage": stage, "status": status}))

        def run_worker():
            try:
                from evidence_pipeline import run_evidence_pipeline
                result = run_evidence_pipeline(topic, on_step=on_step)
                # Persist to Supabase
                save_info = save_research_run(result, user_id=user_id, user_email=user_email)
                result["saved_info"] = save_info
                q.put(("result", result))
            except Exception as exc:
                app.logger.exception("Evidence streaming pipeline failed")
                q.put(("error", {"error": str(exc)}))
            finally:
                q.put((sentinel, None))

        worker_thread = threading.Thread(target=run_worker, daemon=True)
        worker_thread.start()

        while True:
            try:
                event_name, data = q.get(timeout=15)
                if event_name is sentinel:
                    break
                yield f"event: {event_name}\ndata: {json.dumps(data)}\n\n"
            except queue.Empty:
                yield ": keepalive\n\n"

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
    )


@app.get("/health")
def health():
    """Health check endpoint for container orchestrators and cloud load balancers."""
    return jsonify({
        "status": "healthy",
        "service": "ResearchMind",
        "supabase": is_supabase_configured()
    }), 200


if __name__ == "__main__":
    debug = os.getenv("FLASK_DEBUG", "false").lower() in ("true", "1", "yes")
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", 5000))
    app.run(host=host, port=port, debug=debug)
