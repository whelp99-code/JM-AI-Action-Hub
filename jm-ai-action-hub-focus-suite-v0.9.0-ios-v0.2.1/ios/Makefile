.PHONY: project check format test parse xcode-build verify

project:
	python3 scripts/generate_xcodeproj.py

check:
	python3 scripts/generate_xcodeproj.py --check
	python3 scripts/verify_openapi_contract.py
	python3 scripts/validate_ios_project.py

format:
	swift-format format --in-place --recursive ActionHubApp ActionHubShareExtension ActionHubWidgetExtension Packages/ActionHubCore/Sources Packages/ActionHubCore/Tests

test:
	swift test --package-path Packages/ActionHubCore

parse:
	find ActionHubApp ActionHubShareExtension ActionHubWidgetExtension Packages/ActionHubCore/Sources Packages/ActionHubCore/Tests -name '*.swift' -print0 | xargs -0 -n1 swiftc -parse

xcode-build:
	xcodebuild -project JM-AI-Action-Hub-iOS.xcodeproj -scheme ActionHubApp -configuration Debug -destination 'generic/platform=iOS Simulator' CODE_SIGNING_ALLOWED=NO build

verify:
	bash scripts/verify_release.sh
