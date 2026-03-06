import os
import uuid
from datetime import datetime, timedelta

import tinify
from flask import Flask, render_template, request, url_for
from werkzeug.utils import secure_filename


app = Flask(__name__)

UPLOAD_DIR = "uploads"
COMPRESSED_DIR = "compressed"
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "avif"}
MAX_COMPRESSIONS_PER_WINDOW = 3
COOLDOWN_MINUTES = 30

rate_limit_state = {}


def ensure_directories() -> None:
	os.makedirs(UPLOAD_DIR, exist_ok=True)
	os.makedirs(COMPRESSED_DIR, exist_ok=True)


def allowed_file(filename: str) -> bool:
	return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def get_client_ip() -> str:
	forwarded_for = request.headers.get("X-Forwarded-For", "")
	if forwarded_for:
		return forwarded_for.split(",")[0].strip()
	return request.remote_addr or "unknown"


def get_rate_limit_status(ip_address: str):
	now = datetime.utcnow()
	state = rate_limit_state.get(ip_address, {"count": 0, "cooldown_until": None})

	cooldown_until = state.get("cooldown_until")
	if cooldown_until and now >= cooldown_until:
		state = {"count": 0, "cooldown_until": None}
		rate_limit_state[ip_address] = state

	cooldown_until = state.get("cooldown_until")
	if cooldown_until and now < cooldown_until:
		seconds_left = int((cooldown_until - now).total_seconds())
		minutes, seconds = divmod(max(seconds_left, 0), 60)
		return {
			"allowed": False,
			"message": f"Rate limit reached for this IP. Try again in {minutes}m {seconds}s.",
		}

	return {"allowed": True, "state": state}


def register_successful_compression(ip_address: str) -> bool:
	now = datetime.utcnow()
	state = rate_limit_state.get(ip_address, {"count": 0, "cooldown_until": None})
	state["count"] += 1

	cooldown_started = False
	if state["count"] >= MAX_COMPRESSIONS_PER_WINDOW:
		state["cooldown_until"] = now + timedelta(minutes=COOLDOWN_MINUTES)
		cooldown_started = True

	rate_limit_state[ip_address] = state
	return cooldown_started


@app.route("/", methods=["GET", "POST"])
def index():
	ensure_directories()

	if request.method == "GET":
		return render_template("index.html")

	ip_address = get_client_ip()
	status = get_rate_limit_status(ip_address)
	if not status["allowed"]:
		return render_template("index.html", error=status["message"])

	uploaded_file = request.files.get("image")
	if not uploaded_file or uploaded_file.filename == "":
		return render_template("index.html", error="Please choose an image file.")

	if not allowed_file(uploaded_file.filename):
		return render_template("index.html", error="Unsupported file type. Use AVIF, WebP, JPG, or PNG.")

	api_key = os.getenv("TINIFY_API_KEY", "").strip()
	if not api_key:
		return render_template(
			"index.html",
			error="TINIFY_API_KEY is not set. Please configure it before compressing images.",
		)

	tinify.key = api_key

	original_filename = secure_filename(uploaded_file.filename)
	extension = original_filename.rsplit(".", 1)[1].lower()
	file_id = uuid.uuid4().hex

	upload_path = os.path.join(UPLOAD_DIR, f"{file_id}_input.{extension}")
	output_path = os.path.join(COMPRESSED_DIR, f"{file_id}_compressed.{extension}")

	try:
		uploaded_file.save(upload_path)
		source = tinify.from_file(upload_path)
		source.to_file(output_path)
	except tinify.AccountError as error:
		return render_template("index.html", error=f"Tinify account error: {error}")
	except tinify.ClientError as error:
		return render_template("index.html", error=f"Invalid image or request: {error}")
	except tinify.ServerError as error:
		return render_template("index.html", error=f"Tinify temporary server error: {error}")
	except tinify.ConnectionError as error:
		return render_template("index.html", error=f"Network error while contacting Tinify: {error}")
	except Exception as error:
		return render_template("index.html", error=f"Unexpected error: {error}")

	original_size = os.path.getsize(upload_path)
	compressed_size = os.path.getsize(output_path)
	reduction = 0
	if original_size > 0:
		reduction = round(((original_size - compressed_size) / original_size) * 100, 2)

	cooldown_started = register_successful_compression(ip_address)
	success_message = "Image compressed successfully."
	if cooldown_started:
		success_message += " You have reached 3 compressions. Cooldown for 30 minutes has started."

	return render_template(
		"index.html",
		success=success_message,
		original_size_kb=round(original_size / 1024, 2),
		compressed_size_kb=round(compressed_size / 1024, 2),
		reduction_percent=reduction,
		download_url=url_for("download", file_name=os.path.basename(output_path)),
	)


@app.route("/download/<path:file_name>")
def download(file_name: str):
	file_path = os.path.join(COMPRESSED_DIR, file_name)
	if not os.path.isfile(file_path):
		return render_template("index.html", error="Compressed file was not found."), 404

	from flask import send_file

	return send_file(file_path, as_attachment=True)


if __name__ == "__main__":
	app.run(debug=True)
