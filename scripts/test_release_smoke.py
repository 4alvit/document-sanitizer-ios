"""Small same-run preparation/config controls: inert ZIPs, fake transport, no native work."""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import plistlib
import shutil
import stat
import signal
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
import zipfile

ROOT=Path(__file__).resolve().parents[1]
SMOKE=ROOT/'scripts/release_smoke'

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

def digest(data):return hashlib.sha256(data).hexdigest()
def encoded(value):return json.dumps(value).encode()
def archive(files):
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w',zipfile.ZIP_STORED) as z:
        for name,value in files.items():
            data,mode=value if isinstance(value,tuple) else (value,0o100644)
            row=zipfile.ZipInfo(name);row.create_system=3;row.external_attr=mode<<16
            z.writestr(row,data)
    return output.getvalue()

class HostedPreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='redact-smoke-source-')
        self.root=Path(self.temp.name).resolve();self.repo=self.root/'repo';self.repo.mkdir()
        self.prep=load('smoke_prepare_test',SMOKE/'prepare.py')
        self.window=load('smoke_window_test',SMOKE/'window.py')
        self.config=load('smoke_config_test',SMOKE/'config.py')
        self.scanner=load('verify_release_package',ROOT/'scripts/verify_release_package.py')
        with mock.patch.dict(sys.modules,{'verify_release_package':self.scanner}):
            self.fixtures=load('scanner_fixtures',ROOT/'scripts/test_verify_release_package.py')
        self.head,self.checkout,self.tree='a'*40,'b'*40,'c'*40
        self.gets=0;self.auth_failure=False;self.receipt_failure=False;self.state_failure=False;self.expire_during_auth=False;self.synthetic_time=None;self.diagnostic_writes=[];self.outputs=self.root/'outputs'
        self.scope=self.root/'redact-package-smoke-123-attempt-1'
    def tearDown(self):self.temp.cleanup()

    def inputs(self,fault=None):
        sources={'Tests/UITests/ShareExtensionEntryTests.swift':b'// inert selected source fixture\n',
                 'scripts/verify_release_package.py':(ROOT/'scripts/verify_release_package.py').read_bytes()}
        for name,data in sources.items():
            p=self.repo/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
        source_hashes={n:digest(v) for n,v in sources.items()}
        binary=self.fixtures.thin() if fault=='x86_64_only_binary' else self.fixtures.fat([self.fixtures.thin(),self.fixtures.thin(cpu=0x0100000C)])
        binaries=self.fixtures.bundle_files(binary, extension=self.fixtures.thin(cpu=0x0100000C))
        binary_zip=archive({'CleanSend.app/'+n:v for n,v in binaries.items()})
        scanned=self.root/'inert.zip';scanned.write_bytes(binary_zip)
        scan=self.scanner.scan_package(scanned);self.assertTrue(scan['ok'],scan)
        scans={v+'_'+kind:json.loads(json.dumps(scan)) for v in ('unsigned','adhoc') for kind in ('app','zip')}
        for variant in ('unsigned','adhoc'):
            scans[variant+'_zip']['input']='RedactLeaf-'+variant+'-simulator.zip'
            scans[variant+'_app']['input']='CleanSend.app';scans[variant+'_app']['container']='app'
        if fault=='scanner':scans['adhoc_zip']['binaries'][0]['sha256']='0'*64
        release={
            'RedactLeaf-source.zip':archive({'RedactLeaf-source/'+n:v for n,v in sources.items()}),
            'RedactLeaf-unsigned-simulator.zip':binary_zip,'RedactLeaf-adhoc-simulator.zip':binary_zip,
            'preview-build.json':encoded({'source_commit':self.checkout,'source_tree':self.tree,'configuration':'Release','platform':'iPhoneSimulator','host_architecture':'arm64','xcode':'Xcode 16.4\nBuild version 16F6','app_store_release':False,'provenance':{'published_head':self.head,'published_head_tree':self.tree,'checkout_tree_matches_published_head':True,'github':{'run_id':'123','run_attempt':'1','repository':self.prep.REPO}}}),
            'payload-sha256.json':b'{}','release-binary-scan.json':encoded(scans),'PREVIEW-README.txt':b'Inert source control only.\n'}
        release['SHA256SUMS']=''.join(digest(v)+'  '+n+'\n' for n,v in release.items()).encode()
        if fault=='release_profile':
            preview=json.loads(release['preview-build.json']);preview['host_architecture']='x86_64';release['preview-build.json']=encoded(preview)
            release['SHA256SUMS']=''.join(digest(v)+'  '+n+'\n' for n,v in release.items() if n!='SHA256SUMS').encode()
        original='/producer/Build/Products/Release-iphonesimulator'
        runner_files={'Info.plist':plistlib.dumps({'CFBundleIdentifier':'fixture.runner','MinimumOSVersion':'17.0','DTXcodeBuild':'16F6'}),'CleanSendUITests-Runner':b'runner','PlugIns/CleanSendUITests.xctest/CleanSendUITests':b'test','Frameworks/XCTest.framework/XCTest':b'framework'}
        directories=['.','PlugIns','PlugIns/CleanSendUITests.xctest','Frameworks','Frameworks/XCTest.framework']
        modes={n:{'directory':True,'mode':'0755'} for n in directories}
        for n in runner_files:modes[n]={'directory':False,'mode':'0644' if n=='Info.plist' else '0755'}
        before={'AUT':{'path':original+'/CleanSend.app','files':{}},'runner':{'path':original+'/CleanSendUITests-Runner.app','files':{n:digest(v) for n,v in runner_files.items()}}}
        target={'BlueprintName':'CleanSendUITests','IsUITestBundle':True,'IsXCTRunnerHostedTestBundle':True,'UITargetAppPath':original+'/CleanSend.app','TestHostPath':original+'/CleanSendUITests-Runner.app','TestBundlePath':original+'/CleanSendUITests-Runner.app/PlugIns/CleanSendUITests.xctest','UITargetAppEnvironmentVariables':{},'UITargetAppCommandLineArguments':[],'TestingEnvironmentVariables':{'DYLD_FRAMEWORK_PATH':original,'DYLD_LIBRARY_PATH':original,'__XCODE_BUILT_PRODUCTS_DIR_PATHS':original,'__XPC_DYLD_FRAMEWORK_PATH':original,'__XPC_DYLD_LIBRARY_PATH':original}}
        self.template=plistlib.dumps({'__xctestrun_metadata__':{'FormatVersion':2},'TestConfigurations':[{'TestTargets':[target]}]})
        payloads={}
        for n,v in runner_files.items():payloads['runner/'+n]=(v,stat.S_IFREG|int(modes[n]['mode'],8))
        if fault=='mode':payloads['runner/Frameworks/XCTest.framework/XCTest']=(b'framework',0o100644)
        provenance={'published_head':self.head,'run_id':'123','run_attempt':'1','build_configuration':'Release','host_architecture':'arm64','sdk':'18.5','xcode':'Xcode 16.4\nBuild version 16F6','equal_trees':True,'actual_tree':self.tree,'head_tree':self.tree,'actual_checkout':self.checkout,'source_files':source_hashes}
        metadata={'commands':[{'args':['xcodebuild','-scheme','CleanSendPrivacyRelease','-configuration','Release','ENABLE_TESTABILITY=NO','ARCHS=arm64','ONLY_ACTIVE_ARCH=YES','build-for-testing'],'returncode':0,'owned_group_absent':True}],'source_and_built_payloads_unchanged':True,'device_removed':True,'cleanup':{'shutdown':0,'delete':0},'xcodebuild_returncode':0,'failures':[],'runtime':{'identifier':'com.apple.CoreSimulator.SimRuntime.iOS-18-5'},'device_type':{'identifier':'com.apple.CoreSimulator.SimDeviceType.iPad-Pro-13-inch-M4-16GB'}}
        if fault=='privacy_profile':provenance['host_architecture']='x86_64'
        if fault=='runner_profile':metadata['commands'][0]['args'].remove('ARCHS=arm64');metadata['commands'][0]['args'].append('ARCHS=x86_64')
        privacy={'tested-payloads.zip':archive(payloads),'generated-original.xctestrun':self.template,'selected.xctestrun':self.template,'source-provenance.json':encoded(provenance),'metadata.json':encoded(metadata),'summary.json':encoded({'passedTests':1,'failedTests':0,'skippedTests':0,'totalTestCount':1}),'selected-cases.json':b'{}','invocation.json':b'{}'}
        for when in ('before','after'):
            privacy['payload-'+when+'.json']=encoded(before)
            privacy['payload-node-modes-'+when+'.json']=encoded({'AUT':{},'runner':modes})
        self.zips={11:archive(release),12:archive(privacy)}
        artifacts=[]
        for ident,prefix in ((11,'release-simulator-packages'),(12,'privacy-ipad-evidence')):
            data=self.zips[ident];artifacts.append({'id':ident,'name':prefix+'-123-attempt-1','expired':False,'workflow_run':{'id':123,'head_sha':self.head},'digest':'sha256:'+digest(data),'size_in_bytes':len(data)})
        if fault=='head':artifacts[1]['workflow_run']['head_sha']='f'*40
        self.listing={'total_count':2,'artifacts':artifacts};self.sources=sources

    def execute(self):
        owner=self
        class FakeTransport:
            def __init__(self,*_):self.report={'fake':True}
            @contextlib.contextmanager
            def command(self,kind,limit,cap,argv,env):
                args=argv(limit)
                if kind=='artifact_metadata':data=encoded(owner.listing)
                elif args[1:]==['rev-parse','HEAD']:data=owner.checkout.encode()
                elif args[1:]==['status','--porcelain','--untracked-files=no']:data=b''
                elif args[1:]==['ls-files']:data='\n'.join(owner.sources).encode()
                elif args[1]=='rev-parse':data=owner.tree.encode()
                else:raise AssertionError(args)
                yield io.BytesIO(data)
            def token(self):
                if owner.auth_failure:
                    if owner.expire_during_auth:owner.synthetic_time=clock_anchor+301
                    raise RuntimeError('injected authentication failure')
                return 'inert-token'
            @contextlib.contextmanager
            def zip(self,token,size):
                owner.gets+=1;ident=int(transport.URL.split('/')[-2]);yield io.BytesIO(owner.zips[ident])
        transport=SimpleNamespace(Transport=FakeTransport,GH='/usr/bin/true',CURL='/usr/bin/true',environment=lambda *_:{},URL=None)
        original_clock=self.prep.time.monotonic;clock_anchor=original_clock()
        def controlled_clock():return owner.synthetic_time if owner.synthetic_time is not None else original_clock()
        original_load=self.prep.load;original_admit=self.window.Window.admit
        original_copy=self.window.Window.copy;original_state=self.window.Window.state
        def controlled_state(window):
            if owner.state_failure:raise owner.window.Rejected('fixture-sensitive-state-message')
            return original_state(window)
        def controlled_copy(window,stream,name,*args,**kwargs):
            if owner.receipt_failure and name=='preparation.json':raise owner.window.Rejected('injected receipt capacity failure')
            return original_copy(window,stream,name,*args,**kwargs)
        original_write=os.write
        def observed_write(fd,raw):
            if fd==2:owner.diagnostic_writes.append(raw);return len(raw)
            return original_write(fd,raw)
        def local_load(name,path=None):
            return self.window if name=='window' else transport if name=='transport' else original_load(name,path)
        env={'GITHUB_ACTIONS':'true','RUNNER_OS':'macOS','GITHUB_EVENT_NAME':'pull_request','GITHUB_REPOSITORY':self.prep.REPO,'GITHUB_RUN_ID':'123','GITHUB_RUN_ATTEMPT':'1','EXPECTED_HEAD_SHA':self.head,'GITHUB_SHA':self.checkout,'RUNNER_TEMP':str(self.root),'GITHUB_OUTPUT':str(self.outputs)}
        with mock.patch.object(os,'uname',return_value=SimpleNamespace(machine='arm64')),mock.patch.object(self.prep.time,'monotonic',side_effect=controlled_clock),mock.patch.object(self.window.Window,'state',controlled_state),mock.patch.object(self.window.Window,'copy',controlled_copy),mock.patch.object(os,'write',side_effect=observed_write),mock.patch.dict(os.environ,env),mock.patch.object(self.prep,'ROOT',self.repo),mock.patch.object(self.prep,'load',side_effect=local_load),mock.patch.object(self.window.Window,'admit',side_effect=lambda scope,started:original_admit(scope,started=started,clock=controlled_clock,disk_usage=lambda _:SimpleNamespace(free=100*2**30))),mock.patch.object(shutil,'disk_usage',return_value=SimpleNamespace(free=100*2**30)):
            try:self.prep.main()
            except SystemExit as error:self.assertEqual(error.code,1)
        receipt=self.scope/'preparation.json'
        return json.loads(receipt.read_bytes()) if receipt.exists() else {'status':'missing_receipt'}

    def test_mixed_producer_profiles_are_rejected_by_actual_preparation(self):
        for fault in ('privacy_profile','release_profile','runner_profile','x86_64_only_binary'):
            with self.subTest(fault=fault):
                self.inputs(fault);report=self.execute();self.assertEqual(report['status'],'failed',report)
                self.assertFalse((self.scope/'context.json').exists())
                shutil.rmtree(self.scope)

    def test_non_arm_consumer_is_rejected_before_preparation(self):
        with mock.patch.dict(os.environ,{'GITHUB_ACTIONS':'true','RUNNER_OS':'macOS'}),mock.patch.object(os,'uname',return_value=SimpleNamespace(machine='x86_64')),mock.patch.object(self.prep,'load',side_effect=AssertionError('no transport')):
            with self.assertRaisesRegex(AssertionError,'ARM host profile'):self.prep.main()
        native=load('profile_smoke_native',SMOKE/'run.py')
        with mock.patch.dict(os.environ,{'GITHUB_ACTIONS':'true','GITHUB_EVENT_NAME':'pull_request'}),mock.patch.object(os,'uname',return_value=SimpleNamespace(machine='x86_64')):
            with self.assertRaisesRegex(AssertionError,'ARM host profile'):native.validate_grant(self.root/'absent-context.json')

    def test_real_preparation_and_rebound_config(self):
        self.inputs();report=self.execute();self.assertEqual(report['status'],'prepared',report);self.assertEqual(self.gets,2)
        binding=json.loads((self.scope/'runner-binding.json').read_bytes())
        self.assertIn('Frameworks/XCTest.framework',binding['runner_entries'])
        app=self.root/'installed/CleanSend.app';(app/'PlugIns/CleanSendShare.appex').mkdir(parents=True)
        dev=self.root/'Developer';framework=dev/'Platforms/iPhoneSimulator.platform/Developer/Library/Frameworks/XCTest.framework';framework.mkdir(parents=True);(framework/'XCTest').write_bytes(b'fixture')
        (dev/'Platforms/iPhoneSimulator.platform/Developer/usr/lib').mkdir(parents=True)
        output=self.root/'config'
        self.config.prepare(app,dev,output,self.scope/'runner-binding.json',self.scope/'privacy-inputs/generated-original.xctestrun',self.head,self.tree)
        raw=(output/'exact-package-share.xctestrun').read_bytes();target=plistlib.loads(raw)['TestConfigurations'][0]['TestTargets'][0]
        self.assertEqual(target['OnlyTestIdentifiers'],[self.config.CASE]);self.assertEqual(target['UITargetAppEnvironmentVariables'],{})
        self.assertNotIn(b'/producer',raw);self.assertEqual(target['MaximumTestExecutionTimeAllowance'],240)
        selected=Path(binding['selected_test_source_path']);selected.write_bytes(b'changed')
        with self.assertRaises(AssertionError):self.config.verify_runner(binding)
    def configured_fixture(self,change=None):
        self.inputs()
        raw=(ROOT/'scripts/fixtures/release-ui-template.xctestrun').read_bytes()
        self.assertEqual(digest(raw),'77b44d732bf2ccee2242edf444ca9ef02eec560f62c820a3cd83506ecd912acb')
        template=plistlib.loads(raw)
        if change:change(template['TestConfigurations'][0]['TestTargets'][0])
        # The control uses the exact observed template shape, with only public
        # placeholders; artifact paths and binaries remain inert local fixtures.
        raw=plistlib.dumps(template)
        with zipfile.ZipFile(io.BytesIO(self.zips[12])) as z:
            files={row.filename:z.read(row) for row in z.infolist()}
        files['generated-original.xctestrun']=raw
        self.zips[12]=archive(files)
        row=self.listing['artifacts'][1];row.update(size_in_bytes=len(self.zips[12]),digest='sha256:'+digest(self.zips[12]))
        self.assertEqual(self.execute()['status'],'prepared')
        app=self.root/'installed/CleanSend.app';(app/'PlugIns/CleanSendShare.appex').mkdir(parents=True)
        dev=self.root/'Developer';framework=dev/'Platforms/iPhoneSimulator.platform/Developer/Library/Frameworks/XCTest.framework';framework.mkdir(parents=True);(framework/'XCTest').write_bytes(b'fixture')
        (dev/'Platforms/iPhoneSimulator.platform/Developer/usr/lib').mkdir(parents=True)
        return app,dev

    def test_observed_generated_AUT_environment_is_validated_and_fully_removed(self):
        app,dev=self.configured_fixture();state={};out=self.root/'config'
        receipt=self.config.prepare(app,dev,out,self.scope/'runner-binding.json',self.scope/'privacy-inputs/generated-original.xctestrun',self.head,self.tree,state)
        encoded=(out/'exact-package-share.xctestrun').read_bytes();target=plistlib.loads(encoded)['TestConfigurations'][0]['TestTargets'][0]
        self.assertEqual(target['UITargetAppEnvironmentVariables'],{});self.assertEqual(target['UITargetAppCommandLineArguments'],[])
        self.assertEqual(target['OnlyTestIdentifiers'],[self.config.CASE]);self.assertEqual(state['stage'],'prepared')
        self.assertEqual(len(receipt['target_changes']['UITargetAppEnvironmentVariables']['before']),8)
        for unwanted in (b'/producer',b'__TESTROOT__',b'Debug-iphonesimulator',b'storekit',b'commerce'):
            self.assertNotIn(unwanted,encoded.lower() if unwanted in (b'storekit',b'commerce') else encoded)

    def test_unknown_or_value_changed_AUT_environment_fails_with_safe_stage(self):
        app,dev=self.configured_fixture();original=(self.scope/'privacy-inputs/generated-original.xctestrun').read_bytes()
        binding_path=self.scope/'runner-binding.json';binding=json.loads(binding_path.read_bytes())
        run=load('smoke_failure_frames',SMOKE/'run.py')
        for key,value in [('UNEXPECTED_SEED','sensitive-fixture-value'),('APP_DISTRIBUTOR_ID_OVERRIDE','unexpected'),('DYLD_LIBRARY_PATH','/wrong/products')]:
            with self.subTest(key=key):
                data=plistlib.loads(original);data['TestConfigurations'][0]['TestTargets'][0]['UITargetAppEnvironmentVariables'][key]=value;raw=plistlib.dumps(data)
                template=self.root/(key+'.xctestrun');template.write_bytes(raw);binding['template_sha256']=digest(raw);binding_path.write_text(json.dumps(binding));state={};out=self.root/('out-'+key)
                try:self.config.prepare(app,dev,out,binding_path,template,self.head,self.tree,state)
                except AssertionError as error:failure=run.failure_detail(error)
                else:self.fail('unexpected AUT environment accepted')
                self.assertEqual(state['stage'],'AUT_environment');self.assertFalse(out.exists())
                self.assertEqual(failure['type'],'AssertionError');self.assertTrue(any(row['file']=='config.py' and row['function']=='prepare' for row in failure['frames']))
                self.assertNotIn(value,json.dumps(failure));self.assertNotIn(str(self.root),json.dumps(failure))

    def test_commerce_and_template_integrity_guards_remain_strict(self):
        app,dev=self.configured_fixture(lambda target:target.update(StoreKitConfigurationFilePath='fixture.storekit'))
        state={};out=self.root/'config';binding=self.scope/'runner-binding.json';template=self.scope/'privacy-inputs/generated-original.xctestrun'
        with self.assertRaises(AssertionError):self.config.prepare(app,dev,out,binding,template,self.head,self.tree,state)
        self.assertEqual(state['stage'],'final_template_guards');self.assertFalse(out.exists())
        template.write_bytes(template.read_bytes()+b' ');state={}
        with self.assertRaises(AssertionError):self.config.prepare(app,dev,out,binding,template,self.head,self.tree,state)
        self.assertEqual(state['stage'],'immutable_binding');self.assertFalse(out.exists())

    def test_new_compiled_test_bundle_and_prebuilt_carrier_have_distinct_provenance(self):
        runner=self.root/'carrier/CleanSendUITests-Runner.app';unit=runner/'PlugIns/CleanSendUITests.xctest';unit.mkdir(parents=True)
        developer=self.root/'Developer';template=developer/'Platforms/iPhoneSimulator.platform/Developer/Library/Xcode/Agents/XCTRunner.app/Info.plist';template.parent.mkdir(parents=True)
        carrier_info={'CFBundleIdentifier':'io.github.4alvit.cleansend.uitests.xctrunner','MinimumOSVersion':'13.0','DTXcodeBuild':'16F1t','DTSDKName':'iphonesimulator18.4.internal','DTSDKBuild':'22E169','DTPlatformName':'iphonesimulator','DTPlatformVersion':'18.4','DTPlatformBuild':'22E169'}
        unit_info={'CFBundleIdentifier':'io.github.4alvit.cleansend.uitests','MinimumOSVersion':'17.0','DTXcodeBuild':'16F6','DTSDKName':'iphonesimulator18.5','DTPlatformName':'iphonesimulator'}
        context={'host_architecture':'arm64','head':self.head,'tree':self.tree,'checkout':self.checkout,'run':'123','attempt':'1','xcode_build':'16F6','runtime_version':'18.5'}
        producer={k:context[k]for k in ('host_architecture','head','tree','checkout','run','attempt')};producer.update(configuration='Release',xcode='Xcode 16.4\nBuild version 16F6',sdk='18.5')
        binding={'runner':str(runner),'producer':producer,'runner_entries':{}}
        def write_infos():
            for name,value in [('Info.plist',carrier_info),('PlugIns/CleanSendUITests.xctest/Info.plist',unit_info)]:
                raw=plistlib.dumps(value);(runner/name).write_bytes(raw);binding['runner_entries'][name]={'sha256':digest(raw)}
        write_infos();template.write_bytes(plistlib.dumps(carrier_info));checks=[]
        result=self.config.runner_toolchain(binding,developer,context,lambda:checks.append(True))
        self.assertTrue(result['carrier_matches_selected_Xcode_template']);self.assertEqual(result['test_bundle_Info']['DTXcodeBuild'],'16F6');self.assertEqual(result['carrier_metadata']['DTXcodeBuild'],'16F1t');self.assertGreater(len(checks),3)
        producer['sdk']='18.4'
        with self.assertRaises(AssertionError):self.config.runner_toolchain(binding,developer,context,lambda:None)
        producer['sdk']='18.5';unit_info['DTXcodeBuild']='16F1t';write_infos()
        with self.assertRaises(AssertionError):self.config.runner_toolchain(binding,developer,context,lambda:None)
        unit_info['DTXcodeBuild']='16F6';unit_info['DTSDKName']='iphonesimulator18.4';write_infos()
        with self.assertRaises(AssertionError):self.config.runner_toolchain(binding,developer,context,lambda:None)
        unit_info['DTSDKName']='iphonesimulator18.5';write_infos();wrong=dict(carrier_info,DTXcodeBuild='wrong');template.write_bytes(plistlib.dumps(wrong))
        with self.assertRaises(AssertionError):self.config.runner_toolchain(binding,developer,context,lambda:None)

    def test_native_command_uses_original_remaining_work_after_preflight(self):
        lifecycle=load('smoke_lifecycle_test',SMOKE/'lifecycle.py')
        lifecycle.OUT=self.root
        for elapsed,expected in ((70,300),(550,6),(557,None)):
            with self.subTest(elapsed=elapsed):
                process=SimpleNamespace(pid=123,returncode=0,wait=mock.Mock())
                with mock.patch.object(lifecycle.time,'monotonic',return_value=elapsed),mock.patch.object(lifecycle.subprocess,'Popen',return_value=process) as spawn,mock.patch.object(lifecycle,'stop_group',side_effect=lambda proc,row:row.update(owned_group_absent=True)):
                    run=lifecycle.Run();run.start=0;run.persist=mock.Mock()
                    if expected is None:
                        with self.assertRaises(TimeoutError):run.command(['fixture'],str(elapsed)+'.log',300)
                        spawn.assert_not_called()
                    else:
                        run.command(['fixture'],str(elapsed)+'.log',300)
                        process.wait.assert_called_once_with(timeout=expected)
                        self.assertTrue(run.meta['commands'][0]['owned_group_absent'])

    def test_lifecycle_rechecks_persistence_and_log_open_before_spawn(self):
        for stage in ('persist','open'):
            with self.subTest(stage=stage):
                lifecycle=load('late_package_lifecycle',SMOKE/'lifecycle.py');lifecycle.OUT=self.root
                clock=[550.0];original_open=Path.open
                with mock.patch.object(lifecycle.time,'monotonic',side_effect=lambda:clock[0]):
                    run=lifecycle.Run();run.start=0
                    def persist():
                        if stage=='persist':clock[0]=556
                    run.persist=persist
                    def opened(path,*args,**kwargs):
                        stream=original_open(path,*args,**kwargs)
                        if stage=='open':clock[0]=556
                        return stream
                    with mock.patch.object(Path,'open',opened),mock.patch.object(subprocess,'Popen') as spawn:
                        with self.assertRaises(TimeoutError):run.command(['fixture'],stage+'.log',300)
                    spawn.assert_not_called();self.assertEqual(run.start,0);self.assertEqual(run.end,560)
    def test_lifecycle_post_spawn_work_consumes_single_original_command_end(self):
        lifecycle=load('post_spawn_package_lifecycle',SMOKE/'lifecycle.py');lifecycle.OUT=self.root
        clock=[0.0];calls=[];proc=SimpleNamespace(pid=123,returncode=0,wait=mock.Mock())
        with mock.patch.object(lifecycle.time,'monotonic',side_effect=lambda:clock[0]):
            run=lifecycle.Run();run.start=0
            def persist():
                calls.append(1)
                if len(calls)==2:clock[0]+=10
            run.persist=persist
            with mock.patch.object(subprocess,'Popen',return_value=proc),mock.patch.object(lifecycle,'stop_group',side_effect=lambda p,row:row.update(owned_group_absent=True)):
                run.command(['fixture'],'post-spawn.log',15)
        proc.wait.assert_called_once_with(timeout=5)
        self.assertEqual(run.meta['commands'][0]['command_deadline_monotonic'],15)
        self.assertTrue(run.meta['commands'][0]['owned_group_absent'])

    def test_supervisor_timeout_stops_only_identity_bound_child_group(self):
        for correct_parent in (True,False):
            with self.subTest(correct_parent=correct_parent):
                run=load('smoke_run_timeout_test',SMOKE/'run.py')
                lifecycle=load('smoke_lifecycle_timeout_test',SMOKE/'lifecycle.py')
                scope=self.root/('native-owned' if correct_parent else 'native-foreign')
                run.SCOPE=scope;run.OWNED_ROOT=self.root
                context=self.root/('context-owned.json' if correct_parent else 'context-foreign.json');context.write_bytes(b'{}')
                process=SimpleNamespace(pid=500,returncode=None)
                process.poll=lambda:process.returncode
                process.wait=lambda **_:process.returncode
                signals=[];child_present=[True]
                def killpg(pid,sig):
                    signals.append((pid,sig))
                    if pid==700 and sig==0 and not child_present[0]:raise ProcessLookupError()
                    if pid==700 and sig==signal.SIGKILL:child_present[0]=False
                    if pid==500 and sig==signal.SIGKILL:process.returncode=-9
                def spawn(*args,**kwargs):
                    (scope/'metadata.json').write_text(json.dumps({'owner_worker_pid':500,'owned_device_name':'fixture-owned-device','commands':[{'owned_process_group':700,'args':['xcodebuild'],'owned_group_absent':False}]}))
                    return process
                aggregate=run.aggregate_command_groups
                with mock.patch.object(run,'load',return_value=lifecycle),mock.patch.object(subprocess,'Popen',side_effect=spawn),mock.patch.object(run.Resources,'check',side_effect=AssertionError('injected allocation floor')),mock.patch.object(run,'await_cleanup_ack',side_effect=subprocess.TimeoutExpired('fixture-worker',3)),mock.patch.object(subprocess,'check_output',return_value='500\n' if correct_parent else '999\n') as parent_lookup,mock.patch.object(os,'getpgid',return_value=700),mock.patch.object(os,'killpg',side_effect=killpg),mock.patch.object(lifecycle,'stop_group',side_effect=lambda proc,row:row.update(owned_group_absent=True)),mock.patch.object(run,'aggregate_command_groups',side_effect=lambda meta,start:aggregate(meta,start,probe=killpg)),mock.patch.object(run,'terminal_stdout',return_value=True):
                    self.assertEqual(run.supervise(context,{}),1)
                receipt=json.loads((scope/'invocation-final.json').read_bytes())
                self.assertNotIn('last_resort_error',receipt)
                self.assertEqual(parent_lookup.call_args.args[0],['ps','-p','700','-o','ppid='])
                expected='signal_sent_absence_not_established' if correct_parent else 'identity_mismatch_no_signal'
                self.assertEqual(receipt['last_resort_children'],[{'pid':700,'status':expected}])
                self.assertEqual((700,signal.SIGKILL) in signals,correct_parent)
                self.assertEqual(receipt['owned_command_groups']['all_absent'],correct_parent)
                self.assertFalse(receipt['cleanup_obligation']['absence_verified'])
                self.assertTrue(receipt['cleanup_obligation']['cleanup_required'])
                self.assertEqual(receipt['status'],'failed')

    def test_primary_and_receipt_failures_are_visible_without_payload_or_native(self):
        self.inputs();self.auth_failure=True;self.receipt_failure=True
        self.assertEqual(self.execute()['status'],'missing_receipt');self.assertEqual(self.gets,0)
        self.assertEqual(len(self.diagnostic_writes),1)
        raw=self.diagnostic_writes[0];self.assertLessEqual(len(raw),4096)
        diagnostic=json.loads(raw)
        self.assertEqual(diagnostic['stage'],'artifact_authentication')
        self.assertEqual(diagnostic['primary_error']['type'],'RuntimeError')
        self.assertEqual(diagnostic['receipt_error']['type'],'Rejected')
        self.assertTrue(diagnostic['primary_error']['frames'])
        self.assertNotIn('inert-token',raw.decode());self.assertNotIn('injected authentication failure',raw.decode());self.assertNotIn('injected receipt capacity failure',raw.decode())

    def test_final_state_failure_cannot_preserve_prepared_success(self):
        self.inputs();self.state_failure=True
        report=self.execute();self.assertEqual(report['status'],'failed');self.assertEqual(self.gets,2)
        diagnostic=json.loads(self.diagnostic_writes[0])
        self.assertEqual(diagnostic['primary_error']['type'],'Rejected')
        self.assertNotIn('fixture-sensitive-state-message',self.diagnostic_writes[0].decode())

    def test_capacity_failure_preserves_sample_without_extra_disk_read(self):
        window=object.__new__(self.window.Window)
        window.scope=self.root;window.entries={};window.started=0
        window.check=mock.Mock();window.validate_entries=mock.Mock()
        window.disk_usage=mock.Mock(return_value=SimpleNamespace(free=1))
        with self.assertRaises(self.window.Rejected):window.capacity()
        window.disk_usage.assert_called_once_with(self.root)
        self.assertEqual(window.last_capacity_sample['free_bytes'],1)
        self.assertEqual(window.last_capacity_sample['required_free_bytes'],self.window.FLOOR+self.window.OTHER+self.window.CAP)

    def test_expired_original_window_emits_no_further_failure_output(self):
        self.inputs();self.auth_failure=True;self.expire_during_auth=True
        self.assertEqual(self.execute()['status'],'missing_receipt')
        self.assertEqual(self.gets,0);self.assertEqual(self.diagnostic_writes,[])

    def test_wrong_head_rejected_before_payload(self):
        self.inputs('head');report=self.execute();self.assertEqual(report['status'],'failed');self.assertEqual(report['stage'],'artifact_metadata_identities');self.assertEqual(self.gets,0)
    def test_nested_runner_mode_drift_rejected(self):
        self.inputs('mode');report=self.execute();self.assertEqual(report['status'],'failed');self.assertEqual(report['stage'],'runner_reconstruction');self.assertEqual(self.gets,2)
    def test_retained_scan_must_match_actual_binary_scan(self):
        self.inputs('scanner');report=self.execute();self.assertEqual(report['status'],'failed');self.assertEqual(report['stage'],'release_binary_scans');self.assertEqual(self.gets,2)

class InstalledRunnerReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.runner=self.root/'Runner.app';self.runner.mkdir(mode=0o755);self.runner.chmod(0o755)  # Fixture mode is explicit even under a private umask.
        (self.runner/'binary').write_bytes(b'original');(self.runner/'binary').chmod(0o755)
        self.expected={'.':{'directory':True,'mode':'0755'},'binary':{'mode':'0755','sha256':digest(b'original')}}
        self.e=load('installed_runner_evidence',SMOKE/'evidence.py');self.b=load('installed_runner_window',SMOKE/'window.py');self.r=load('installed_runner_writer',SMOKE/'run.py')
        self.receipt=self.root/'installed-runner.json'
    def record(self,value):self.r.save_installed_runner(self.receipt,value,lambda:None)
    def test_actual_hash_mode_changes_are_saved_before_strict_failure(self):
        (self.runner/'binary').write_bytes(b'changed');(self.runner/'binary').chmod(0o600);(self.runner/'added').write_bytes(b'added')
        with self.assertRaisesRegex(AssertionError,'bounded inventory saved'):
            self.e.verify_installed_runner(self.runner,self.expected,self.b,lambda:None,self.record)
        result=json.loads(self.receipt.read_bytes());self.assertFalse(result['exact_payload']);rows={x['path']:x for x in result['differences']}
        self.assertEqual(rows['binary']['fields'],['mode','sha256']);self.assertEqual(rows['binary']['actual']['mode'],'0600');self.assertEqual(rows['binary']['expected']['sha256'],digest(b'original'));self.assertEqual(rows['added']['change'],'added')
    def test_exact_installed_runner_still_passes(self):
        result=self.e.verify_installed_runner(self.runner,self.expected,self.b,lambda:None,self.record)
        self.assertTrue(result['exact_payload']);self.assertEqual(result['differences'],[]);self.assertEqual(json.loads(self.receipt.read_bytes()),result)
    def test_receipt_failure_is_fatal_and_never_becomes_payload_pass(self):
        def fail(_):raise OSError('owned receipt fixture')
        with self.assertRaises(OSError):self.e.verify_installed_runner(self.runner,self.expected,self.b,lambda:None,fail)
    def test_expired_serialization_and_existing_receipt_never_write(self):
        expired=[False];encode=self.r.json.dumps
        def check():
            if expired[0]:raise TimeoutError('original phase')
        def during(*args,**kwargs):
            result=encode(*args,**kwargs);expired[0]=True;return result
        with mock.patch.object(self.r.json,'dumps',side_effect=during),mock.patch.object(Path,'open')as opened:
            with self.assertRaises(TimeoutError):self.r.save_installed_runner(self.receipt,{},check)
        opened.assert_not_called();self.receipt.write_bytes(b'original')
        with self.assertRaises(FileExistsError):self.r.save_installed_runner(self.receipt,{},lambda:None)
        self.assertEqual(self.receipt.read_bytes(),b'original')

if __name__=='__main__':unittest.main()
