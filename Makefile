.PHONY: test smoke

test:
	pytest

smoke:
	rm -rf /tmp/aethelgard-smoke
	cp -R demo /tmp/aethelgard-smoke
	cd /tmp/aethelgard-smoke && aethelgard init --profile smoke && aethelgard run && aethelgard status
