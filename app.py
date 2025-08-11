import os
import time

from dotenv import load_dotenv
from flask import Flask, request, flash, redirect, render_template
import boto3
from botocore.exceptions import ClientError

# -----------------------------------------------------------------------------
# Load env and assign config
# -----------------------------------------------------------------------------
load_dotenv()

AWS_REGION       = os.getenv("AWS_DEFAULT_REGION", "ca-central-1")
UPLOAD_BUCKET    = os.getenv("UPLOAD_BUCKET")
PROCESSED_BUCKET = os.getenv("PROCESSED_BUCKET")

if not all([UPLOAD_BUCKET, PROCESSED_BUCKET]):
    raise RuntimeError("UPLOAD_BUCKET and PROCESSED_BUCKET must be set in .env")

# -----------------------------------------------------------------------------
# Initialize Flask + S3
# -----------------------------------------------------------------------------
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY")
if not app.secret_key:
    raise RuntimeError("FLASK_SECRET_KEY must be set in .env")

s3 = boto3.client("s3", region_name=AWS_REGION)

# Polling controls
TIMEOUT_SECONDS = 20
POLL_INTERVAL   = 1

# -----------------------------------------------------------------------------
# Presigned URLs
# -----------------------------------------------------------------------------
def presigned_url(bucket: str, key: str, expires: int = 3600) -> str:
    return s3.generate_presigned_url(
        ClientMethod="get_object",
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=expires,
    )

# -----------------------------------------------------------------------------
# Upload route
# -----------------------------------------------------------------------------
@app.route("/", methods=["GET", "POST"])
def upload_and_show():
    if request.method == "POST":
        # Grab the file from the form
        file = request.files.get("image")
        if not file or not file.filename:
            flash("Please choose an image file to upload")
            return redirect(request.url)

        key = file.filename

        # Upload original to S3
        try:
            s3.upload_fileobj(
                Fileobj=file,
                Bucket=UPLOAD_BUCKET,
                Key=key,
                ExtraArgs={"ContentType": file.content_type},
            )
        except ClientError as e:
            flash(f"Upload failed: {e}")
            return render_template("upload.html")

        # Wait until Lambda has written the greyscale object
        start = time.time()
        while time.time() - start < TIMEOUT_SECONDS:
            try:
                s3.head_object(Bucket=PROCESSED_BUCKET, Key=key)
                break
            except ClientError as e:
                code = e.response["Error"]["Code"]
                if code in ("404", "NoSuchKey"):
                    time.sleep(POLL_INTERVAL)
                    continue
                flash(f"Error checking processed image: {e}")
                return render_template("upload.html")
        else:
            flash("Timed out waiting for greyscale image")
            return render_template("upload.html")

        # Build presigned URLs and render result page
        original_url  = presigned_url(UPLOAD_BUCKET, key)
        processed_url = presigned_url(PROCESSED_BUCKET, key)

        return render_template(
            "result.html",
            original_url=original_url,
            processed_url=processed_url,
        )

    # GET → show upload form
    return render_template("upload.html")


if __name__ == "__main__":
    app.run(debug=True)
