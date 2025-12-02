from flask import Flask, render_template, request, send_file
import os
import shutil
from pathlib import Path
from scrape.your_python_script import process_invoices

app = Flask(__name__)

@app.route("/")
def index():
    return render_template("upload.html")

@app.route("/upload", methods=["POST"])
def upload():
    files = request.files.getlist("files")
    if not files:
        return "No files uploaded", 400

    upload_folder = Path("/tmp/invoice_uploads")
    if upload_folder.exists():
        shutil.rmtree(upload_folder)
    upload_folder.mkdir(parents=True, exist_ok=True)

    saved = []
    for f in files:
        filename = f.filename
        if not filename:
            continue
        dest = upload_folder / filename
        f.save(dest)
        saved.append(str(dest))

    zip_path = process_invoices(saved)

    if not zip_path or not os.path.exists(zip_path):
        return "Processing failed", 500

    return send_file(zip_path, as_attachment=True)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)), debug=False)
