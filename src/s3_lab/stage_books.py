#!/usr/bin/env python3
"""
Download Project Gutenberg books from a list, stage them in a public S3 bucket,
and upload an index page for collaborators.

Usage:
    python3 src/s3_lab/stage_books.py <book_list_path> <index_html_path> <bucket_name>
"""

import json
import logging
import os
import sys
import argparse
import time
import boto3
import requests
from botocore.exceptions import ClientError

#Sets up the logging configuration
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
log = logging.getLogger(__name__)

#Creates one S3 client at the module level shared by all functions
s3 = boto3.client("s3", region_name="us-east-1")

def parse_args():
    """Parses the command line arguments for the book list, index page, and bucket name."""
    parser = argparse.ArgumentParser(
        description = "Stage a book corpus to a public S3 bucket."
    )
    parser.add_argument("list_file", help="Path to the book list file (book_urls.txt)")
    parser.add_argument("index_path", help="Path to the index page file (index.html)")
    parser.add_argument("bucket", help="Name of the S3 bucket (like, public-sfx8bt)")
    
    args = parser.parse_args()
    return args.list_file, args.index_path, args.bucket

def download_books(list_file, dest_dir = "books"):
    """Downloads books from a list of URLs into a local directory"""
    os.makedirs(dest_dir, exist_ok = True)
    file_paths = []
    
    try:
        with open(list_file, "r", encoding = "utf-8") as file:
            urls = [line.strip() for line in file if line.strip()]
    except OSError as e:
        log.error(f"Failed to read book list file {list_file}: {e}")
        return[]
    
    for url in urls:
        #Extracts the file name from the last part of the URL
        filename = url.split("/")[-1]
        dest_path = os.path.join(dest_dir, filename)
        file_paths.append(dest_path)
    
        if os.path.exists(dest_path):
            log.info(f"Skipping, already downloaded: {filename}")
            continue

        try:
            log.info("Downloading {url}...")
            response = requests.get(url, timeout=30)
            response.raise_for_status()  # Raise exception for HTTP errors
            
            with open(dest_path, "wb") as f:
                f.write(response.content)
                
            time.sleep(1)  #Pauses to avoid bombarding Project Gutenberg servers
        except requests.RequestException as e:
            log.error(f"Error downloading {url}: {e}")

    return file_paths


def create_bucket(bucket):
    """Checks if the bucket exists; if it doesn't, then it creates it in us-east-1."""
    try:
        s3.head_bucket(Bucket=bucket)
        log.info(f"Bucket '{bucket}' already exists and is accessible.")
        return True
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code")
        if error_code == "404":
            log.info(f"Bucket '{bucket}' does not exist. Creating...")
            try:
                # Note: us-east-1 does not require LocationConstraint
                s3.create_bucket(Bucket=bucket)
                log.info(f"Successfully created bucket '{bucket}'.")
                return True
            except ClientError as create_err:
                log.error(f"Failed to create bucket '{bucket}': {create_err}")
                return False
        else:
            log.error(f"Error checking bucket '{bucket}': {e}")
            return False


def make_public(bucket):
    """Turns off Block Public Access and applies a public read policy to the bucket."""
    try:
        log.info(f"Disabling Block Public Access for bucket '{bucket}'...")
        s3.put_public_access_block(
            Bucket=bucket,
            PublicAccessBlockConfiguration={
                "BlockPublicAcls": False,
                "IgnorePublicAcls": False,
                "BlockPublicPolicy": False,
                "RestrictPublicBuckets": False,
            },
        )

        policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": "*",
                    "Action": "s3:GetObject",
                    "Resource": f"arn:aws:s3:::{bucket}/*",
                }
            ],
        }

        log.info(f"Applying public bucket policy to '{bucket}'...")
        s3.put_bucket_policy(Bucket=bucket, Policy=json.dumps(policy))
        log.info(f"Bucket '{bucket}' is now publicly readable.")
        return True
    except ClientError as e:
        log.error(f"Failed to make bucket '{bucket}' public: {e}")
        return False


def upload_files(bucket, file_paths):
    """Uploads a list of local files to the top level of the S3 bucket."""
    success_count = 0

    for path in file_paths:
        if not os.path.exists(path):
            log.warning(f"Local file not found, skipping upload: {path}")
            continue

        key = os.path.basename(path)
        try:
            log.info(f"Uploading {path} to s3://{bucket}/{key}...")
            with open(path, "rb") as f:
                s3.upload_fileobj(
                    f,
                    bucket,
                    key,
                    ExtraArgs={"ContentType": "text/plain; charset=utf-8"},
                )
            success_count += 1
        except (ClientError, OSError) as e:
            log.error(f"Failed to upload {path}: {e}")

    return success_count


def upload_index(bucket, index_path):
    """Uploads the index.html file to the S3 bucket."""
    if not os.path.exists(index_path):
        log.error(f"Index file not found at {index_path}")
        return False

    try:
        log.info(f"Uploading index page {index_path} to s3://{bucket}/index.html...")
        with open(index_path, "rb") as f:
            s3.upload_fileobj(
                f,
                bucket,
                "index.html",
                ExtraArgs={"ContentType": "text/html"},
            )
        return True
    except (ClientError, OSError) as e:
        log.error(f"Failed to upload index page: {e}")
        return False


def main():
    """This is the main function that runs to automate this process."""
    list_file, index_path, bucket = parse_args()

    # Step 1: Downloads books locally
    log.info("Starting book downloads...")
    file_paths = download_books(list_file)
    if not file_paths:
        log.error("No books were processed or downloaded.")
        sys.exit(1)

    # Step 2: Creates bucket
    if not create_bucket(bucket):
        log.error("Failed to ensure bucket existence. Exiting.")
        sys.exit(1)

    # Step 3: Makes bucket public
    if not make_public(bucket):
        log.error("Failed to make bucket public. Exiting.")
        sys.exit(1)

    # Step 4: Uploads books
    uploaded_count = upload_files(bucket, file_paths)
    if uploaded_count == 0:
        log.error("No files were successfully uploaded to S3.")
        sys.exit(1)

    # Step 5: Uploads index page
    if not upload_index(bucket, index_path):
        log.error("Failed to upload index page.")
        sys.exit(1)

    #Prints the success output
    public_url = f"https://{bucket}.s3.amazonaws.com/index.html"
    log.info(f"Staging completed successfully! Uploaded {uploaded_count} books.")
    log.info(f"Public web page URL: {public_url}")


if __name__ == "__main__":
    main()
