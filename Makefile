PLUGIN_DIR ?= $(HOME)/.local/share/xed/plugins

.PHONY: install uninstall test itest

install:
	mkdir -p $(PLUGIN_DIR)
	ln -sfn $(CURDIR)/scratch-tabs/scratch-tabs.plugin $(PLUGIN_DIR)/scratch-tabs.plugin
	ln -sfn $(CURDIR)/scratch-tabs/scratch_tabs $(PLUGIN_DIR)/scratch_tabs

uninstall:
	rm -f $(PLUGIN_DIR)/scratch-tabs.plugin $(PLUGIN_DIR)/scratch_tabs

test:
	PYTHONPATH=scratch-tabs/scratch_tabs python3 -m unittest discover -s tests -t tests -p 'test_store.py'

# Headless end-to-end tests: real xed in an isolated sandbox (see tests/integration/xedsandbox.py)
itest:
	PYTHONPATH=tests/integration python3 -m unittest discover -s tests/integration -t tests/integration -v
