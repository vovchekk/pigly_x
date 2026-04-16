import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

try:
    import winsound
except ImportError:  # pragma: no cover
    winsound = None


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_CODEX_DIR = Path.home() / ".codex"
DEFAULT_STATE_PATH = SCRIPT_DIR / ".codex_completion_notifier_state.json"
DEFAULT_LOG_PATH = SCRIPT_DIR / "codex_completion_notifier.log"


def resolve_default_db_path() -> Path:
    candidates = sorted(
        DEFAULT_CODEX_DIR.glob("logs_*.sqlite"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if candidates:
        return candidates[0]
    return DEFAULT_CODEX_DIR / "logs_1.sqlite"


def load_state(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state), encoding="utf-8")


def append_log(path: Path, message: str) -> None:
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(f"[{timestamp}] {message}\n")


def latest_completed_response_id(db_path: Path) -> int:
    con = sqlite3.connect(str(db_path))
    try:
        cur = con.cursor()
        cur.execute(
            """
            SELECT id, feedback_log_body
            FROM logs
            WHERE feedback_log_body LIKE '%"type":"response.completed"%'
              AND feedback_log_body LIKE '%"status":"completed"%'
            ORDER BY id DESC
            LIMIT 50
            """
        )
        for row_id, body in cur.fetchall():
            if is_final_response_completed(body):
                return int(row_id or 0)
        return 0
    finally:
        con.close()


def is_final_response_completed(body: str) -> bool:
    if not body:
        return False
    payload = extract_json_payload(body)
    try:
        message = json.loads(payload)
    except Exception:
        return False
    if message.get("type") != "response.completed":
        return False
    response = message.get("response") or {}
    for item in response.get("output", []):
        if (
            item.get("type") == "message"
            and item.get("role") == "assistant"
            and item.get("phase") in {"final", "final_answer"}
            and item.get("status") in {None, "completed"}
        ):
            return True
    return False


def extract_json_payload(body: str) -> str:
    markers = (
        'Received message ',
        'websocket event: ',
    )
    for marker in markers:
        if marker in body:
            return body.split(marker, 1)[1].strip()
    json_start = body.find('{"type":"response.completed"')
    if json_start >= 0:
        return body[json_start:].strip()
    return body.strip()


def play_sound(sound_count: int = 2) -> None:
    if winsound is None:
        return
    for _ in range(max(sound_count, 1)):
        winsound.PlaySound("SystemExclamation", winsound.SND_ALIAS)
        time.sleep(0.25)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", default=str(resolve_default_db_path()))
    parser.add_argument("--state-path", default=str(DEFAULT_STATE_PATH))
    parser.add_argument("--log-path", default=str(DEFAULT_LOG_PATH))
    parser.add_argument("--poll-seconds", type=float, default=1.5)
    parser.add_argument("--sound-count", type=int, default=2)
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--test-sound", action="store_true")
    args = parser.parse_args()

    db_path = Path(args.db_path)
    state_path = Path(args.state_path)
    log_path = Path(args.log_path)

    if args.test_sound:
        append_log(log_path, "Manual sound test started.")
        play_sound(args.sound_count)
        append_log(log_path, "Manual sound test finished.")
        return 0

    if not db_path.exists():
        print(f"Codex log database not found: {db_path}", file=sys.stderr)
        append_log(log_path, f"Database not found: {db_path}")
        return 1

    state = {} if args.reset else load_state(state_path)
    last_seen_id = int(state.get("last_seen_id", 0) or 0)

    if last_seen_id <= 0:
        last_seen_id = latest_completed_response_id(db_path)
        save_state(state_path, {"last_seen_id": last_seen_id})
        append_log(log_path, f"Initialized watcher at log row {last_seen_id}.")

    while True:
        try:
            current_id = latest_completed_response_id(db_path)
            if current_id > last_seen_id:
                last_seen_id = current_id
                save_state(state_path, {"last_seen_id": last_seen_id})
                append_log(log_path, f"Detected completed final response at log row {last_seen_id}.")
                play_sound(args.sound_count)
            time.sleep(max(args.poll_seconds, 0.5))
        except KeyboardInterrupt:
            append_log(log_path, "Watcher stopped by keyboard interrupt.")
            return 0
        except Exception as exc:
            append_log(log_path, f"Watcher error: {exc}")
            time.sleep(2.0)


if __name__ == "__main__":
    raise SystemExit(main())
