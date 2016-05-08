 .PHONY: deploy

deploy:
	ssh -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no -A $(DEPLOY_TO) "cd ~/boterator && git fetch origin && git reset --hard origin/master && source ../.bashrc && pip3 install -r requirements.txt && make compile_messages"
	ssh -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no -A $(DEPLOY_TO) "touch ~/restart.txt"

DOMAIN = boterator

BASE_DIR = locales

compile_messages:
	@pybabel compile --domain=$(DOMAIN) --directory=$(BASE_DIR)

LANG=en

LOCALE_DIR = $(BASE_DIR)/$(LANG)/LC_MESSAGES
POT_FILE = $(BASE_DIR)/$(DOMAIN).pot
PO_FILE = $(LOCALE_DIR)/$(DOMAIN).po
BABEL_CONFIG = $(BASE_DIR)/babel.cfg

collect_messages:
	@pybabel extract ./ --project=boterator --version=$$(git rev-parse --short HEAD) --output=$(POT_FILE) \
	  --charset=UTF-8 --sort-by-file --mapping=$(BABEL_CONFIG)

build_translation: collect_messages
	@test -f "$(PO_FILE)" \
	  && pybabel update --domain=$(DOMAIN) --input-file=$(POT_FILE) --output-dir=$(BASE_DIR) --locale=$(LANG) --no-wrap \
	  || pybabel init --input-file=$(POT_FILE) --output-dir=$(BASE_DIR) --domain=$(DOMAIN) --locale=$(LANG) --no-wrap

upload_loco: collect_messages
	@curl -s -XPOST -H 'Content-type: text/x-gettext-translation' -H 'Authorization: Loco $(LOCO_KEY)' \
	    --data-binary @locales/boterator.pot https://localise.biz/api/import/pot?index=id > /dev/null

download_loco:
	@curl -s -H 'Authorization: Loco $(LOCO_KEY)' https://localise.biz/api/export/archive/po.zip -o loco.zip
	@unzip loco.zip >/dev/null && rm loco.zip
	@rsync boterator-po-archive/locales/ ./locales/ >/dev/null
	@rm -rf boterator-po-archive

compile_messages_loco: download_loco compile_messages
