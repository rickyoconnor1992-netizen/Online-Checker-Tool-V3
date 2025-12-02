from flask import Flask, request, render_template, redirect, url_for
import os
from scrape import invoice_checker_V2

app = Flask(__name__)
UPLOAD_FOLDER = os.path.join(os.getcwd(), "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

@app.route("/", methods=["GET", "POST"])
def upload_file():
    if request.method == "POST":
        if "file" not in request.files:
            return "No file part"
        file = request.files["file"]
        if file.filename == "":
            return "No selected file"
        if file and file.filename.lower().endswith((".xls", ".xlsx")):
            filepath = os.path.join(UPLOAD_FOLDER, file.filename)
            file.save(filepath)
            # Run the invoice checker script
            driver = invoice_checker_V2.setup_driver(headless=True)
            try:
                invoice_checker_V2.process_invoice(filepath, driver)
            finally:
                driver.quit()
            return f"✅ Invoice processed: {file.filename}"
        else:
            return "Invalid file type"
    return render_template("upload.html")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
