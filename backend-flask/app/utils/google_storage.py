from pathlib import Path, PurePosixPath
from uuid import uuid4

from flask import current_app
from werkzeug.utils import secure_filename

from .google_credentials import load_google_credentials


ALLOWED_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "gif"}
STORAGE_SCOPE = ["https://www.googleapis.com/auth/devstorage.read_write"]


def get_storage_client():
    try:
        from google.cloud import storage
    except ImportError as error:
        raise RuntimeError("google-cloud-storage package is not installed") from error

    credentials = load_google_credentials(current_app.config, STORAGE_SCOPE)
    project_id = current_app.config.get("GOOGLE_CLOUD_PROJECT") or getattr(credentials, "project_id", None)
    return storage.Client(project=project_id, credentials=credentials)


def test_storage_connection():
    bucket_name = current_app.config.get("GOOGLE_CLOUD_STORAGE_BUCKET")
    if not bucket_name:
        raise RuntimeError("GOOGLE_CLOUD_STORAGE_BUCKET is not configured")

    client = get_storage_client()
    bucket = client.bucket(bucket_name)
    object_name = f"connection-tests/{uuid4().hex}.txt"
    blob = bucket.blob(object_name)
    try:
        blob.upload_from_string("ok", content_type="text/plain")
        blob.delete()
    except Exception as error:
        raise RuntimeError(f"Google Cloud Storage bucket upload test failed for {bucket_name}: {error}") from error
    return {"ok": True, "bucket": bucket_name}


def upload_product_image(file_storage, folder=None, sku=None):
    if not file_storage or not file_storage.filename:
        return None

    filename = secure_filename(file_storage.filename)
    extension = Path(filename).suffix.lower().lstrip(".")
    if extension not in ALLOWED_IMAGE_EXTENSIONS:
        raise ValueError("Only jpg, jpeg, png, webp, and gif images are allowed")

    bucket_name = current_app.config.get("GOOGLE_CLOUD_STORAGE_BUCKET")
    if not bucket_name:
        raise RuntimeError("GOOGLE_CLOUD_STORAGE_BUCKET is not configured")

    folder = normalize_storage_folder(folder or current_app.config.get("GOOGLE_CLOUD_STORAGE_PRODUCTS_PREFIX") or "products")
    if sku:
        object_name = build_sku_image_object_name(sku, extension, folder)
    else:
        object_name = join_storage_path(folder, f"{uuid4().hex}-{filename}")
    client = get_storage_client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(object_name)
    blob.upload_from_file(file_storage.stream, content_type=file_storage.mimetype)

    if current_app.config.get("GOOGLE_CLOUD_STORAGE_PUBLIC"):
        blob.make_public()
        return blob.public_url

    return f"gs://{bucket_name}/{object_name}"


def import_product_images_by_sku(products, replace_existing=False):
    bucket_name = current_app.config.get("GOOGLE_CLOUD_STORAGE_BUCKET")
    if not bucket_name:
        raise RuntimeError("GOOGLE_CLOUD_STORAGE_BUCKET is not configured")

    prefix = (current_app.config.get("GOOGLE_CLOUD_STORAGE_PRODUCTS_PREFIX") or "").strip().strip("/")
    list_prefix = f"{prefix}/" if prefix else None
    client = get_storage_client()
    blobs = [
        blob
        for blob in client.list_blobs(bucket_name, prefix=list_prefix)
        if is_image_blob_name(blob.name)
    ]

    result = {"matched": 0, "missing": 0, "skipped": 0}
    for product in products:
        if not product.sku:
            result["skipped"] += 1
            continue
        if product.image_url and not replace_existing:
            result["skipped"] += 1
            continue

        match = find_image_blob_for_sku(product.sku, blobs)
        if not match:
            result["missing"] += 1
            continue

        product.image_url = f"gs://{bucket_name}/{match.name}"
        result["matched"] += 1

    return result


def find_image_blob_for_sku(sku, blobs):
    scored_matches = []
    for blob in blobs:
        score = image_match_score(sku, blob.name)
        if score is not None:
            scored_matches.append((score, blob))
    if not scored_matches:
        return None
    return sorted(scored_matches, key=lambda item: item[0])[0][1]


def image_match_score(sku, blob_name):
    sku_key = normalize_image_match_key(sku)
    if not sku_key:
        return None

    stem = PurePosixPath(blob_name).stem
    stem_key = normalize_image_match_key(stem)
    if not stem_key:
        return None

    if stem_key == sku_key:
        return (0, len(stem_key), blob_name)
    if stem_key.startswith(sku_key):
        return (1, len(stem_key), blob_name)
    if len(sku_key) >= 4 and sku_key in stem_key:
        return (2, stem_key.index(sku_key), len(stem_key), blob_name)
    return None


def is_image_blob_name(blob_name):
    extension = PurePosixPath(blob_name).suffix.lower().lstrip(".")
    return extension in ALLOWED_IMAGE_EXTENSIONS


def normalize_image_match_key(value):
    return "".join(char.lower() for char in str(value or "") if char.isalnum())


def build_sku_image_object_name(sku, extension, folder=None):
    safe_sku = secure_filename(str(sku or "").strip())
    if not safe_sku:
        safe_sku = uuid4().hex
    return join_storage_path(normalize_storage_folder(folder), f"{safe_sku}.{extension}")


def join_storage_path(folder, filename):
    return f"{folder}/{filename}" if folder else filename


def normalize_storage_folder(folder):
    return str(folder or "").strip().strip("/")
