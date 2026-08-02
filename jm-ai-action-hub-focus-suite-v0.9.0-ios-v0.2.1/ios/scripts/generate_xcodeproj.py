#!/usr/bin/env python3
"""Generate a deterministic Xcode project without third-party tooling."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJ = ROOT / "JM-AI-Action-Hub-iOS.xcodeproj"


def oid(key: str) -> str:
    return hashlib.sha1(key.encode()).hexdigest()[:24].upper()


def q(value: str) -> str:
    escaped = value.replace('\\', '\\\\').replace('"', '\\"')
    return f'"{escaped}"'


class PBX:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[str, list[str]]] = {}

    def add(self, key: str, isa: str, lines: list[str]) -> str:
        ident = oid(key)
        self.objects[ident] = (isa, lines)
        return ident

    def ref(self, ident: str, comment: str) -> str:
        return f"{ident} /* {comment} */"

    def render(self) -> str:
        sections: dict[str, list[tuple[str, list[str]]]] = {}
        for ident, (isa, lines) in self.objects.items():
            sections.setdefault(isa, []).append((ident, lines))
        output = ["// !$*UTF8*$!", "{", "\tarchiveVersion = 1;", "\tclasses = {};", "\tobjectVersion = 56;", "\tobjects = {", ""]
        for isa in sorted(sections):
            output.append(f"/* Begin {isa} section */")
            for ident, lines in sorted(sections[isa]):
                output.append(f"\t\t{ident} = {{")
                output.append(f"\t\t\tisa = {isa};")
                output.extend(f"\t\t\t{line}" for line in lines)
                output.append("\t\t};")
            output.append(f"/* End {isa} section */\n")
        output.extend(["\t};", f"\trootObject = {oid('project')} /* Project object */;", "}"])
        return "\n".join(output) + "\n"


pbx = PBX()

# File references.
source_groups: dict[str, list[str]] = {}
build_files_by_target: dict[str, list[str]] = {"app": [], "share": [], "widget": []}
for target_key, folder in [("app", "ActionHubApp"), ("share", "ActionHubShareExtension"), ("widget", "ActionHubWidgetExtension")]:
    for path in sorted((ROOT / folder).rglob("*.swift")):
        rel = path.relative_to(ROOT).as_posix()
        ref = pbx.add(f"fileref:{rel}", "PBXFileReference", [
            "lastKnownFileType = sourcecode.swift;",
            f"name = {q(path.name)};",
            f"path = {q(rel)};",
            'sourceTree = "<group>";',
        ])
        source_groups.setdefault(folder, []).append(ref)
        build = pbx.add(f"build:{target_key}:{rel}", "PBXBuildFile", [f"fileRef = {pbx.ref(ref, path.name)};"])
        build_files_by_target[target_key].append(build)

assets_rel = "ActionHubApp/Resources/Assets.xcassets"
assets_ref = pbx.add("fileref:assets", "PBXFileReference", [
    "lastKnownFileType = folder.assetcatalog;",
    "name = Assets.xcassets;",
    f"path = {assets_rel};",
    'sourceTree = "<group>";',
])
assets_build = pbx.add("build:assets", "PBXBuildFile", [f"fileRef = {pbx.ref(assets_ref, 'Assets.xcassets')};"])

privacy_rel = "ActionHubApp/Resources/PrivacyInfo.xcprivacy"
privacy_ref = pbx.add("fileref:privacy", "PBXFileReference", [
    "lastKnownFileType = text.xml;",
    "name = PrivacyInfo.xcprivacy;",
    f"path = {privacy_rel};",
    'sourceTree = "<group>";',
])
privacy_build = pbx.add(
    "build:privacy", "PBXBuildFile", [f"fileRef = {pbx.ref(privacy_ref, 'PrivacyInfo.xcprivacy')};"]
)

config_refs = {}
for name in [
    "Shared.xcconfig", "Debug.xcconfig", "Release.xcconfig",
    "ActionHubApp-Info.plist", "ShareExtension-Info.plist", "WidgetExtension-Info.plist",
    "ActionHubApp.entitlements", "ActionHubShareExtension.entitlements", "ActionHubWidgetExtension.entitlements",
]:
    ext = "text.xcconfig" if name.endswith(".xcconfig") else ("text.plist.entitlements" if name.endswith(".entitlements") else "text.plist.xml")
    config_refs[name] = pbx.add(f"fileref:config:{name}", "PBXFileReference", [
        f"lastKnownFileType = {ext};", f"path = {name};", 'sourceTree = "<group>";'
    ])

# Products.
app_product = pbx.add("product:app", "PBXFileReference", ["explicitFileType = wrapper.application;", "includeInIndex = 0;", "path = ActionHubApp.app;", "sourceTree = BUILT_PRODUCTS_DIR;"])
share_product = pbx.add("product:share", "PBXFileReference", ["explicitFileType = wrapper.app-extension;", "includeInIndex = 0;", "path = ActionHubShareExtension.appex;", "sourceTree = BUILT_PRODUCTS_DIR;"])
widget_product = pbx.add("product:widget", "PBXFileReference", ["explicitFileType = wrapper.app-extension;", "includeInIndex = 0;", "path = ActionHubWidgetExtension.appex;", "sourceTree = BUILT_PRODUCTS_DIR;"])

# Local package and products.
package_ref = pbx.add("package:core", "XCLocalSwiftPackageReference", ["relativePath = Packages/ActionHubCore;"])
package_deps = {}
for target in ["app", "share", "widget"]:
    package_deps[target] = pbx.add(f"package-product:{target}", "XCSwiftPackageProductDependency", [
        f"package = {pbx.ref(package_ref, 'XCLocalSwiftPackageReference \"ActionHubCore\"')};",
        "productName = ActionHubCore;",
    ])

framework_phases = {}
for target in ["app", "share", "widget"]:
    package_build = pbx.add(f"package-build:{target}", "PBXBuildFile", [f"productRef = {pbx.ref(package_deps[target], 'ActionHubCore')};"])
    framework_phases[target] = pbx.add(f"frameworks:{target}", "PBXFrameworksBuildPhase", [
        "buildActionMask = 2147483647;",
        "files = (", f"\t{pbx.ref(package_build, 'ActionHubCore in Frameworks')},", ");",
        "runOnlyForDeploymentPostprocessing = 0;",
    ])

# Source and resource phases.
source_phases = {}
for target in ["app", "share", "widget"]:
    entries = [f"\t{pbx.ref(b, 'Swift source in Sources')}," for b in build_files_by_target[target]]
    source_phases[target] = pbx.add(f"sources:{target}", "PBXSourcesBuildPhase", [
        "buildActionMask = 2147483647;", "files = (", *entries, ");", "runOnlyForDeploymentPostprocessing = 0;"
    ])
resources_app = pbx.add("resources:app", "PBXResourcesBuildPhase", [
    "buildActionMask = 2147483647;", "files = (", f"\t{pbx.ref(assets_build, 'Assets.xcassets in Resources')},", f"\t{pbx.ref(privacy_build, 'PrivacyInfo.xcprivacy in Resources')},", ");", "runOnlyForDeploymentPostprocessing = 0;"
])
resources_share = pbx.add("resources:share", "PBXResourcesBuildPhase", ["buildActionMask = 2147483647;", "files = ();", "runOnlyForDeploymentPostprocessing = 0;"])
resources_widget = pbx.add("resources:widget", "PBXResourcesBuildPhase", ["buildActionMask = 2147483647;", "files = ();", "runOnlyForDeploymentPostprocessing = 0;"])

share_embed_build = pbx.add("embed:share", "PBXBuildFile", [f"fileRef = {pbx.ref(share_product, 'ActionHubShareExtension.appex')};", "settings = {ATTRIBUTES = (CodeSignOnCopy, RemoveHeadersOnCopy, ); };"])
widget_embed_build = pbx.add("embed:widget", "PBXBuildFile", [f"fileRef = {pbx.ref(widget_product, 'ActionHubWidgetExtension.appex')};", "settings = {ATTRIBUTES = (CodeSignOnCopy, RemoveHeadersOnCopy, ); };"])
embed_phase = pbx.add("embed:phase", "PBXCopyFilesBuildPhase", [
    "buildActionMask = 2147483647;", "dstPath = \"\";", "dstSubfolderSpec = 13;", "files = (",
    f"\t{pbx.ref(share_embed_build, 'ActionHubShareExtension.appex in Embed App Extensions')},",
    f"\t{pbx.ref(widget_embed_build, 'ActionHubWidgetExtension.appex in Embed App Extensions')},",
    ");", 'name = "Embed App Extensions";', "runOnlyForDeploymentPostprocessing = 0;"
])

# Groups.
def group(key: str, name: str, children: list[tuple[str, str]], path: str | None = None) -> str:
    lines = ["children = ("] + [f"\t{pbx.ref(i, c)}," for i, c in children] + [");", f"name = {q(name)};"]
    if path: lines.append(f"path = {q(path)};")
    lines.append('sourceTree = "<group>";')
    return pbx.add(key, "PBXGroup", lines)

app_group = group("group:app", "ActionHubApp", [(i, Path(next(k for k,v in source_groups.items() if k=='ActionHubApp') if False else '').name) for i in []])
# Replace generated empty group with explicit file children.
pbx.objects[app_group] = ("PBXGroup", ["children = ("] + [f"\t{pbx.ref(i, Path(next(p for p in [str(ROOT)] if p)).name if False else 'Swift source')}," for i in source_groups['ActionHubApp']] + [f"\t{pbx.ref(assets_ref, 'Assets.xcassets')},", f"\t{pbx.ref(privacy_ref, 'PrivacyInfo.xcprivacy')},", ");", "name = ActionHubApp;", 'sourceTree = "<group>";'])
share_group = group("group:share", "ActionHubShareExtension", [(i, "ShareViewController.swift") for i in source_groups['ActionHubShareExtension']])
widget_group = group("group:widget", "ActionHubWidgetExtension", [(i, "ActionHubWidget.swift") for i in source_groups['ActionHubWidgetExtension']])
config_group = group("group:config", "Config", [(i, name) for name, i in config_refs.items()], path="Config")
products_group = group("group:products", "Products", [(app_product, "ActionHubApp.app"), (share_product, "ActionHubShareExtension.appex"), (widget_product, "ActionHubWidgetExtension.appex")])
root_group = group("group:root", "JM-AI-Action-Hub-iOS", [(app_group,"ActionHubApp"),(share_group,"ActionHubShareExtension"),(widget_group,"ActionHubWidgetExtension"),(config_group,"Config"),(products_group,"Products")])

# Dependencies.
project_id = oid("project")
share_proxy = pbx.add("proxy:share", "PBXContainerItemProxy", [f"containerPortal = {pbx.ref(project_id, 'Project object')};", "proxyType = 1;", f"remoteGlobalIDString = {oid('target:share')};", "remoteInfo = ActionHubShareExtension;"])
widget_proxy = pbx.add("proxy:widget", "PBXContainerItemProxy", [f"containerPortal = {pbx.ref(project_id, 'Project object')};", "proxyType = 1;", f"remoteGlobalIDString = {oid('target:widget')};", "remoteInfo = ActionHubWidgetExtension;"])
share_dep = pbx.add("dependency:share", "PBXTargetDependency", [f"target = {oid('target:share')} /* ActionHubShareExtension */;", f"targetProxy = {pbx.ref(share_proxy, 'PBXContainerItemProxy')};"])
widget_dep = pbx.add("dependency:widget", "PBXTargetDependency", [f"target = {oid('target:widget')} /* ActionHubWidgetExtension */;", f"targetProxy = {pbx.ref(widget_proxy, 'PBXContainerItemProxy')};"])

# Build configurations.
def build_config(key: str, name: str, base: str, settings: dict[str, str]) -> str:
    lines = [f"baseConfigurationReference = {pbx.ref(config_refs[base], base)};", "buildSettings = {"]
    for k,v in sorted(settings.items()): lines.append(f"\t{k} = {q(v)};")
    lines += ["};", f"name = {name};"]
    return pbx.add(key, "XCBuildConfiguration", lines)

def config_list(key: str, configs: list[tuple[str,str]]) -> str:
    return pbx.add(key, "XCConfigurationList", ["buildConfigurations = ("] + [f"\t{pbx.ref(i,n)}," for i,n in configs] + [");", "defaultConfigurationIsVisible = 0;", "defaultConfigurationName = Release;"])

project_cfgs=[]
for name in ["Debug","Release"]:
    project_cfgs.append((build_config(f"config:project:{name}",name,f"{name}.xcconfig",{"CLANG_ENABLE_MODULES":"YES","SWIFT_VERSION":"6.0"}),name))
project_list=config_list("configlist:project",project_cfgs)

target_lists={}
settings_map={
 "app":{"PRODUCT_BUNDLE_IDENTIFIER":"$(ACTION_HUB_BUNDLE_PREFIX).ios","INFOPLIST_FILE":"Config/ActionHubApp-Info.plist","CODE_SIGN_ENTITLEMENTS":"Config/ActionHubApp.entitlements","ASSETCATALOG_COMPILER_APPICON_NAME":"AppIcon","TARGETED_DEVICE_FAMILY":"1,2","PRODUCT_NAME":"ActionHubApp","GENERATE_INFOPLIST_FILE":"NO"},
 "share":{"PRODUCT_BUNDLE_IDENTIFIER":"$(ACTION_HUB_BUNDLE_PREFIX).ios.share","INFOPLIST_FILE":"Config/ShareExtension-Info.plist","CODE_SIGN_ENTITLEMENTS":"Config/ActionHubShareExtension.entitlements","APPLICATION_EXTENSION_API_ONLY":"YES","SKIP_INSTALL":"YES","PRODUCT_NAME":"ActionHubShareExtension","GENERATE_INFOPLIST_FILE":"NO"},
 "widget":{"PRODUCT_BUNDLE_IDENTIFIER":"$(ACTION_HUB_BUNDLE_PREFIX).ios.widget","INFOPLIST_FILE":"Config/WidgetExtension-Info.plist","CODE_SIGN_ENTITLEMENTS":"Config/ActionHubWidgetExtension.entitlements","APPLICATION_EXTENSION_API_ONLY":"YES","SKIP_INSTALL":"YES","PRODUCT_NAME":"ActionHubWidgetExtension","GENERATE_INFOPLIST_FILE":"NO"},
}
for target in ["app","share","widget"]:
    configs=[]
    for name in ["Debug","Release"]:
        configs.append((build_config(f"config:{target}:{name}",name,f"{name}.xcconfig",settings_map[target]),name))
    target_lists[target]=config_list(f"configlist:{target}",configs)

# Native targets.
share_target = pbx.add("target:share", "PBXNativeTarget", [
    f"buildConfigurationList = {pbx.ref(target_lists['share'], 'Build configuration list for PBXNativeTarget ActionHubShareExtension')};",
    "buildPhases = (", f"\t{pbx.ref(source_phases['share'],'Sources')},", f"\t{pbx.ref(framework_phases['share'],'Frameworks')},", f"\t{pbx.ref(resources_share,'Resources')},", ");",
    "buildRules = ();", "dependencies = ();", "name = ActionHubShareExtension;", "packageProductDependencies = (", f"\t{pbx.ref(package_deps['share'],'ActionHubCore')},", ");",
    "productName = ActionHubShareExtension;", f"productReference = {pbx.ref(share_product,'ActionHubShareExtension.appex')};", 'productType = "com.apple.product-type.app-extension";'
])
widget_target = pbx.add("target:widget", "PBXNativeTarget", [
    f"buildConfigurationList = {pbx.ref(target_lists['widget'], 'Build configuration list for PBXNativeTarget ActionHubWidgetExtension')};",
    "buildPhases = (", f"\t{pbx.ref(source_phases['widget'],'Sources')},", f"\t{pbx.ref(framework_phases['widget'],'Frameworks')},", f"\t{pbx.ref(resources_widget,'Resources')},", ");",
    "buildRules = ();", "dependencies = ();", "name = ActionHubWidgetExtension;", "packageProductDependencies = (", f"\t{pbx.ref(package_deps['widget'],'ActionHubCore')},", ");",
    "productName = ActionHubWidgetExtension;", f"productReference = {pbx.ref(widget_product,'ActionHubWidgetExtension.appex')};", 'productType = "com.apple.product-type.app-extension";'
])
app_target = pbx.add("target:app", "PBXNativeTarget", [
    f"buildConfigurationList = {pbx.ref(target_lists['app'], 'Build configuration list for PBXNativeTarget ActionHubApp')};",
    "buildPhases = (", f"\t{pbx.ref(source_phases['app'],'Sources')},", f"\t{pbx.ref(framework_phases['app'],'Frameworks')},", f"\t{pbx.ref(resources_app,'Resources')},", f"\t{pbx.ref(embed_phase,'Embed App Extensions')},", ");",
    "buildRules = ();", "dependencies = (", f"\t{pbx.ref(share_dep,'PBXTargetDependency')},", f"\t{pbx.ref(widget_dep,'PBXTargetDependency')},", ");",
    "name = ActionHubApp;", "packageProductDependencies = (", f"\t{pbx.ref(package_deps['app'],'ActionHubCore')},", ");",
    "productName = ActionHubApp;", f"productReference = {pbx.ref(app_product,'ActionHubApp.app')};", 'productType = "com.apple.product-type.application";'
])

pbx.add("project", "PBXProject", [
    "attributes = {", "\tBuildIndependentTargetsInParallel = 1;", "\tLastSwiftUpdateCheck = 1600;", "\tLastUpgradeCheck = 1600;", "\tTargetAttributes = {",
    f"\t\t{app_target} = {{ CreatedOnToolsVersion = 16.0; }};", f"\t\t{share_target} = {{ CreatedOnToolsVersion = 16.0; }};", f"\t\t{widget_target} = {{ CreatedOnToolsVersion = 16.0; }};", "\t};", "};",
    f"buildConfigurationList = {pbx.ref(project_list,'Build configuration list for PBXProject')};", 'compatibilityVersion = "Xcode 14.0";', "developmentRegion = en;", "hasScannedForEncodings = 0;", "knownRegions = (en, Base, ko, );",
    f"mainGroup = {pbx.ref(root_group,'Main Group')};", f"productRefGroup = {pbx.ref(products_group,'Products')};", "projectDirPath = \"\";", "projectRoot = \"\";",
    "packageReferences = (", f"\t{pbx.ref(package_ref,'XCLocalSwiftPackageReference \"ActionHubCore\"')},", ");",
    "targets = (", f"\t{pbx.ref(app_target,'ActionHubApp')},", f"\t{pbx.ref(share_target,'ActionHubShareExtension')},", f"\t{pbx.ref(widget_target,'ActionHubWidgetExtension')},", ");",
])

project_text = pbx.render()
scheme = f'''<?xml version="1.0" encoding="UTF-8"?>
<Scheme LastUpgradeVersion="1600" version="1.7">
  <BuildAction parallelizeBuildables="YES" buildImplicitDependencies="YES">
    <BuildActionEntries><BuildActionEntry buildForTesting="YES" buildForRunning="YES" buildForProfiling="YES" buildForArchiving="YES" buildForAnalyzing="YES">
      <BuildableReference BuildableIdentifier="primary" BlueprintIdentifier="{app_target}" BuildableName="ActionHubApp.app" BlueprintName="ActionHubApp" ReferencedContainer="container:JM-AI-Action-Hub-iOS.xcodeproj"/>
    </BuildActionEntry></BuildActionEntries>
  </BuildAction>
  <TestAction buildConfiguration="Debug" selectedDebuggerIdentifier="Xcode.DebuggerFoundation.Debugger.LLDB" selectedLauncherIdentifier="Xcode.DebuggerFoundation.Launcher.LLDB" shouldUseLaunchSchemeArgsEnv="YES"/>
  <LaunchAction buildConfiguration="Debug" selectedDebuggerIdentifier="Xcode.DebuggerFoundation.Debugger.LLDB" selectedLauncherIdentifier="Xcode.DebuggerFoundation.Launcher.LLDB" launchStyle="0" useCustomWorkingDirectory="NO" ignoresPersistentStateOnLaunch="NO" debugDocumentVersioning="YES" debugServiceExtension="internal" allowLocationSimulation="YES">
    <BuildableProductRunnable runnableDebuggingMode="0"><BuildableReference BuildableIdentifier="primary" BlueprintIdentifier="{app_target}" BuildableName="ActionHubApp.app" BlueprintName="ActionHubApp" ReferencedContainer="container:JM-AI-Action-Hub-iOS.xcodeproj"/></BuildableProductRunnable>
  </LaunchAction>
  <ProfileAction buildConfiguration="Release" shouldUseLaunchSchemeArgsEnv="YES" savedToolIdentifier="" useCustomWorkingDirectory="NO" debugDocumentVersioning="YES"><BuildableProductRunnable runnableDebuggingMode="0"><BuildableReference BuildableIdentifier="primary" BlueprintIdentifier="{app_target}" BuildableName="ActionHubApp.app" BlueprintName="ActionHubApp" ReferencedContainer="container:JM-AI-Action-Hub-iOS.xcodeproj"/></BuildableProductRunnable></ProfileAction>
  <AnalyzeAction buildConfiguration="Debug"/>
  <ArchiveAction buildConfiguration="Release" revealArchiveInOrganizer="YES"/>
</Scheme>
'''


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail if the checked-in project differs from deterministic generation.",
    )
    args = parser.parse_args()
    project_path = PROJ / "project.pbxproj"
    scheme_path = PROJ / "xcshareddata" / "xcschemes" / "ActionHubApp.xcscheme"
    expected = {project_path: project_text, scheme_path: scheme}
    if args.check:
        stale = [str(path.relative_to(ROOT)) for path, content in expected.items() if not path.exists() or path.read_text() != content]
        if stale:
            raise SystemExit("Generated Xcode files are stale: " + ", ".join(stale))
        print("XCODEPROJ_CHECK_OK")
        return

    for path, content in expected.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    print(PROJ)


if __name__ == "__main__":
    main()
