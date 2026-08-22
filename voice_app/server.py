"""Loopback-only HTTP server for the Nihongo Sensei voice tutor."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import sys
import threading
import urllib.error
import urllib.request
import webbrowser
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .controller import ControllerError, TutorController, load_controller


WORKSPACE = Path(__file__).resolve().parents[1]
STATIC_DIR = Path(__file__).resolve().parent / "static"
EXTRACTOR = (
    WORKSPACE
    / ".agents/skills/nihongo-sensei/scripts/build_session.py"
)
CORPUS = WORKSPACE / "work/current-session/corpus.json"
REALTIME_CALLS_URL = "https://api.openai.com/v1/realtime/calls"


class SessionManager:
    """Own the single local tutor session and serialize controller transitions."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._controller: TutorController | None = None
        self._last_refresh: dict[str, Any] | None = None

    @property
    def api_key(self) -> str | None:
        return os.environ.get("OPENAI_API_KEY") or os.environ.get(
            "NIHONGO_SENSEI_API_KEY"
        )

    @property
    def transcription_model(self) -> str:
        return os.environ.get(
            "NIHONGO_TRANSCRIBE_MODEL", "gpt-live-transcribe"
        )

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "app": "Nihongo Sensei Voice Tutor",
                "mode": "realtime-transcription" if self.api_key else "text/mock",
                "api_key_configured": bool(self.api_key),
                "transcription_model": self.transcription_model,
                "controller_state": self._controller.state
                if self._controller
                else "not_started",
                "last_refresh": self._last_refresh,
                "privacy": {
                    "anki_collection_transmitted": False,
                    "realtime_usage": "microphone transcription only when explicitly connected",
                    "prompt_generation": "local deterministic controller only",
                },
            }

    def start(self) -> dict[str, Any]:
        with self._lock:
            if not EXTRACTOR.is_file():
                raise ControllerError(f"Extractor not found: {EXTRACTOR}")
            process = subprocess.run(
                [sys.executable, str(EXTRACTOR)],
                cwd=WORKSPACE,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            if process.returncode != 0:
                detail = (process.stderr or process.stdout).strip()
                raise ControllerError(
                    "Anki refresh failed. Sync and close Anki, then retry. " + detail
                )
            corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
            self._controller = load_controller(corpus)
            metadata = corpus["metadata"]
            self._last_refresh = {
                "generated_at": metadata["generated_at"],
                "source_access": metadata["source_access"],
                "active_card_count": metadata["current_active_card_count"],
                "sentence_pair_count": len(corpus["tutor_policy"]["sentence_pairs"]),
            }
            response = self._controller.start()
            response["refresh"] = self._last_refresh
            response["voice"] = self.voice_status()
            return response

    def answer(self, answer: str) -> dict[str, Any]:
        with self._lock:
            if not self._controller:
                raise ControllerError("Start a session first")
            response = self._controller.submit_answer(answer)
            response["voice"] = self.voice_status()
            return response

    def current(self) -> dict[str, Any]:
        with self._lock:
            if not self._controller:
                raise ControllerError("Start a session first")
            response = self._controller.current()
            response["voice"] = self.voice_status()
            return response

    def voice_status(self) -> dict[str, Any]:
        return {
            "mode": "realtime-transcription" if self.api_key else "text/mock",
            "api_key_configured": bool(self.api_key),
            "transcription_model": self.transcription_model,
            "output_speech": "local browser speech synthesis of controller-approved text",
        }

    def connect_realtime(self, sdp: str) -> tuple[int, str, str]:
        api_key = self.api_key
        if not api_key:
            raise ControllerError(
                "No API key is configured. Text/mock mode remains available."
            )
        if not sdp.startswith("v=0"):
            raise ControllerError("Invalid WebRTC SDP offer")

        session = {
            "type": "transcription",
            "audio": {
                "input": {
                    "transcription": {
                        "model": self.transcription_model,
                    },
                    "noise_reduction": {"type": "near_field"},
                    "turn_detection": {
                        "type": "server_vad",
                        "threshold": 0.5,
                        "prefix_padding_ms": 300,
                        "silence_duration_ms": 650,
                    },
                }
            },
        }
        boundary = "----NihongoSensei" + secrets.token_hex(16)
        body = _multipart_body(
            boundary,
            (
                ("sdp", sdp, "application/sdp"),
                ("session", json.dumps(session), "application/json"),
            ),
        )
        request = urllib.request.Request(
            REALTIME_CALLS_URL,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "OpenAI-Safety-Identifier": "nihongo-sensei-local-user",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                content_type = response.headers.get(
                    "Content-Type", "application/sdp"
                )
                return response.status, content_type, response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise ControllerError(
                f"Realtime connection failed ({exc.code}): {detail[:1000]}"
            ) from exc
        except urllib.error.URLError as exc:
            raise ControllerError(f"Realtime connection failed: {exc.reason}") from exc


def _multipart_body(
    boundary: str, fields: tuple[tuple[str, str, str], ...]
) -> bytes:
    chunks: list[bytes] = []
    for name, value, content_type in fields:
        chunks.extend(
            (
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{name}"\r\n'.encode(),
                f"Content-Type: {content_type}\r\n\r\n".encode(),
                value.encode("utf-8"),
                b"\r\n",
            )
        )
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks)


class LocalRequestHandler(SimpleHTTPRequestHandler):
    manager: SessionManager

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def log_message(self, format: str, *args: Any) -> None:
        sys.stderr.write("[nihongo] " + (format % args) + "\n")

    def end_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; media-src 'self' blob:",
        )
        super().end_headers()

    def do_GET(self) -> None:  # noqa: N802
        if not self._is_local_host():
            self._json_error(HTTPStatus.FORBIDDEN, "Localhost access only")
            return
        if self.path == "/api/status":
            self._json(HTTPStatus.OK, self.manager.status())
            return
        if self.path == "/api/session/current":
            try:
                self._json(HTTPStatus.OK, self.manager.current())
            except ControllerError as exc:
                self._json_error(HTTPStatus.CONFLICT, str(exc))
            return
        super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        if not self._is_local_host():
            self._json_error(HTTPStatus.FORBIDDEN, "Localhost access only")
            return
        try:
            if self.path == "/api/session/start":
                self._require_empty_or_json_body()
                self._json(HTTPStatus.OK, self.manager.start())
            elif self.path == "/api/session/answer":
                payload = self._read_json(max_bytes=16_384)
                answer = payload.get("answer")
                if not isinstance(answer, str):
                    raise ControllerError("answer must be a string")
                self._json(HTTPStatus.OK, self.manager.answer(answer))
            elif self.path == "/api/realtime/connect":
                sdp = self._read_body(max_bytes=1_000_000).decode("utf-8")
                status, content_type, answer = self.manager.connect_realtime(sdp)
                encoded = answer.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)
            else:
                self._json_error(HTTPStatus.NOT_FOUND, "Not found")
        except ControllerError as exc:
            self._json_error(HTTPStatus.BAD_REQUEST, str(exc))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._json_error(HTTPStatus.BAD_REQUEST, "Invalid request body")
        except subprocess.TimeoutExpired:
            self._json_error(HTTPStatus.GATEWAY_TIMEOUT, "Anki refresh timed out")
        except Exception as exc:  # keep local server alive and avoid traceback in UI
            self._json_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

    def _is_local_host(self) -> bool:
        host = self.headers.get("Host", "").split(":", 1)[0].strip("[]").lower()
        return host in {"127.0.0.1", "localhost", "::1"}

    def _read_body(self, max_bytes: int) -> bytes:
        length = int(self.headers.get("Content-Length", "0"))
        if length < 0 or length > max_bytes:
            raise ControllerError("Request body is too large")
        return self.rfile.read(length)

    def _read_json(self, max_bytes: int) -> dict[str, Any]:
        body = self._read_body(max_bytes)
        payload = json.loads(body or b"{}")
        if not isinstance(payload, dict):
            raise ControllerError("JSON body must be an object")
        return payload

    def _require_empty_or_json_body(self) -> None:
        if int(self.headers.get("Content-Length", "0")):
            self._read_json(max_bytes=1024)

    def _json(self, status: HTTPStatus | int, payload: dict[str, Any]) -> None:
        body = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
        self.send_response(int(status))
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json_error(self, status: HTTPStatus | int, message: str) -> None:
        self._json(status, {"error": message})


def create_server(host: str, port: int) -> ThreadingHTTPServer:
    if host not in {"127.0.0.1", "::1", "localhost"}:
        raise ValueError("Nihongo Sensei may bind only to the loopback interface")
    manager = SessionManager()

    class Handler(LocalRequestHandler):
        pass

    Handler.manager = manager
    return ThreadingHTTPServer((host, port), Handler)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Nihongo Sensei locally")
    parser.add_argument("--host", default="127.0.0.1", choices=("127.0.0.1", "::1", "localhost"))
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-open", action="store_true", help="Do not open a browser window")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    server = create_server(args.host, args.port)
    url = f"http://{args.host}:{server.server_address[1]}"
    print(f"Nihongo Sensei is running locally at {url}")
    print("Press Control-C to stop. Anki access remains read-only.")
    if not args.no_open:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Nihongo Sensei.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
