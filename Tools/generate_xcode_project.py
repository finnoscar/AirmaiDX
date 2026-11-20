"""Generate the checked-in native macOS and iOS project without third-party tooling.

Swift sources remain in their existing locations. Explicit native static
framework targets keep Xcode away from the runtime/Prefix trees at repo root.
"""
from pathlib import Path
import hashlib
import json
import xml.etree.ElementTree as ET
from sync_editor_preview import sync_project

ROOT = Path(__file__).resolve().parents[1]


def uid(name):
    return hashlib.sha256(name.encode()).hexdigest()[:24].upper()


def quote(value):
    return json.dumps(str(value), ensure_ascii=False)


def write_if_changed(path, text):
    # Do not provoke Xcode's external-modification dialog for identical output.
    if path.is_file() and path.read_text() == text:
        return
    temporary = path.with_name('.' + path.name + '.generated')
    temporary.write_text(text)
    temporary.replace(path)


def generate():
    editor_inputs = sync_project(ROOT)
    objects = {}

    def obj(key, isa, **fields):
        objects[uid(key)] = {'isa': isa, **fields}
        return uid(key)

    def config_list(key, common, debug=None, release=None):
        configs = []
        for name, extra in [('Debug', debug), ('Release', release)]:
            configs.append(obj(key + name, 'XCBuildConfiguration', name=name,
                               buildSettings={**common, **(extra or {})}))
        return obj(key, 'XCConfigurationList', buildConfigurations=configs,
                   defaultConfigurationIsVisible=0, defaultConfigurationName='Release')

    def files(folder, patterns, compile_sources=False, names=None):
        children, build = [], []
        candidates = (ROOT/folder).iterdir() if names is None else (ROOT/folder/name for name in names)
        paths = sorted(p for p in candidates if p.is_file() and p.suffix in patterns)
        types = {'.swift': 'sourcecode.swift', '.py': 'text.script.python', '.c': 'sourcecode.c.c', '.cs': 'text'}
        for path in paths:
            ref = obj('file:' + str(path.relative_to(ROOT)), 'PBXFileReference',
                      lastKnownFileType=types.get(path.suffix, 'text'), path=path.name, sourceTree='<group>')
            children.append(ref)
            if compile_sources:
                build.append(obj('build:' + str(path.relative_to(ROOT)), 'PBXBuildFile', fileRef=ref))
        return obj('group:' + folder, 'PBXGroup', children=children, path=folder, sourceTree='<group>'), build

    app_group, app_sources = files('Sources/AirmaiDX', {'.swift'}, True)
    core_group, core_sources = files('Sources/AirmaiCore', {'.swift'}, True)
    preview_group, preview_sources = files('Sources/AirmaiEditorPreview', {'.swift'}, True)
    touch_group, touch_sources = files('Sources/AirmaiTouchKit', {'.swift'}, True)
    mobile_core_group, mobile_core_sources = files('Sources/AirmaiMobileCore', {'.swift'}, True)
    mobile_group, mobile_sources = files('Sources/AirmaiDXMobile', {'.swift'}, True)
    generated_group, generated_sources = files('Generated/EditorPreview', {'.swift'}, True,
                                               names=[name for _,name in editor_inputs])
    test_group, test_sources = files('Tests/AirmaiCoreTests', {'.swift'}, True)
    touch_test_group, touch_test_sources = files('Tests/AirmaiTouchKitTests', {'.swift'}, True)
    service_group, _ = files('Service', {'.py'})
    native_group, _ = files('Native', {'.c', '.cs', '.swift'})
    tools_group, _ = files('Tools', {'.py'})
    localized_children = []
    resource_refs = []
    for language in ['zh-Hans', 'en', 'ja']:
        path = f'Sources/AirmaiCore/Resources/{language}.lproj/Localizable.strings'
        if (ROOT / path).is_file():
            localized_children.append(obj('localized:' + language, 'PBXFileReference', name=language,
                lastKnownFileType='text.plist.strings', path=path, sourceTree='SOURCE_ROOT'))
    if localized_children:
        resource_refs.append(obj('localizable-strings', 'PBXVariantGroup', name='Localizable.strings',
            children=localized_children, sourceTree='<group>'))
    for name in ['AquaMaiMetadata.json', 'AquaMaiTranslations.json', 'AquaMai-Documentation-LICENSE.txt', 'AquaMai-Documentation-NOTICE.txt']:
        path = 'Sources/AirmaiCore/Resources/' + name
        if (ROOT / path).is_file():
            resource_refs.append(obj('resource:' + name, 'PBXFileReference', name=name,
                lastKnownFileType='text.json' if name.endswith('.json') else 'text', path=path, sourceTree='SOURCE_ROOT'))
    resources_group = obj('localization-group', 'PBXGroup', name='Localization', children=resource_refs, sourceTree='<group>')
    app_icon = obj('app-icon', 'PBXFileReference', lastKnownFileType='folder.iconcomposer.icon',
                   path='Resources/AppIcon.icon', sourceTree='SOURCE_ROOT')
    extra = [obj('file:' + path, 'PBXFileReference', path=path, sourceTree='<group>',
                 lastKnownFileType='sourcecode.swift' if path.endswith('.swift') else 'net.daringfireball.markdown')
             for path in ['README.md', 'docs/BUILDING.md']]
    app_product = obj('app-product', 'PBXFileReference', explicitFileType='wrapper.application',
                      path='AirmaiDX.app', sourceTree='BUILT_PRODUCTS_DIR', includeInIndex=0)
    mobile_product = obj('mobile-product', 'PBXFileReference', explicitFileType='wrapper.application',
                         path='AirmaiDX Mobile.app', sourceTree='BUILT_PRODUCTS_DIR', includeInIndex=0)
    test_product = obj('test-product', 'PBXFileReference', explicitFileType='wrapper.cfbundle',
                       path='AirmaiDXTests.xctest', sourceTree='BUILT_PRODUCTS_DIR', includeInIndex=0)
    touch_test_product = obj('touch-test-product', 'PBXFileReference', explicitFileType='wrapper.cfbundle',
                             path='AirmaiTouchKitTests.xctest', sourceTree='BUILT_PRODUCTS_DIR', includeInIndex=0)
    module_products = {name:obj(name+'-product', 'PBXFileReference', explicitFileType='wrapper.framework',
                               path=name+'.framework', sourceTree='BUILT_PRODUCTS_DIR', includeInIndex=0)
                       for name in ['AirmaiCore','AirmaiEditorPreview','AirmaiTouchKit','AirmaiMobileCore']}
    mobile_info = obj('mobile-info', 'PBXFileReference', lastKnownFileType='text.plist.xml',
                      path='Info.plist', sourceTree='<group>')
    mobile_entitlements = obj('mobile-entitlements', 'PBXFileReference', lastKnownFileType='text.plist.entitlements',
                              path='AirmaiDXMobile.entitlements', sourceTree='<group>')
    mobile_assets = obj('mobile-assets', 'PBXFileReference', lastKnownFileType='folder.assetcatalog',
                        path='Assets.xcassets', sourceTree='<group>')
    objects[mobile_group]['children'] += [mobile_info, mobile_entitlements, mobile_assets]
    products = obj('products', 'PBXGroup', name='Products', children=[app_product, mobile_product, test_product, touch_test_product, *module_products.values()], sourceTree='<group>')
    root = obj('root', 'PBXGroup', children=[app_group, mobile_group, core_group, resources_group, preview_group,
               touch_group, mobile_core_group, generated_group, test_group, touch_test_group, service_group, native_group, tools_group, app_icon, *extra, products],
               sourceTree='<group>')

    def dependencies(target, names=('AirmaiCore','AirmaiEditorPreview')):
        deps, builds = [], []
        for name in names:
            proxy=obj(target+name+'-proxy','PBXContainerItemProxy',containerPortal=uid('project'),proxyType=1,
                      remoteGlobalIDString=uid(name+'-target'),remoteInfo=name)
            deps.append(obj(target+name+'-dependency','PBXTargetDependency',target=uid(name+'-target'),targetProxy=proxy))
            builds.append(obj(target+name+'link','PBXBuildFile',fileRef=module_products[name]))
        return deps, builds

    app_deps, app_links = dependencies('app')
    test_deps, test_links = dependencies('test')
    mobile_deps, mobile_links = dependencies('mobile', ('AirmaiTouchKit','AirmaiMobileCore'))
    touch_test_deps, touch_test_links = dependencies('touch-test', ('AirmaiTouchKit','AirmaiMobileCore'))
    def resources_phase(target):
        return obj(target+'-localized-resources', 'PBXResourcesBuildPhase', buildActionMask=2147483647,
            files=[obj(target+'-resource:'+ref, 'PBXBuildFile', fileRef=ref) for ref in resource_refs], runOnlyForDeploymentPostprocessing=0)
    app_phases = [
        obj('app-sources', 'PBXSourcesBuildPhase', buildActionMask=2147483647, files=app_sources, runOnlyForDeploymentPostprocessing=0),
        obj('app-frameworks', 'PBXFrameworksBuildPhase', buildActionMask=2147483647, files=app_links, runOnlyForDeploymentPostprocessing=0),
        resources_phase('app'),
        obj('app-resources', 'PBXShellScriptBuildPhase', name='Embed runtime, service and preview assets',
            buildActionMask=2147483647, files=[], inputPaths=[], outputPaths=[],
            alwaysOutOfDate=1, runOnlyForDeploymentPostprocessing=0, shellPath='/bin/sh',
            shellScript='set -eu\n/usr/bin/python3 "$SRCROOT/Tools/prepare_xcode_resources.py"\n')
    ]
    objects[uid('app-localized-resources')]['files'].append(
        obj('app-icon-build', 'PBXBuildFile', fileRef=app_icon))
    test_phases = [
        resources_phase('test'),
        obj('test-sources', 'PBXSourcesBuildPhase', buildActionMask=2147483647, files=test_sources, runOnlyForDeploymentPostprocessing=0),
        obj('test-frameworks', 'PBXFrameworksBuildPhase', buildActionMask=2147483647, files=test_links, runOnlyForDeploymentPostprocessing=0)
    ]
    mobile_phases = [
        obj('mobile-sources', 'PBXSourcesBuildPhase', buildActionMask=2147483647, files=mobile_sources, runOnlyForDeploymentPostprocessing=0),
        obj('mobile-frameworks', 'PBXFrameworksBuildPhase', buildActionMask=2147483647, files=mobile_links, runOnlyForDeploymentPostprocessing=0),
        obj('mobile-resources', 'PBXResourcesBuildPhase', buildActionMask=2147483647,
            files=[obj('mobile-assets-build', 'PBXBuildFile', fileRef=mobile_assets)], runOnlyForDeploymentPostprocessing=0)
    ]
    touch_test_phases = [
        obj('touch-test-sources', 'PBXSourcesBuildPhase', buildActionMask=2147483647, files=touch_test_sources, runOnlyForDeploymentPostprocessing=0),
        obj('touch-test-frameworks', 'PBXFrameworksBuildPhase', buildActionMask=2147483647, files=touch_test_links, runOnlyForDeploymentPostprocessing=0)
    ]
    project_config = config_list('project-config', {
        'MACOSX_DEPLOYMENT_TARGET': '15.0', 'SWIFT_VERSION': '5.0',
        'CLANG_ENABLE_MODULES': 'YES', 'ARCHS': 'arm64', 'ONLY_ACTIVE_ARCH': 'YES',
        'CODE_SIGN_IDENTITY': '-', 'CODE_SIGN_STYLE': 'Manual', 'ENABLE_USER_SCRIPT_SANDBOXING': 'NO',
        'ENABLE_HARDENED_RUNTIME': 'NO', 'ENABLE_APP_SANDBOX': 'NO'
    }, {'SWIFT_OPTIMIZATION_LEVEL': '-Onone', 'DEBUG_INFORMATION_FORMAT': 'dwarf',
        'ENABLE_TESTABILITY': 'YES', 'SWIFT_ACTIVE_COMPILATION_CONDITIONS': 'DEBUG'},
       {'SWIFT_OPTIMIZATION_LEVEL': '-O', 'DEBUG_INFORMATION_FORMAT': 'dwarf-with-dsym'})
    app_config = config_list('app-config', {
        'PRODUCT_NAME': 'AirmaiDX', 'PRODUCT_BUNDLE_IDENTIFIER': 'com.airmai.AirmaiDX',
        'GENERATE_INFOPLIST_FILE': 'YES', 'INFOPLIST_KEY_CFBundleDisplayName': 'AirmaiDX',
        'INFOPLIST_KEY_LSApplicationCategoryType': 'public.app-category.games',
        'INFOPLIST_KEY_NSHumanReadableCopyright': 'AirmaiDX · Local Preview',
        'MARKETING_VERSION': '0.2.14', 'CURRENT_PROJECT_VERSION': '24',
        'ASSETCATALOG_COMPILER_APPICON_NAME': 'AppIcon',
        'AIRMAIDX_RUNTIME_RESOURCES': '$(SRCROOT)/build/AirmaiDX.app/Contents/Resources',
        'LD_RUNPATH_SEARCH_PATHS': ['$(inherited)', '@executable_path/../Frameworks'],
        'COMBINE_HIDPI_IMAGES': 'YES', 'SWIFT_EMIT_LOC_STRINGS': 'YES',
        'INFOPLIST_KEY_NSLocalNetworkUsageDescription': '连接同一网络中的 iPhone 读卡伴侣。',
        'INFOPLIST_KEY_NSBonjourServices': ['_airmai-card._tcp.'],
        'INFOPLIST_KEY_CFBundleLocalizations': ['zh-Hans', 'en', 'ja'],
        'INFOPLIST_KEY_CFBundleDevelopmentRegion': 'zh-Hans', 'SDKROOT': 'macosx'
    })
    test_config = config_list('test-config', {
        'PRODUCT_NAME': '$(TARGET_NAME)', 'PRODUCT_BUNDLE_IDENTIFIER': 'com.airmai.AirmaiDXTests',
        'GENERATE_INFOPLIST_FILE': 'YES', 'LD_RUNPATH_SEARCH_PATHS': ['$(inherited)', '@loader_path/../Frameworks'],
        'TEST_HOST': '', 'BUNDLE_LOADER': '', 'SDKROOT': 'macosx'
    })
    mobile_config = config_list('mobile-config', {
        'PRODUCT_NAME': 'AirmaiDX Mobile', 'PRODUCT_BUNDLE_IDENTIFIER': 'com.airmai.AirmaiDX.mobile',
        'GENERATE_INFOPLIST_FILE': 'NO', 'INFOPLIST_FILE': 'Sources/AirmaiDXMobile/Info.plist',
        'CODE_SIGN_ENTITLEMENTS': 'Sources/AirmaiDXMobile/AirmaiDXMobile.entitlements',
        'CODE_SIGN_STYLE': 'Automatic', 'CODE_SIGN_IDENTITY': '',
        'SDKROOT': 'iphoneos', 'IPHONEOS_DEPLOYMENT_TARGET': '17.0',
        'SUPPORTED_PLATFORMS': ['iphoneos', 'iphonesimulator'], 'TARGETED_DEVICE_FAMILY': '1,2',
        'SUPPORTS_MACCATALYST': 'NO', 'SUPPORTS_MAC_DESIGNED_FOR_IPHONE_IPAD': 'NO',
        'LD_RUNPATH_SEARCH_PATHS': ['$(inherited)', '@executable_path/Frameworks'],
        'SWIFT_EMIT_LOC_STRINGS': 'YES', 'ASSETCATALOG_COMPILER_GENERATE_SWIFT_ASSET_SYMBOL_EXTENSIONS': 'YES'
    })
    touch_test_config = config_list('touch-test-config', {
        'PRODUCT_NAME': '$(TARGET_NAME)', 'PRODUCT_BUNDLE_IDENTIFIER': 'com.airmai.AirmaiTouchKitTests',
        'GENERATE_INFOPLIST_FILE': 'YES', 'SDKROOT': 'macosx',
        'LD_RUNPATH_SEARCH_PATHS': ['$(inherited)', '@loader_path/../Frameworks'], 'TEST_HOST': '', 'BUNDLE_LOADER': ''
    })
    app = obj('app', 'PBXNativeTarget', name='AirmaiDX', productName='AirmaiDX',
              buildConfigurationList=app_config, buildPhases=app_phases, buildRules=[], dependencies=app_deps,
              productReference=app_product, productType='com.apple.product-type.application')
    tests = obj('tests', 'PBXNativeTarget', name='AirmaiDXTests', productName='AirmaiDXTests',
                buildConfigurationList=test_config, buildPhases=test_phases, buildRules=[], dependencies=test_deps,
                productReference=test_product, productType='com.apple.product-type.bundle.unit-test')
    mobile = obj('mobile', 'PBXNativeTarget', name='AirmaiDX iOS', productName='AirmaiDX Mobile',
                 buildConfigurationList=mobile_config, buildPhases=mobile_phases, buildRules=[], dependencies=mobile_deps,
                 productReference=mobile_product, productType='com.apple.product-type.application')
    touch_tests = obj('touch-tests', 'PBXNativeTarget', name='AirmaiTouchKitTests', productName='AirmaiTouchKitTests',
                      buildConfigurationList=touch_test_config, buildPhases=touch_test_phases, buildRules=[], dependencies=touch_test_deps,
                      productReference=touch_test_product, productType='com.apple.product-type.bundle.unit-test')
    modules=[]
    for name, source_files in [('AirmaiCore',core_sources),('AirmaiEditorPreview',preview_sources+generated_sources),
                               ('AirmaiTouchKit',touch_sources),('AirmaiMobileCore',mobile_core_sources)]:
        deps, links = dependencies(name, ('AirmaiCore',) if name=='AirmaiEditorPreview' else ())
        phases=[]
        if name=='AirmaiEditorPreview':
            phases.append(obj('sync-editor','PBXShellScriptBuildPhase', name='Sync original Editor preview sources',
                buildActionMask=2147483647,files=[],runOnlyForDeploymentPostprocessing=0,shellPath='/bin/sh',
                inputPaths=['$(SRCROOT)/Tools/sync_editor_preview.py','$(SRCROOT)/Tools/editor_preview_sources.json',
                            *['$(SRCROOT)/' + str(source.relative_to(ROOT)) for source,_ in editor_inputs]],
                outputPaths=['$(SRCROOT)/Generated/EditorPreview/'+output for _,output in editor_inputs],
                shellScript='set -eu\n/usr/bin/python3 "$SRCROOT/Tools/sync_editor_preview.py" --project\n'))
        phases += [obj(name+'-sources','PBXSourcesBuildPhase',buildActionMask=2147483647,files=source_files,runOnlyForDeploymentPostprocessing=0),
                   obj(name+'-frameworks','PBXFrameworksBuildPhase',buildActionMask=2147483647,files=links,runOnlyForDeploymentPostprocessing=0)]
        settings=dict(PRODUCT_NAME=name,PRODUCT_BUNDLE_IDENTIFIER='com.airmai.'+name,
            GENERATE_INFOPLIST_FILE='YES',DEFINES_MODULE='YES',MACH_O_TYPE='staticlib',SKIP_INSTALL='YES',
            SWIFT_INSTALL_OBJC_HEADER='NO',ENABLE_MODULE_VERIFIER='NO')
        if name in ('AirmaiTouchKit','AirmaiMobileCore'):
            settings.update(SUPPORTED_PLATFORMS=['macosx','iphoneos','iphonesimulator'],
                            IPHONEOS_DEPLOYMENT_TARGET='17.0')
        else:
            settings.update(SDKROOT='macosx')
        config=config_list(name+'-config',settings)
        modules.append(obj(name+'-target','PBXNativeTarget',name=name,productName=name,buildConfigurationList=config,
            buildPhases=phases,buildRules=[],dependencies=deps,productReference=module_products[name],productType='com.apple.product-type.framework'))
    project = obj('project', 'PBXProject', attributes={'BuildIndependentTargetsInParallel': 'YES',
                  'LastUpgradeCheck': '2700', 'TargetAttributes': {app: {'CreatedOnToolsVersion': '27.1'}, mobile: {'CreatedOnToolsVersion': '27.1'}, tests: {'CreatedOnToolsVersion': '27.1'}}},
                  buildConfigurationList=project_config, compatibilityVersion='Xcode 14.0', developmentRegion='zh-Hans',
                  knownRegions=['zh-Hans', 'en', 'ja', 'Base'], mainGroup=root, productRefGroup=products,
                  projectDirPath='', projectRoot='', targets=[app, mobile, tests, touch_tests, *modules])

    def serialize(value, depth=0):
        if isinstance(value, dict):
            indent = '\t' * depth
            return '{\n' + ''.join('\t' * (depth + 1) + quote(k) + ' = ' + serialize(v, depth + 1) + ';\n' for k, v in value.items()) + indent + '}'
        if isinstance(value, list):
            return '(' + ', '.join(serialize(v, depth) for v in value) + (',' if value else '') + ')'
        return str(value) if isinstance(value, int) else quote(value)

    directory = ROOT / 'AirmaiDX.xcodeproj'
    directory.mkdir(exist_ok=True)
    write_if_changed(directory / 'project.pbxproj', '// !$*UTF8*$!\n' + serialize({
        'archiveVersion': 1, 'classes': {}, 'objectVersion': 56, 'objects': objects, 'rootObject': project
    }) + '\n')
    workspace = directory / 'project.xcworkspace'
    workspace.mkdir(exist_ok=True)
    workspace_file = workspace / 'contents.xcworkspacedata'
    if not workspace_file.exists():
        write_if_changed(workspace_file, '<?xml version="1.0" encoding="UTF-8"?>\n<Workspace version="1.0"><FileRef location="self:"/></Workspace>\n')

    scheme = ET.Element('Scheme', LastUpgradeVersion='2700', version='1.3')
    build = ET.SubElement(scheme, 'BuildAction', parallelizeBuildables='YES', buildImplicitDependencies='YES')
    entries = ET.SubElement(build, 'BuildActionEntries')

    def reference(parent, target, name):
        ET.SubElement(parent, 'BuildableReference', BuildableIdentifier='primary', BlueprintIdentifier=target,
                      BuildableName=name, BlueprintName=objects[target]['name'],
                      ReferencedContainer='container:AirmaiDX.xcodeproj')

    entry = ET.SubElement(entries, 'BuildActionEntry', buildForTesting='YES', buildForRunning='YES',
                          buildForProfiling='YES', buildForArchiving='YES', buildForAnalyzing='YES')
    reference(entry, app, 'AirmaiDX.app')
    test = ET.SubElement(scheme, 'TestAction', buildConfiguration='Debug', selectedDebuggerIdentifier='Xcode.DebuggerFoundation.Debugger.LLDB',
                         selectedLauncherIdentifier='Xcode.IDEFoundation.Launcher.LLDB', shouldUseLaunchSchemeArgsEnv='YES')
    testables = ET.SubElement(test, 'Testables')
    reference(ET.SubElement(testables, 'TestableReference', skipped='NO'), tests, 'AirmaiDXTests.xctest')
    launch = ET.SubElement(scheme, 'LaunchAction', buildConfiguration='Debug', selectedDebuggerIdentifier='Xcode.DebuggerFoundation.Debugger.LLDB',
                           selectedLauncherIdentifier='Xcode.IDEFoundation.Launcher.LLDB', launchStyle='0', useCustomWorkingDirectory='NO',
                           ignoresPersistentStateOnLaunch='NO', debugDocumentVersioning='YES', allowLocationSimulation='NO')
    reference(ET.SubElement(launch, 'BuildableProductRunnable', runnableDebuggingMode='0'), app, 'AirmaiDX.app')
    profile = ET.SubElement(scheme, 'ProfileAction', buildConfiguration='Release', shouldUseLaunchSchemeArgsEnv='YES',
                            savedToolIdentifier='', useCustomWorkingDirectory='NO', debugDocumentVersioning='YES')
    reference(ET.SubElement(profile, 'BuildableProductRunnable', runnableDebuggingMode='0'), app, 'AirmaiDX.app')
    ET.SubElement(scheme, 'AnalyzeAction', buildConfiguration='Debug')
    ET.SubElement(scheme, 'ArchiveAction', buildConfiguration='Release', revealArchiveInOrganizer='YES')
    schemes = directory / 'xcshareddata/xcschemes'
    schemes.mkdir(parents=True, exist_ok=True)
    ET.indent(scheme, space='  ')
    legacy_scheme = schemes / 'AirmaiDX.xcscheme'
    if legacy_scheme.exists():
        legacy_scheme.unlink()
    scheme_text = ET.tostring(scheme, encoding='unicode')
    # Keep the exact existing XML declaration so regeneration is a true no-op.
    write_if_changed(schemes / 'AirmaiDX macOS.xcscheme', "<?xml version='1.0' encoding='UTF-8'?>\n" + scheme_text)

    mobile_scheme = ET.Element('Scheme', LastUpgradeVersion='2700', version='1.3')
    mobile_build = ET.SubElement(mobile_scheme, 'BuildAction', parallelizeBuildables='YES', buildImplicitDependencies='YES')
    mobile_entries = ET.SubElement(mobile_build, 'BuildActionEntries')
    mobile_entry = ET.SubElement(mobile_entries, 'BuildActionEntry', buildForTesting='NO', buildForRunning='YES',
                                 buildForProfiling='YES', buildForArchiving='YES', buildForAnalyzing='YES')
    reference(mobile_entry, mobile, 'AirmaiDX Mobile.app')
    mobile_launch = ET.SubElement(mobile_scheme, 'LaunchAction', buildConfiguration='Debug',
        selectedDebuggerIdentifier='Xcode.DebuggerFoundation.Debugger.LLDB',
        selectedLauncherIdentifier='Xcode.IDEFoundation.Launcher.LLDB', launchStyle='0',
        useCustomWorkingDirectory='NO', ignoresPersistentStateOnLaunch='NO', debugDocumentVersioning='YES', allowLocationSimulation='NO')
    reference(ET.SubElement(mobile_launch, 'BuildableProductRunnable', runnableDebuggingMode='0'), mobile, 'AirmaiDX Mobile.app')
    mobile_profile = ET.SubElement(mobile_scheme, 'ProfileAction', buildConfiguration='Release', shouldUseLaunchSchemeArgsEnv='YES',
                                   savedToolIdentifier='', useCustomWorkingDirectory='NO', debugDocumentVersioning='YES')
    reference(ET.SubElement(mobile_profile, 'BuildableProductRunnable', runnableDebuggingMode='0'), mobile, 'AirmaiDX Mobile.app')
    ET.SubElement(mobile_scheme, 'AnalyzeAction', buildConfiguration='Debug')
    ET.SubElement(mobile_scheme, 'ArchiveAction', buildConfiguration='Release', revealArchiveInOrganizer='YES')
    ET.indent(mobile_scheme, space='  ')
    write_if_changed(schemes / 'AirmaiDX iOS.xcscheme', "<?xml version='1.0' encoding='UTF-8'?>\n" + ET.tostring(mobile_scheme, encoding='unicode'))
    print(directory)


if __name__ == '__main__':
    generate()
