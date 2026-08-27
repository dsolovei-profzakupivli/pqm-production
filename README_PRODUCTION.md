# PQM Production

Production deployment package for Prozorro Qualification Manager.

## Quick start locally

```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
python tools/make_password_hash.py
# configure .env / environment variables
python server.py
```

## Production

Use `render.yaml` and `PRODUCTION_SETUP_UA.md`.
