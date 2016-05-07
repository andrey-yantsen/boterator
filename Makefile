 .PHONY: deploy

deploy:
	ssh -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no -A $(DEPLOY_TO) "cd ~/boterator && git fetch origin && git reset --hard origin/master && source ../.bashrc && pip3 install -r requirements.txt && make compile_messages"
	ssh -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no -A $(DEPLOY_TO) "touch ~/restart.txt"

DOMAIN = boterator

compile_messages:
	@pybabel compile --domain=$(DOMAIN) --directory=locale/

LANG=en

BASE_DIR = locale
LOCALE_DIR = $(BASE_DIR)/$(LANG)/LC_MESSAGES
POT_FILE = $(BASE_DIR)/$(DOMAIN).pot
PO_FILE = $(LOCALE_DIR)/$(DOMAIN).po
BABEL_CONFIG = $(BASE_DIR)/babel.cfg

collect_messages:
	@pybabel extract ./ --project=boterator --version=$$(git rev-parse --short HEAD) --output=$(POT_FILE) \
	  --charset=UTF-8 --sort-by-file --mapping=$(BABEL_CONFIG)

	@test -f "$(PO_FILE)" \
	  && pybabel update --domain=$(DOMAIN) --input-file=$(POT_FILE) --output-dir=$(BASE_DIR) --locale=$(LANG) --no-wrap \
	  || pybabel init --input-file=$(POT_FILE) --output-dir=$(BASE_DIR) --domain=$(DOMAIN) --locale=$(LANG) --no-wrap
