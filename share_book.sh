#!/bin/bash
set -euo pipefail

#Checks for url, bucket name, and the expiration in seconds
if [ "$#" -lt 3 ]; then
  echo "Usage: $0 <gutenberg-text-url> <bucket-name> <expiration-seconds>" >&2
  echo "Example: $0 https://www.gutenberg.org/cache/epub/1342/pg1342.txt secret-sfx8bt 3600" >&2
  exit 1
fi

URL="$1"
BUCKET="$2"
EXPIRES="$3"

#Keeps the file name from the URL
FILENAME="$(basename "$URL")"
BOOK_PATH="books/$FILENAME"

#Downloads the book into the books/ folder
mkdir -p books
curl -fSL -o "$BOOK_PATH" "$URL"

#Creates the bucket only if it does not already exist
if aws s3 ls "s3://$BUCKET" > /dev/null 2>&1; then
  echo "Bucket s3://$BUCKET already exists."
else
  aws s3 mb "s3://$BUCKET"
fi

#Uploads the book as text so it displays in the browser (public access untouched)
aws s3 cp "$BOOK_PATH" "s3://$BUCKET/$FILENAME" --content-type "text/plain; charset=utf-8"

#Presigns a URL for the book and print it
aws s3 presign "s3://$BUCKET/$FILENAME" --expires-in "$EXPIRES"
