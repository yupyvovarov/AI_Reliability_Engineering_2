help:
	@echo "Available targets:"
	@echo "  push   - Bump patch version, tag lab2/vX.Y.Z and push to trigger CI"
	@echo "  apply  - Apply Flux source for lab2 directly to cluster"

push:
	@git fetch origin --tags --force
	$(eval TAG=$(shell git tag --list 'lab2/v*' | sort -V | tail -1 | sed 's/^lab2\/v//' | grep . || echo "0.0.0"))
	$(eval MAJOR=$(shell echo $(TAG) | cut -d. -f1))
	$(eval MINOR=$(shell echo $(TAG) | cut -d. -f2))
	$(eval PATCH=$(shell echo $(TAG) | cut -d. -f3))
	$(eval NEW_TAG=lab2/v$(MAJOR).$(MINOR).$(shell echo $$(($(PATCH)+1))))
	@git tag $(NEW_TAG)
	@git push origin lab2/setup $(NEW_TAG)
	@echo "Tagged and pushed $(NEW_TAG)"

apply:
	@kubectl wait --for=condition=Established crd/ocirepositories.source.toolkit.fluxcd.io --timeout=120s
	@kubectl apply --server-side -f flux/lab2-source.yaml
	@echo "Flux lab2 source applied. Watch: flux get sources oci -n flux-system"
