from flask import Flask, jsonify, request, send_from_directory, Response
import json
import os
import queue
import threading

app = Flask(__name__, static_folder="web", static_url_path="")


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.post("/api/research")
def research():
    """Backward-compatible synchronous endpoint."""
    payload = request.get_json(silent=True) or {}
    topic = str(payload.get("topic", "")).strip()

    if not topic:
        return jsonify({"error": "Enter a research topic first."}), 400
    if len(topic) > 300:
        return jsonify({"error": "Topic cannot exceed 300 characters."}), 400

    try:
        from evidence_pipeline import run_evidence_pipeline

        result = run_evidence_pipeline(topic)
        return jsonify(result)
    except Exception as error:
        app.logger.exception("Evidence pipeline failed")
        return jsonify({"error": str(error)}), 500


@app.get("/api/research/stream")
def research_stream():
    """Server-Sent Events endpoint streaming real-time pipeline stage transitions and final evidence brief."""
    topic = request.args.get("topic", "").strip()

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


if __name__ == "__main__":
    debug = os.getenv("FLASK_DEBUG", "false").lower() in ("true", "1", "yes")
    app.run(host="127.0.0.1", port=5000, debug=debug)
