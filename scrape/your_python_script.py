def process_invoices(file_paths):
    # TODO: replace with your real script
    import zipfile, os, time

    out_zip = "/tmp/results.zip"
    with zipfile.ZipFile(out_zip, "w") as z:
        for fp in file_paths:
            z.write(fp, arcname=os.path.basename(fp))
    return out_zip
