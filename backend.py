import http.server
import socketserver
import cgi
import requests
import time

PORT = 8000

API_KEY = "YOUR_TINYPNG_API_KEY"

last_request_time = 0
RATE_LIMIT = 600   # 10 minutes

class ImageCompressorHandler(http.server.SimpleHTTPRequestHandler):

    def do_POST(self):

        global last_request_time

        current_time = time.time()

        if current_time - last_request_time < RATE_LIMIT:
            remaining = int(RATE_LIMIT - (current_time - last_request_time))
            self.send_response(429)
            self.end_headers()
            self.wfile.write(f"Rate limit exceeded. Try again in {remaining} seconds.".encode())
            return

        last_request_time = current_time

        form = cgi.FieldStorage(
            fp=self.rfile,
            headers=self.headers,
            environ={'REQUEST_METHOD': 'POST'}
        )

        file_item = form['image']

        if not file_item.file:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"No file uploaded")
            return

        image_data = file_item.file.read()

        response = requests.post(
            "https://api.tinify.com/shrink",
            auth=("api", API_KEY),
            data=image_data
        )

        if response.status_code != 201:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b"Compression failed")
            return

        compressed_url = response.headers["Location"]

        compressed_image = requests.get(compressed_url)

        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.end_headers()
        self.wfile.write(compressed_image.content)


with socketserver.TCPServer(("", PORT), ImageCompressorHandler) as httpd:
    print("Server running on port", PORT)
    httpd.serve_forever()