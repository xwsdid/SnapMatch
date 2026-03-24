import sys
import json
import requests


def main():
    if len(sys.argv) < 3:
        print("Usage: python test_client.py <image_path> <advice|pose> [url]")
        sys.exit(2)

    image_path = sys.argv[1]
    task = sys.argv[2]
    url = sys.argv[3] if len(sys.argv) >= 4 else "http://127.0.0.1:8000/vlm/infer"

    # Avoid local proxy env (common on dev machines) interfering with localhost calls.
    session = requests.Session()
    session.trust_env = False

    with open(image_path, "rb") as f:
        files = {"file": (image_path, f, "image/jpeg")}
        data = {"task": task}
        # First real model run may take long due to downloading/loading.
        r = session.post(url, files=files, data=data, timeout=1800)

    print("Status:", r.status_code)
    try:
        payload = r.json()
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    except Exception:
        print(r.text)


if __name__ == "__main__":
    main()
