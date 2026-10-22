# Teamer — sviluppo e deploy
# Dev locale (Mac): make setup / make dev / make seed / make test
# Release e deploy (LXC): make release / make deploy

APP_HOST ?= 127.0.0.1
APP_PORT ?= 8000
LXC_HOST ?= teamer.lan
LXC_USER ?= root
VERSION  := $(shell python3 -c "import tomllib;print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])")

# chiave di sistema del DB in sviluppo (in produzione /etc/teamer/db.key, vedi teamer-admin)
export TEAMER_DB_KEY_FILE ?= data/dev.key

.PHONY: setup key dev seed test release deploy clean

setup:
	uv sync --group dev

key:
	@test -f $(TEAMER_DB_KEY_FILE) && echo "chiave già presente in $(TEAMER_DB_KEY_FILE)" || \
	  uv run python -c "from app import db; db.write_key(); print('chiave creata in $(TEAMER_DB_KEY_FILE)')"

dev: key
	uv run uvicorn app.main:app --reload --host $(APP_HOST) --port $(APP_PORT)

seed:
	uv run python scripts/seed_demo.py

test:
	uv run pytest -q

release:
	@test -z "$$(git status --porcelain)" || (echo "working tree sporco: commit prima di rilasciare" && exit 1)
	git tag -a v$(VERSION) -m "Release v$(VERSION)"
	git push origin main --tags
	gh release create v$(VERSION) --generate-notes
	@echo "Release v$(VERSION) pubblicata."

deploy:
	ssh $(LXC_USER)@$(LXC_HOST) '/usr/local/bin/teamer-update'

clean:
	rm -rf .venv data/*.db
