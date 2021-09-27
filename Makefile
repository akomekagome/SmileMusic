.PHONY: ignore obey

ignore:
	git update-index --assume-unchanged .env

obey:
	git update-index --no-assume-unchanged .env