"""Small same-run preparation/config controls: inert ZIPs, fake transport, no native work."""
import contextlib
import ast
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import plistlib
import shutil
import stat
import struct
import time
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
                def fail_scan(resources,*_):
                    resources.first_failure={'operation':'free_floor','root':None,'charged_allocated_bytes':0}
                    raise AssertionError('injected allocation floor')
                with mock.patch.object(run,'load',return_value=lifecycle),mock.patch.object(subprocess,'Popen',side_effect=spawn),mock.patch.object(run.Resources,'check',new=fail_scan),mock.patch.object(run,'await_cleanup_ack',side_effect=subprocess.TimeoutExpired('fixture-worker',3)),mock.patch.object(subprocess,'check_output',return_value='500\n' if correct_parent else '999\n') as parent_lookup,mock.patch.object(os,'getpgid',return_value=700),mock.patch.object(os,'killpg',side_effect=killpg),mock.patch.object(lifecycle,'stop_group',side_effect=lambda proc,row:row.update(owned_group_absent=True)),mock.patch.object(run,'aggregate_command_groups',side_effect=lambda meta,start:aggregate(meta,start,probe=killpg)),mock.patch.object(run,'terminal_stdout',return_value=True):
                    self.assertEqual(run.supervise(context,{}),1)
                receipt=json.loads((scope/'invocation-final.json').read_bytes())
                self.assertEqual(receipt['resource_scan_first_failure'],{'operation':'free_floor','root':None,'charged_allocated_bytes':0})
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

class NativeContextInheritanceTests(unittest.TestCase):
    def setUp(self):
        self.lifecycle=load('native_context_lifecycle',SMOKE/'lifecycle.py')

    def test_only_existing_fixed_system_context_is_forwarded(self):
        parent={'HOME':'/fixture/home','PATH':'/fixture/bin','LANG':'other',
                'GH_TOKEN':'secret','GITHUB_TOKEN':'secret2','SDKROOT':'unexpected',
                'DYLD_LIBRARY_PATH':'unexpected','STOREKIT_CONFIGURATION':'unexpected'}
        parent.update({key:'synthetic-'+key for key in self.lifecycle.NATIVE_CONTEXT_KEYS})
        expected={key:parent[key] for key in ('HOME','PATH')+self.lifecycle.NATIVE_CONTEXT_KEYS}
        expected['LANG']='en_US.UTF-8'
        self.assertEqual(self.lifecycle.child_environment(parent),expected)

    def test_absent_system_context_is_not_synthesized(self):
        self.assertEqual(self.lifecycle.child_environment({}),{'LANG':'en_US.UTF-8'})
        self.assertEqual(self.lifecycle.child_environment({'XPC_FLAGS':''}),
                         {'XPC_FLAGS':'','LANG':'en_US.UTF-8'})

    def test_diagnostics_record_presence_and_equality_without_values(self):
        parent={key:'not-for-diagnostics-'+key for key in self.lifecycle.NATIVE_CONTEXT_KEYS}
        child=self.lifecycle.child_environment(parent)
        child['XPC_FLAGS']='different-not-for-diagnostics'
        del child['XPC_SERVICE_NAME']
        with mock.patch.dict(os.environ,parent,clear=True),mock.patch.object(self.lifecycle,'ENV',child),mock.patch.object(self.lifecycle.shutil,'which',return_value=None):
            value=self.lifecycle.runtime_context()
        observed=value['native_context']
        self.assertEqual(observed['XPC_SERVICE_NAME'],{'parent_present':True,'child_present':False,'equal_to_parent':False})
        self.assertEqual(observed['XPC_FLAGS'],{'parent_present':True,'child_present':True,'equal_to_parent':False})
        self.assertEqual(observed['__CF_USER_TEXT_ENCODING'],{'parent_present':True,'child_present':True,'equal_to_parent':True})
        self.assertNotIn('not-for-diagnostics',json.dumps(value))


class InstalledRunnerLoaderPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name).resolve()
        self.e=load('loader_policy_evidence',SMOKE/'evidence.py');self.b=load('loader_policy_window',SMOKE/'window.py');self.index=0
    def fixture(self,kind_override=None):
        self.index+=1;root=self.root/str(self.index);root.mkdir();root.chmod(0o755)
        (root/'Runner').write_bytes(b'unchanged main executable');(root/'Runner').chmod(0o755)
        for name,kind in self.e.INSTALLED_RUNNER_LOADERS.items():
            path=root/name;path.parent.mkdir(parents=True,exist_ok=True)
            value=struct.pack('<8I',0xfeedfacf,0x0100000c,0,kind_override or kind,0,0,0,0)
            path.write_bytes(value);path.chmod(0o755)
        expected=self.e.payload_inventory(root,self.b,lambda:None)
        for name in self.e.INSTALLED_RUNNER_LOADERS:(root/name).chmod(0o644)
        return root,expected
    def test_exact_observed_nine_loader_transitions_then_strict_baseline(self):
        root,expected=self.fixture();receipts=[]
        first=self.e.verify_installed_runner(root,expected,self.b,lambda:None,receipts.append,initial_install=True)
        self.assertFalse(first['exact_payload']);self.assertTrue(first['accepted_payload']);self.assertEqual(len(first['accepted_install_transitions']),9)
        self.assertEqual(set(first['loader_headers']),set(self.e.INSTALLED_RUNNER_LOADERS))
        later=self.e.verify_installed_runner(root,first['files'],self.b,lambda:None,receipts.append)
        self.assertTrue(later['exact_payload']);self.assertEqual(later['accepted_install_transitions'],[])
        (root/next(iter(self.e.INSTALLED_RUNNER_LOADERS))).chmod(0o755)
        with self.assertRaises(AssertionError):self.e.verify_installed_runner(root,first['files'],self.b,lambda:None,receipts.append)
        self.assertFalse(receipts[-1]['accepted_payload'])
    def test_replaced_installed_root_is_fatal_even_with_exact_mode_and_content(self):
        root,expected=self.fixture();receipts=[]
        first=self.e.verify_installed_runner(root,expected,self.b,lambda:None,receipts.append,initial_install=True)
        identity={k:first[k] for k in ('path','root_device_inode')}
        prior=root.with_name(root.name+'-prior');root.rename(prior);shutil.copytree(prior,root)
        with self.assertRaises(AssertionError):self.e.verify_installed_runner(root,first['files'],self.b,lambda:None,receipts.append,installed_identity=identity)
        self.assertTrue(receipts[-1]['exact_payload']);self.assertFalse(receipts[-1]['installed_identity_matches'])
    def test_missing_transition_added_path_hash_directory_main_or_wrong_mode_stays_fatal(self):
        path=next(iter(self.e.INSTALLED_RUNNER_LOADERS))
        mutations=[lambda r:(r/path).chmod(0o755),lambda r:(r/'added').write_bytes(b'added'),
            lambda r:(r/path).write_bytes(b'changed'),lambda r:(r/'Frameworks').chmod(0o711),
            lambda r:(r/'Runner').chmod(0o644),lambda r:(r/path).chmod(0o600),lambda r:(r/path).unlink()]
        for mutate in mutations:
            root,expected=self.fixture();mutate(root);receipts=[]
            with self.assertRaisesRegex(AssertionError,'bounded inventory saved'):self.e.verify_installed_runner(root,expected,self.b,lambda:None,receipts.append,initial_install=True)
            self.assertFalse(receipts[-1]['accepted_payload']);self.assertFalse(receipts[-1]['exact_payload'])
    def test_execute_headers_never_qualify_as_loader_even_with_identical_hashes(self):
        root,expected=self.fixture(kind_override=2);receipts=[]
        with self.assertRaises(AssertionError):self.e.verify_installed_runner(root,expected,self.b,lambda:None,receipts.append,initial_install=True)
        self.assertFalse(receipts[-1]['accepted_payload'])
    def test_fat_headers_validate_all_slices_and_bounds(self):
        thin=lambda cpu,kind:struct.pack('<8I',0xfeedfacf,cpu,0,kind,0,0,0,0)
        a=thin(0x0100000c,6);x=thin(0x01000007,6)
        fat=struct.pack('>II',0xcafebabe,2)+struct.pack('>5I',0x0100000c,0,48,32,0)+struct.pack('>5I',0x01000007,0,80,32,0)+a+x
        self.assertEqual(self.e.loader_header_types(fat),[{'cpu':0x0100000c,'filetype':6},{'cpu':0x01000007,'filetype':6}])
        for bad in (b'',fat[:-1],fat[:48]+b'bad!'+fat[52:],fat[:28]+struct.pack('>5I',0x01000007,0,48,32,0)+a+x):self.assertIsNone(self.e.loader_header_types(bad))
    def test_initial_policy_not_enabled_for_ordinary_later_comparison(self):
        root,expected=self.fixture();receipts=[]
        with self.assertRaises(AssertionError):self.e.verify_installed_runner(root,expected,self.b,lambda:None,receipts.append)
        self.assertFalse(receipts[-1]['accepted_payload']);self.assertIsNone(receipts[-1]['loader_headers'])

class PackageRunnerReadmissionTests(unittest.TestCase):
    START=b"Test Case '-[CleanSendUITests.ShareExtensionEntryTests testPDFReceivedByExtensionThenImported]' started."
    UID='11111111-1111-4111-8111-111111111111'
    FIRST='22222222-2222-4222-8222-222222222222'
    SECOND='33333333-3333-4333-8333-333333333333'
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.home=Path(self.temp.name).resolve();self.device=self.home/'Devices'/self.UID
        self.applications=self.device/'data/Containers/Bundle/Application'
        self.root=self.applications/self.FIRST/'CleanSendUITests-Runner.app'
        self.root.mkdir(parents=True);(self.root/'PlugIns').mkdir()
        (self.root/'Runner').write_bytes(b'unchanged signed runner fixture');(self.root/'Runner').chmod(0o755)
        (self.root/'PlugIns/test').write_bytes(b'unchanged compiled case fixture')
        self.r=load('readmission_run',SMOKE/'run.py');self.e=load('readmission_evidence',SMOKE/'evidence.py');self.b=load('readmission_window',SMOKE/'window.py')
        self.rows=[];self.expired=False
        entries=self.e.payload_inventory(self.root,self.b,self.check)
        self.before=self.call(self.root,entries)
        self.new=self.applications/self.SECOND/self.root.name;shutil.copytree(self.root,self.new)
    def check(self):
        if self.expired:raise TimeoutError('original phase deadline')
    def call(self,root,entries=None,*,baseline=None,log=None,device=None,uid=None):
        return self.r.verify_package_runner(root,device or self.device,uid or self.UID,
            entries if entries is not None else baseline['files'],self.b,self.e,self.check,self.rows.append,
            baseline=baseline,started_log=log)
    def during(self,root=None):return self.call(root or self.new,baseline=self.before,log=self.START)
    def test_exact_new_container_admitted_once_then_same_identity_required(self):
        during=self.during();transition=during['case_start_readmission']
        self.assertTrue(during['exact_payload']);self.assertEqual(during['differences'],[])
        self.assertTrue(transition['accepted']);self.assertTrue(transition['identity_changed'])
        self.assertEqual(transition['prior_identity']['path'],str(self.root))
        self.assertEqual(transition['current_identity']['path'],str(self.new))
        self.assertEqual(during['files'],self.before['files']);self.assertEqual(during['accepted_install_transitions'],[])
        after=self.call(self.new,baseline=during);self.assertTrue(after['installed_identity_matches'])
        with self.assertRaises(AssertionError):self.call(self.new,baseline=during,log=self.START)
    def test_unchanged_container_is_valid_first_during_without_claiming_relocation(self):
        during=self.during(self.root)
        self.assertFalse(during['case_start_readmission']['identity_changed'])
        self.assertTrue(self.call(self.root,baseline=during)['installed_identity_matches'])
    def test_split_start_line_waits_for_full_case_marker_before_admission(self):
        # First64KiB read ends after 'started'; the final period arrives next.
        first=b'x'*(65536-len(self.START)+1)+self.START[:-1]
        self.assertEqual(len(first),65536)
        tail=first[-131072:];observed=[]
        if self.r.selected_case_started(tail):observed.append(self.call(self.new,baseline=self.before,log=tail))
        self.assertEqual(observed,[])
        tail=(tail+b'.\n    t = 0.00s Start Test')[-131072:]
        if self.r.selected_case_started(tail):observed.append(self.call(self.new,baseline=self.before,log=tail))
        self.assertEqual(len(observed),1);self.assertTrue(observed[0]['case_start_readmission']['accepted'])
        self.assertFalse(self.r.selected_case_started(self.START.replace(b'ShareExtensionEntryTests',b'OtherTests')))
    def test_no_case_wrong_class_truncated_or_overlong_marker_never_readmits(self):
        for log in (b'',self.START.replace(b'ShareExtensionEntryTests',b'OtherTests'),self.START[:-1],b'x'*131073):
            with self.subTest(log=log[:80]),self.assertRaises(AssertionError):self.call(self.new,baseline=self.before,log=log)
        with self.assertRaises(AssertionError):self.call(self.new,baseline=self.before)
        with self.assertRaises(AssertionError):self.call(self.new,self.before['files'],log=self.START)
    def test_changed_bytes_mode_type_added_or_missing_file_cannot_readmit(self):
        def replace_with_directory(root):
            (root/'PlugIns/test').unlink();(root/'PlugIns/test').mkdir()
        mutations=[lambda r:(r/'Runner').write_bytes(b'changed'),lambda r:(r/'Runner').chmod(0o644),
            lambda r:(r/'PlugIns').chmod(0o711),lambda r:(r/'extra').write_bytes(b'added'),
            lambda r:(r/'PlugIns/test').unlink(),replace_with_directory]
        for index,mutate in enumerate(mutations):
            with self.subTest(index=index):
                root=self.applications/f'44444444-4444-4444-8444-{index:012d}'/self.root.name
                shutil.copytree(self.root,root);mutate(root)
                with self.assertRaises(AssertionError):self.during(root)
                self.assertFalse(self.rows[-1]['exact_payload']);self.assertFalse(self.rows[-1]['case_start_readmission']['accepted'])
    def test_wrong_uuid_noncanonical_container_and_wrong_runner_rejected(self):
        for path in (self.device/'data/elsewhere'/self.root.name,
                     self.applications/'not-a-uuid'/self.root.name,self.new.with_name('OtherRunner.app')):
            with self.subTest(path=str(path)),self.assertRaises((ValueError,AssertionError)):self.during(path)
        with self.assertRaises(AssertionError):self.call(self.new,baseline=self.before,log=self.START,uid=self.SECOND)
        outside=self.home/'Elsewhere'/self.SECOND/'data/Containers/Bundle/Application'/self.FIRST/self.root.name
        shutil.copytree(self.root,outside)
        with self.assertRaises(AssertionError):self.call(outside,baseline=self.before,log=self.START,device=outside.parents[5],uid=self.SECOND)
    def test_root_or_ancestor_symlink_never_followed(self):
        original=self.new.with_name('original');self.new.rename(original);self.new.symlink_to(original,target_is_directory=True)
        with self.assertRaises(OSError):self.during()
        self.new.unlink();original.rename(self.new)
        moved=self.new.parent.with_name('moved');self.new.parent.rename(moved);self.new.parent.symlink_to(moved,target_is_directory=True)
        with self.assertRaises(OSError):self.during()
    def test_owned_device_replacement_is_rejected_even_with_exact_payload(self):
        prior=self.device.with_name('prior-device');self.device.rename(prior);shutil.copytree(prior,self.device)
        with self.assertRaises(AssertionError):self.during()
    def test_runner_replaced_during_inventory_is_saved_and_rejected(self):
        inventory=self.e.payload_inventory
        def replace(*args,**kwargs):
            value=inventory(*args,**kwargs);old=self.new.with_name('old-runner')
            self.new.rename(old);shutil.copytree(old,self.new);return value
        with mock.patch.object(self.e,'payload_inventory',side_effect=replace),self.assertRaises(AssertionError):self.during()
        self.assertTrue(self.rows[-1]['exact_payload']);self.assertFalse(self.rows[-1]['location_stable'])
        self.assertFalse(self.rows[-1]['case_start_readmission']['accepted'])
    def test_after_changed_container_or_same_path_replaced_inode_is_fatal(self):
        during=self.during()
        with self.assertRaises(AssertionError):self.call(self.root,baseline=during)
        old=self.new.with_name('previous');self.new.rename(old);shutil.copytree(old,self.new)
        with self.assertRaises(AssertionError):self.call(self.new,baseline=during)
        self.assertTrue(self.rows[-1]['exact_payload']);self.assertFalse(self.rows[-1]['installed_identity_matches'])
    def test_expiry_after_inventory_does_not_save_or_renew_admission(self):
        inventory=self.e.payload_inventory;prior=len(self.rows)
        def expire(*args,**kwargs):
            value=inventory(*args,**kwargs);self.expired=True;return value
        with mock.patch.object(self.e,'payload_inventory',side_effect=expire),self.assertRaises(TimeoutError):self.during()
        self.assertEqual(len(self.rows),prior)
    def test_receipt_failure_stays_fatal(self):
        def fail(_):raise OSError('owned evidence failure')
        with self.assertRaises(OSError):
            self.r.verify_package_runner(self.new,self.device,self.UID,self.before['files'],self.b,self.e,self.check,fail,baseline=self.before,started_log=self.START)
    def test_replacement_while_recording_cannot_return_an_admitted_baseline(self):
        def replace(value):
            self.rows.append(value);old=self.new.with_name('old-at-receipt')
            self.new.rename(old);shutil.copytree(old,self.new)
        with self.assertRaisesRegex(AssertionError,'while recording evidence'):
            self.r.verify_package_runner(self.new,self.device,self.UID,self.before['files'],self.b,self.e,self.check,replace,baseline=self.before,started_log=self.START)


class PackageObservationRootTests(unittest.TestCase):
    UID='11111111-1111-4111-8111-111111111111'
    FIRST='22222222-2222-4222-8222-222222222222'
    SECOND='33333333-3333-4333-8333-333333333333'
    GROUP='44444444-4444-4444-8444-444444444444'
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.home=Path(self.temp.name).resolve();self.device=self.home/'Devices'/self.UID
        self.data=self.device/'data/Containers/Data/Application'/self.FIRST
        self.new=self.data.with_name(self.SECOND)
        self.group=self.device/'data/Containers/Shared/AppGroup'/self.GROUP
        for path in (self.data,self.new,self.group):path.mkdir(parents=True)
        self.r=load('observation_run',SMOKE/'run.py');self.e=load('observation_evidence',SMOKE/'evidence.py');self.b=load('observation_window',SMOKE/'window.py')
        self.expired=False;self.before=self.bind(self.data)
        self.ready=self.r.CASE_STARTED+b'\n'+self.r.WORKSPACE_READY
        for patch in (mock.patch.object(subprocess,'Popen',side_effect=AssertionError('native forbidden')),
                      mock.patch.object(os,'killpg',side_effect=AssertionError('signals forbidden'))):
            patch.start();self.addCleanup(patch.stop)
    def check(self):
        if self.expired:raise TimeoutError('original phase deadline')
    def bind(self,data,baseline=None,log=None,group=None):
        return self.r.verify_observation_roots(data,group or self.group,self.device,self.UID,self.b,self.check,baseline=baseline,started_log=log)
    def during(self):return self.bind(self.new,self.before,self.ready)
    def test_actual_worker_sequence_waits_for_late_aut_ready_with_same_data_container(self):
        # Execute the worker's real three observation branches in sequence. All
        # process/native operations are mocked; the container filesystem is real.
        worker=next(n for n in ast.parse((SMOKE/'run.py').read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='worker')
        loop=next(n for n in ast.walk(worker) if isinstance(n,ast.While) and ast.unparse(n.test)=='proc.poll() is None')
        branches=[n for n in loop.body if isinstance(n,ast.If)]
        self.assertEqual(len(branches),3)
        step=compile(ast.fix_missing_locations(ast.Module(body=branches,type_ignores=[])),'actual-worker-observation','exec')
        tmp=self.data/'tmp/CleanSend';tmp.mkdir(parents=True)
        prelaunch=self.e.Observer(self.b,self.check);prelaunch.started=time.monotonic()
        prelaunch.event(self.group/'SharedInbox',tmp,io.BytesIO())
        sampler=self.e.Observer(self.b,self.check);sampler.started=time.monotonic();events=io.BytesIO();queried=[]
        def container(kind,name):
            queried.append(name);return self.data if kind=='data' else self.group
        env=dict(vars(self.r),during=False,observation_roots=None,tail=self.r.CASE_STARTED,
            installed=mock.Mock(),container=container,initial_roots=self.before,
            resources=SimpleNamespace(device=self.device,check=self.check),uid=self.UID,b=self.b,
            sampler=sampler,events=events,run=SimpleNamespace(meta={'container_observation':{}},persist=lambda:None))
        exec(step,env)
        self.assertTrue(env['during']);self.assertIsNone(env['observation_roots'])
        self.assertEqual(queried,[]);self.assertEqual(sampler.events,[])
        # Workspace.init has not run at case start. It now replaces the same
        # path's directory; retaining the old root inode would fail here.
        tmp.rename(tmp.with_name('old-CleanSend'));tmp.mkdir()
        env['tail']=self.r.CASE_STARTED+b'\n'+self.r.WORKSPACE_READY[:-1]
        exec(step,env);self.assertEqual(sampler.events,[])
        env['tail']+=b'\n';exec(step,env)
        self.assertTrue(env['run'].meta['container_observation']['case_baseline_empty'])
        self.assertEqual(len(queried),2);self.assertEqual(env['installed'].call_count,1)
        self.assertEqual(sampler.roots[str(tmp)],(tmp.stat().st_dev,tmp.stat().st_ino))
        export=tmp/'document.pdf';export.write_bytes(b'current export')
        ready=self.group/'SharedInbox/batch.ready';ready.mkdir(parents=True)
        (ready/'copy.pdf').write_bytes(b'current export');exec(step,env)
        export.unlink();shutil.rmtree(ready);exec(step,env)
        self.assertEqual(sampler.assert_workflow()['matched_hashes'],[digest(b'current export')])
        self.assertEqual(len(queried),2)  # No second admission or repeated native lookup.

    def test_real_export_hash_matches_only_current_data_root_and_final_cleanup_stays_required(self):
        during=self.during();self.assertNotEqual(during['data'],self.before['data'])
        observer=self.e.Observer(self.b,self.check);observer.started=time.monotonic();events=io.BytesIO()
        tmp=self.new/'tmp/CleanSend';tmp.mkdir(parents=True);inbox=self.group/'SharedInbox'
        state=observer.event(inbox,tmp,events)
        self.assertFalse(state['group']['entries']);self.assertFalse(state['tmp']['entries'])
        export=tmp/'export-1';export.mkdir();(export/'document.pdf').write_bytes(b'actual synthetic PDF')
        ready=inbox/'batch.ready';ready.mkdir(parents=True);(ready/'copy.pdf').write_bytes(b'actual synthetic PDF')
        observer.event(inbox,tmp,events)
        with self.assertRaisesRegex(AssertionError,'temporary files remain'):observer.assert_workflow()
        shutil.rmtree(export);shutil.rmtree(ready);observer.event(inbox,tmp,events)
        self.assertEqual(observer.assert_workflow()['matched_hashes'],[digest(b'actual synthetic PDF')])
        self.assertEqual(self.bind(self.new,during),during)
        stale=self.e.Observer(self.b,self.check);stale.started=time.monotonic()
        stale.event(inbox,self.data/'tmp/CleanSend',io.BytesIO())
        with self.assertRaisesRegex(AssertionError,'exactly one exported PDF'):stale.assert_workflow()
    def test_wrong_export_content_never_matches_queue(self):
        observer=self.e.Observer(self.b,self.check);observer.started=time.monotonic();events=io.BytesIO()
        tmp=self.new/'tmp/CleanSend';tmp.mkdir(parents=True);inbox=self.group/'SharedInbox'
        observer.event(inbox,tmp,events)
        (tmp/'document.pdf').write_bytes(b'original')
        ready=inbox/'batch.ready';ready.mkdir(parents=True);(ready/'copy.pdf').write_bytes(b'changed')
        observer.event(inbox,tmp,events);shutil.rmtree(ready);(tmp/'document.pdf').unlink();observer.event(inbox,tmp,events)
        with self.assertRaisesRegex(AssertionError,'exactly one exported PDF'):observer.assert_workflow()
    def test_rebind_requires_complete_selected_case_and_existing_baseline(self):
        for log in (b'',self.r.CASE_STARTED,self.ready[:-1],self.ready.replace(b'ShareExtensionEntryTests',b'OtherTests'),self.ready.replace(b'format=PDF',b'format=PNG'),self.r.WORKSPACE_READY+self.r.CASE_STARTED,b'x'*131073):
            with self.subTest(log=log[:80]),self.assertRaises(AssertionError):self.bind(self.new,self.before,log)
        with self.assertRaises(AssertionError):self.bind(self.new,None,self.ready)
        with self.assertRaises(AssertionError):self.bind(self.new,self.before)
    def test_changed_group_wrong_path_and_device_identity_are_rejected(self):
        other=self.group.with_name(self.SECOND);other.mkdir()
        with self.assertRaises(AssertionError):self.bind(self.new,self.before,self.ready,other)
        for path in (self.group,self.data.parent/'not-a-uuid',self.home/'outside'):
            with self.subTest(path=str(path)),self.assertRaises((AssertionError,ValueError)):self.bind(path,self.before,self.ready)
        old=self.device.with_name('old');self.device.rename(old);shutil.copytree(old,self.device)
        with self.assertRaises(AssertionError):self.during()
    def test_data_relocation_or_replaced_inode_after_admission_is_rejected(self):
        during=self.during()
        with self.assertRaises(AssertionError):self.bind(self.data,during)
        old=self.new.with_name('old');self.new.rename(old);shutil.copytree(old,self.new)
        with self.assertRaises(AssertionError):self.bind(self.new,during)
    def test_symlink_root_and_ancestor_are_never_followed(self):
        old=self.new.with_name('old');self.new.rename(old);self.new.symlink_to(old,target_is_directory=True)
        with self.assertRaises(OSError):self.during()
        self.new.unlink();old.rename(self.new)
        parent=self.new.parent;old=parent.with_name('old-parent');parent.rename(old);parent.symlink_to(old,target_is_directory=True)
        with self.assertRaises(OSError):self.during()
    def test_replacement_during_admission_and_expired_original_deadline_fail(self):
        original=self.b.directory;calls=[0]
        @contextlib.contextmanager
        def changing(path):
            with original(path) as fd:
                yield fd
            calls[0]+=1
            if calls[0]==3:
                old=self.new.with_name('old');self.new.rename(old);shutil.copytree(old,self.new)
        with mock.patch.object(self.b,'directory',changing),self.assertRaises(AssertionError):self.during()
        self.expired=True
        with self.assertRaises(TimeoutError):self.during()


class PackageResourceScanTests(unittest.TestCase):
    def setUp(self):
        self.m=load('package_resource_scan',SMOKE/'run.py');self.clock=[101.0]
        self.m.SCOPE=self.m.OWNED_ROOT=Path('/fixture/private-owned-root')
        patches=(mock.patch.object(time,'monotonic',new=lambda:self.clock[0]),
                 mock.patch.object(self.m.shutil,'disk_usage',return_value=SimpleNamespace(free=32*2**30)),
                 mock.patch.object(subprocess,'Popen',side_effect=AssertionError('native/network forbidden')),
                 mock.patch.object(os,'killpg',side_effect=AssertionError('signals forbidden')))
        for patch in patches:patch.start();self.addCleanup(patch.stop)
    @staticmethod
    def info(blocks,mode=0o100600):return SimpleNamespace(st_blocks=blocks,st_mode=mode)
    def test_complete_two_root_scan_keeps_both_directory_stats_and_all_allocations(self):
        owned=str(self.m.OWNED_ROOT);device='/fixture/device';device_dirs=['data','link']
        rows={owned:[(owned,['Products'],['receipt.json']),(owned+'/Products',[],['app'])],
              device:[(device,device_dirs,[]),(device+'/data',[],['state'])]}
        values={owned:self.info(4,0o040700),owned+'/Products':self.info(2,0o040700),
                owned+'/receipt.json':self.info(1),owned+'/Products/app':self.info(5),
                device:self.info(3,0o040700),device+'/data':self.info(4,0o040700),
                device+'/link':self.info(1,0o120777),device+'/data/state':self.info(7)}
        resources=self.m.Resources(100);resources.device=Path(device)
        with mock.patch.object(Path,'exists',return_value=True),mock.patch.object(os,'walk',side_effect=lambda root,**kw:rows[str(root)]) as walk,mock.patch.object(os,'lstat',side_effect=lambda path:values[path]) as stat_call:
            resources.check(196)
        self.assertEqual(resources.maximum,33*512)
        names=[call.args[0] for call in stat_call.call_args_list]
        self.assertEqual(len(names),10)  # R + 2D + F = 2 + 4 + 4; no stats omitted.
        self.assertEqual(names.count(owned+'/Products'),2);self.assertEqual(names.count(device+'/data'),2)
        self.assertEqual(names.count(device+'/link'),1);self.assertNotIn('link',device_dirs)
        self.assertEqual([call.kwargs for call in walk.call_args_list],[{'followlinks':False}]*2)
        self.assertIsNone(resources.first_failure)
    def test_changed_or_replaced_directory_is_reobserved_at_traversal(self):
        root=str(self.m.OWNED_ROOT);seen=[]
        def observe(path):
            seen.append(path)
            if path==root:return self.info(1,0o040700)
            if path==root+'/child':return self.info(2 if seen.count(path)==1 else 20,0o040700)
            return self.info(3)
        resources=self.m.Resources(100)
        with mock.patch.object(os,'walk',return_value=[(root,['child'],[]),(root+'/child',[],['file'])]),mock.patch.object(os,'lstat',side_effect=observe):resources.check(196)
        self.assertEqual(resources.maximum,(1+2+20+3)*512)
        self.assertEqual(seen.count(root+'/child'),2)
    def test_real_walk_does_not_follow_directory_replaced_by_symlink(self):
        with tempfile.TemporaryDirectory(prefix='native-scan-links-') as temporary:
            root=Path(temporary)/'owned';outside=Path(temporary)/'outside'
            root.mkdir();outside.mkdir();child=root/'child';child.mkdir()
            (child/'old').write_bytes(b'old');(outside/'never-read').write_bytes(b'outside')
            self.m.OWNED_ROOT=root;resources=self.m.Resources(100)
            original_walk=os.walk;original_stat=os.lstat;visited=[];stats=[]
            def changing_walk(*args,**kwargs):
                self.assertFalse(kwargs['followlinks'])
                for row in original_walk(*args,**kwargs):
                    visited.append(row[0]);yield row
                    if row[0]==str(root):
                        child.rename(outside/'previous');child.symlink_to(outside,target_is_directory=True)
            def observe(path,*args,**kwargs):stats.append(os.fspath(path));return original_stat(path,*args,**kwargs)
            with mock.patch.object(os,'walk',side_effect=changing_walk),mock.patch.object(os,'lstat',side_effect=observe):resources.check(196)
            self.assertEqual(visited,[str(root)])
            self.assertFalse(any(name.startswith(str(outside)) for name in stats))
            self.assertIsNone(resources.first_failure)
    def test_each_worker_and_supervisor_sample_is_fresh_and_independent(self):
        root=str(self.m.OWNED_ROOT);blocks=[1];worker=self.m.Resources(100);supervisor=self.m.Resources(100)
        with mock.patch.object(os,'walk',side_effect=lambda *a,**k:iter([(root,[],[])])),mock.patch.object(os,'lstat',side_effect=lambda path:self.info(blocks[0],0o040700)) as observed:
            worker.check(196);supervisor.check(772)
            self.assertEqual(observed.call_count,2)
            blocks[0]=7;self.clock[0]+=2;worker.check(196)
            self.assertEqual(worker.maximum,7*512);self.assertEqual(supervisor.maximum,512)
            supervisor.check(772);self.assertEqual(observed.call_count,4);self.assertEqual(supervisor.maximum,7*512)
    def test_first_deadline_failure_has_bounded_counters_and_is_not_overwritten(self):
        root=str(self.m.OWNED_ROOT);resources=self.m.Resources(100)
        def observe(path):
            if path!=root:self.clock[0]=296
            return self.info(1)
        with mock.patch.object(os,'walk',return_value=[(root,[],['secret-token'])]),mock.patch.object(os,'lstat',side_effect=observe),mock.patch.object(Path,'open',side_effect=AssertionError('failure I/O forbidden')):
            with self.assertRaisesRegex(AssertionError,'owned stat deadline'):resources.check(196)
        failure=dict(resources.first_failure)
        self.assertEqual(failure['operation'],'stat_deadline');self.assertEqual(failure['root'],'owned')
        self.assertEqual(failure['successful_lstat_count'],2);self.assertEqual(failure['lstat_calls'],2)
        self.assertEqual(failure['charged_allocated_bytes'],512);self.assertFalse(failure['complete_scan'])
        self.assertEqual(failure['deadline_monotonic'],296);self.assertEqual(failure['elapsed_seconds'],196)
        self.assertEqual(failure['roots']['owned']['lstat_calls'],2);self.assertFalse(failure['roots']['owned']['complete'])
        self.assertLess(len(json.dumps(failure)),2048);self.assertNotIn('secret',json.dumps(failure));self.assertNotIn('/fixture',json.dumps(failure))
        self.clock[0]=101
        with mock.patch.object(os,'walk',return_value=[(root,[],[])]),mock.patch.object(os,'lstat',side_effect=PermissionError('credential must not enter evidence')):
            with self.assertRaises(PermissionError):resources.check(772)
        self.assertEqual(resources.first_failure,failure)
    def test_complete_scan_over_cap_remains_fatal(self):
        root=str(self.m.OWNED_ROOT);resources=self.m.Resources(100)
        with mock.patch.object(self.m,'CAP',512),mock.patch.object(os,'walk',return_value=[(root,[],[])]),mock.patch.object(os,'lstat',return_value=self.info(2)):
            with self.assertRaisesRegex(AssertionError,'owned allocation cap'):resources.check(196)
        failure=resources.first_failure
        self.assertTrue(failure['complete_scan']);self.assertEqual(failure['charged_allocated_bytes'],1024)
        self.assertEqual(failure['operation'],'allocation_cap')
    def test_original100000_entry_ceiling_stops_the_complete_scan(self):
        root=str(self.m.OWNED_ROOT);resources=self.m.Resources(100)
        with mock.patch.object(os,'walk',return_value=[(root,[],['file']*100000)]),mock.patch.object(os,'lstat',new=lambda path:self.info(1)):
            with self.assertRaisesRegex(AssertionError,'owned inventory entry cap'):resources.check(196)
        failure=resources.first_failure
        self.assertEqual(failure['successful_lstat_count'],100001);self.assertEqual(failure['lstat_calls'],100001)
        self.assertEqual(failure['charged_allocated_bytes'],100000*512);self.assertEqual(failure['operation'],'entry_cap')
    def test_diagnostic_failure_does_not_mask_primary_exception(self):
        root=str(self.m.OWNED_ROOT);resources=self.m.Resources(100);primary=PermissionError('private text')
        def fail(path):
            self.clock[0]=None
            raise primary
        def clock():
            if self.clock[0] is None:raise RuntimeError('diagnostic clock failure')
            return self.clock[0]
        with mock.patch.object(time,'monotonic',side_effect=clock),mock.patch.object(os,'walk',return_value=[(root,[],[])]),mock.patch.object(os,'lstat',side_effect=fail):
            with self.assertRaises(PermissionError) as caught:resources.check(196)
        self.assertIs(caught.exception,primary);self.assertIsNone(resources.first_failure)


class PackageTestLaunchAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.m=load('package_launch_admission',SMOKE/'run.py')
        self.l=load('package_launch_lifecycle',SMOKE/'lifecycle.py')
        worker=next(n for n in ast.parse((SMOKE/'run.py').read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='worker')
        events=next(n for n in ast.walk(worker) if isinstance(n,ast.With) and any(isinstance(i.optional_vars,ast.Name) and i.optional_vars.id=='events' for i in n.items))
        launch_index=next(i for i,n in enumerate(events.body) if isinstance(n,ast.Try))
        admission_index=max(i for i,n in enumerate(events.body[:launch_index]) if isinstance(n,ast.Assert))
        launch=events.body[launch_index];log=launch.body[0]
        reader_index=next(i for i,n in enumerate(log.body) if isinstance(n,ast.With))
        # Execute the actual worker admission, persistence, log open and Popen,
        # including its finally. Only the later native observation loop is omitted.
        boundary=ast.Try(body=[ast.With(items=log.items,body=log.body[:reader_index],type_comment=None)],
                         handlers=launch.handlers,orelse=launch.orelse,finalbody=launch.finalbody)
        self.boundary=compile(ast.fix_missing_locations(ast.Module(body=events.body[admission_index:launch_index]+[boundary],type_ignores=[])),str(SMOKE/'run.py'),'exec')

    def launch(self,*,elapsed=250,persist_delay=0,open_delay=0):
        clock=[100.0+elapsed];opened=[];observed=[];original_open=Path.open
        with tempfile.TemporaryDirectory() as temporary,mock.patch.object(time,'monotonic',side_effect=lambda:clock[0]):
            run=self.l.Run();run.start=100.0
            deadlines=dict(run.meta['phase_deadlines_seconds']);persist_count=0
            def persist():
                nonlocal persist_count
                persist_count+=1
                if persist_count==1:clock[0]+=persist_delay
            run.persist=persist
            def open_log(path,*args,**kwargs):
                stream=original_open(path,*args,**kwargs);opened.append(stream);clock[0]+=open_delay
                return stream
            state=dict(vars(self.m),run=run,l=self.l,start=run.start,SCOPE=Path(temporary),uid='fixture-owned')
            process=SimpleNamespace(pid=123,returncode=0)
            def spawn(*args,**kwargs):
                observed.append({'time':clock[0],'end':state['end'],'run_end':run.end})
                return process
            def stopped(proc,row):row['owned_group_absent']=True
            with mock.patch.object(Path,'open',open_log),mock.patch.object(subprocess,'Popen',side_effect=spawn) as popen,mock.patch.object(self.l,'stop_group',side_effect=stopped) as stop,mock.patch.object(os,'killpg',side_effect=AssertionError('signals forbidden')):
                error=None
                try:exec(self.boundary,state)
                except AssertionError as caught:error=caught
            self.assertTrue(all(stream.closed for stream in opened))
            self.assertEqual(run.start,100.0);self.assertEqual(run.end,560)
            self.assertEqual(run.meta['phase_deadlines_seconds'],deadlines)
            self.assertEqual(deadlines['absence'],660);self.assertEqual(run.meta['total_seconds'],780)
            if 'end' in state:self.assertLessEqual(state['end'],run.start+560-4)
            for launch in observed:self.assertEqual(launch['end']-launch['time'],300)
            return error,popen.call_count,stop.call_count,observed,state.get('end')

    def test_slow_metadata_write_rejects_stale_admission_without_spawn(self):
        error,spawns,stops,_,end=self.launch(persist_delay=7)
        self.assertIsInstance(error,AssertionError);self.assertEqual(spawns,0);self.assertEqual(stops,0)
        self.assertIsNone(end)

    def test_slow_log_open_rejects_insufficient_original_work_before_test_end_exists(self):
        for delay in (7,301):
            with self.subTest(delay=delay):
                error,spawns,stops,_,end=self.launch(open_delay=delay)
                self.assertIsInstance(error,AssertionError);self.assertEqual(spawns,0);self.assertEqual(stops,0)
                self.assertIsNone(end)

    def test_fast_open_spawns_once_with_full_window_and_original_work_cleanup_deadlines(self):
        error,spawns,stops,observed,end=self.launch(open_delay=1)
        self.assertIsNone(error);self.assertEqual(spawns,1);self.assertEqual(stops,1)
        self.assertEqual(observed,[{'time':351.0,'end':651.0,'run_end':551.0}])
        self.assertEqual(end,651.0)

    def test_early_long_open_establishes_single_full_window_after_io(self):
        error,spawns,stops,observed,end=self.launch(elapsed=100,open_delay=150)
        self.assertIsNone(error);self.assertEqual(spawns,1);self.assertEqual(stops,1)
        self.assertEqual(observed,[{'time':350.0,'end':650.0,'run_end':550.0}])
        self.assertEqual(end,650.0)

    def test_exact_original_work_reserve_can_spawn_with_no_io_delay(self):
        error,spawns,stops,observed,end=self.launch(elapsed=256)
        self.assertIsNone(error);self.assertEqual(spawns,1);self.assertEqual(stops,1)
        self.assertEqual(observed,[{'time':356.0,'end':656.0,'run_end':556.0}])
        self.assertEqual(end,656.0)


class PackageReadinessBudgetTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.m=load('package_boot_budget',SMOKE/'run.py');self.l=load('package_boot_lifecycle',SMOKE/'lifecycle.py');self.l.OUT=self.root
        self.clock=[58.0]
    def actual_run(self):
        run=self.l.Run();run.start=0;run.persist=mock.Mock();return run
    def test_observed_93s_can_finish_with_full_test_reserve_and_no_renewal(self):
        with mock.patch.object(time,'monotonic',side_effect=lambda:self.clock[0]):
            run=self.actual_run();proc=SimpleNamespace(pid=123,returncode=None)
            def wait(timeout):
                self.assertEqual(timeout,120);self.clock[0]+=93;proc.returncode=0
            proc.wait=wait;resources=SimpleNamespace(check=mock.Mock())
            with mock.patch.object(subprocess,'Popen',return_value=proc) as spawn,mock.patch.object(self.l,'stop_group',side_effect=lambda p,r:r.update(owned_group_absent=True)):
                self.m.wait_for_package_boot(run,resources,'fixture-owned')
            resources.check.assert_called_once_with(256);spawn.assert_called_once();self.assertEqual(run.start,0);self.assertEqual(run.end,560);self.assertGreaterEqual(run.remaining(),304);self.assertTrue(run.meta['commands'][0]['owned_group_absent'])
    def test_late_persist_or_open_cannot_spawn_from_stale_120s_allowance(self):
        original_open=Path.open
        for stage in ('persist','open'):
            with self.subTest(stage=stage),mock.patch.object(time,'monotonic',side_effect=lambda:self.clock[0]):
                self.clock[0]=200;run=self.actual_run()
                def persisted():
                    if stage=='persist':self.clock[0]=252
                run.persist=persisted
                def opened(path,*args,**kwargs):
                    stream=original_open(path,*args,**kwargs)
                    if stage=='open':self.clock[0]=252
                    return stream
                with mock.patch.object(Path,'open',opened),mock.patch.object(subprocess,'Popen') as spawn:
                    with self.assertRaises(TimeoutError):self.m.wait_for_package_boot(run,SimpleNamespace(check=lambda phase:None),'fixture-owned')
                spawn.assert_not_called();self.assertEqual(run.end,560);self.assertEqual(run.start,0)
    def test_late_boot_clips_to_original256_and_timeout_closes_one_child(self):
        with mock.patch.object(time,'monotonic',side_effect=lambda:self.clock[0]):
            self.clock[0]=200;run=self.actual_run();proc=SimpleNamespace(pid=123,returncode=None)
            def wait(timeout):
                self.assertEqual(timeout,52);self.clock[0]+=timeout;raise subprocess.TimeoutExpired('fixture',timeout)
            proc.wait=wait
            def stopped(p,row):p.returncode=-15;row['owned_group_absent']=True
            with mock.patch.object(subprocess,'Popen',return_value=proc) as spawn,mock.patch.object(self.l,'stop_group',side_effect=stopped) as stop:
                with self.assertRaises(subprocess.TimeoutExpired):self.m.wait_for_package_boot(run,SimpleNamespace(check=lambda phase:None),'fixture-owned')
            spawn.assert_called_once();stop.assert_called_once();self.assertTrue(run.meta['commands'][0]['owned_group_absent']);self.assertEqual(run.end,560);self.assertEqual(run.start,0)
    def test_scan_expiry_prevents_native_spawn_and_restores_original_work_end(self):
        with mock.patch.object(time,'monotonic',side_effect=lambda:self.clock[0]):
            run=self.actual_run()
            def scan(phase):self.clock[0]=256;raise AssertionError('original phase deadline')
            with mock.patch.object(subprocess,'Popen') as spawn:
                with self.assertRaises(AssertionError):self.m.wait_for_package_boot(run,SimpleNamespace(check=scan),'fixture-owned')
            spawn.assert_not_called();self.assertEqual(run.end,560);self.assertEqual(run.start,0)
    def test_cleanup_uses_existing_absolute_ends_and_attempts_delete_after_timeout(self):
        for elapsed,expected in ((560,[45,25]),(610,[5,19])):
            with self.subTest(elapsed=elapsed),mock.patch.object(time,'monotonic',side_effect=lambda:self.clock[0]):
                self.clock[0]=elapsed;run=self.actual_run();waits=[]
                def spawn(*args,**kwargs):
                    proc=SimpleNamespace(pid=123,returncode=None)
                    def wait(timeout):waits.append(timeout);self.clock[0]+=timeout;raise subprocess.TimeoutExpired('fixture',timeout)
                    proc.wait=wait;return proc
                def stopped(p,row):p.returncode=-15;row['owned_group_absent']=True
                with mock.patch.object(subprocess,'Popen',side_effect=spawn) as spawned,mock.patch.object(self.l,'stop_group',side_effect=stopped):
                    cleanup=self.m.cleanup_device_commands(run,'fixture-owned',self.l)
                self.assertEqual(waits,expected);self.assertEqual(spawned.call_count,2);self.assertTrue(all('TimeoutExpired' in v for v in cleanup.values()));self.assertTrue(all(c['owned_group_absent'] for c in run.meta['commands']));self.assertNotEqual(cleanup,{'shutdown':0,'delete':0});self.assertNotIn('device_removed',run.meta)

class PackageAX5PostconditionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.m=load('package_ax5_postcondition',SMOKE/'run.py');self.l=load('package_ax5_lifecycle',SMOKE/'lifecycle.py')
        self.l.OUT=self.root;self.l.ENV={'HOME':str(self.root)};self.clock=[50.0]
        self.uid='A09F18F8-31EF-372D-A426-0197E73D75E8'
        self.device=self.root/'Library/Developer/CoreSimulator/Devices'/self.uid;self.device.mkdir(parents=True)
        self.calls=[];self.scans=[];self.mode='timeout';self.closure_fault=None;self.after_set=None;self.before_read_scan=None;self.read_value=self.l.AX5
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(time,'monotonic',side_effect=lambda:self.clock[0]).start()
        self.run=self.l.Run();self.run.start=0;self.run.meta['owned_uuid']=self.uid;self.run.persist=mock.Mock()
        mock.patch.object(subprocess,'Popen',side_effect=self.spawn).start()
        mock.patch.object(self.l,'stop_group',side_effect=self.stop).start()
        self.resources=SimpleNamespace(check=self.scan)
    def scan(self,phase):
        self.scans.append(phase)
        if len(self.scans)==2 and self.before_read_scan:self.before_read_scan()
        self.assertLess(self.clock[0],phase)
    def spawn(self,args,**kwargs):
        self.calls.append(args);self.assertEqual(args[:3],['xcrun','simctl','ui'])
        setter=len(args)==6;proc=SimpleNamespace(pid=500+len(self.calls),returncode=None)
        def wait(timeout):
            self.clock[0]+=min(60 if setter else 1,timeout)
            if setter and self.mode=='timeout':raise subprocess.TimeoutExpired(args,timeout)
            if setter and self.mode=='interrupt':raise InterruptedError('synthetic cancellation')
            if setter and self.mode=='nonzero':proc.returncode=7;return 7
            if not setter and self.mode=='read_timeout':raise subprocess.TimeoutExpired(args,timeout)
            if not setter:kwargs['stdout'].write(self.read_value.encode());kwargs['stdout'].flush()
            proc.returncode=0
        proc.wait=wait;return proc
    def stop(self,proc,row):
        if proc.returncode is None:proc.returncode=-15
        row['owned_group_absent']=True;row['cleanup_observation']={'last_probe':{'leader_reaped':True,'group':'ABSENT'}}
        if len(row['args'])==6:
            if self.closure_fault=='group':row['owned_group_absent']=False
            elif self.closure_fault=='leader':row['cleanup_observation']['last_probe']['leader_reaped']=False
            elif self.closure_fault=='probe':row['cleanup_observation']['last_probe']['group']='UNKNOWN'
            elif self.closure_fault=='secondary':row['secondary_errors']={'final_persist':{'exception_type':'OSError'}}
            elif self.closure_fault=='cleanup':row['cleanup_error']='synthetic'
            if self.after_set:self.after_set()
    def invoke(self):return self.m.configure_package_ax5(self.run,self.resources,self.uid,self.l)
    def test_timeout_closed_then_exact_readback_preserves_scans_error_and_budget(self):
        self.assertEqual(self.invoke(),self.l.AX5)
        self.assertEqual(len(self.calls),2);self.assertEqual(self.scans,[256,256])
        self.assertEqual(self.run.end,560);self.assertEqual(self.run.start,0)
        self.assertGreaterEqual(self.run.remaining(),304)
        self.assertIn('TimeoutExpired',self.run.meta['commands'][0]['command_error'])
        self.assertTrue(self.run.meta['ax5_postcondition']['setter_timed_out'])
    def test_normal_setter_uses_the_same_single_readback(self):
        self.mode='success';self.assertEqual(self.invoke(),self.l.AX5)
        self.assertEqual(len(self.calls),2);self.assertEqual(self.scans,[256,256])
        self.assertFalse(self.run.meta['ax5_postcondition']['setter_timed_out'])
    def test_unknown_group_leader_secondary_and_cleanup_never_read(self):
        for fault in ('group','leader','probe','secondary','cleanup'):
            with self.subTest(fault=fault):
                self.calls.clear();self.scans.clear();self.clock[0]=50;self.run.meta['commands']=[];self.closure_fault=fault
                with self.assertRaises(subprocess.TimeoutExpired):self.invoke()
                self.assertEqual(len(self.calls),1);self.assertEqual(self.run.end,560)
    def test_nonzero_cancellation_and_readback_failure_remain_fatal(self):
        for mode,count in (('nonzero',1),('interrupt',1),('read_timeout',2)):
            with self.subTest(mode=mode):
                self.calls.clear();self.scans.clear();self.clock[0]=50;self.run.meta['commands']=[];self.mode=mode
                with self.assertRaises((RuntimeError,InterruptedError,subprocess.TimeoutExpired)):self.invoke()
                self.assertEqual(len(self.calls),count);self.assertEqual(self.run.end,560)
    def test_wrong_readback_and_changed_owner_or_directory_fail(self):
        self.read_value='large'
        with self.assertRaises(AssertionError):self.invoke()
        self.assertEqual(self.run.meta['ax5_postcondition']['readback'],'large')
        for fault in ('uuid','directory'):
            with self.subTest(fault=fault):
                self.calls.clear();self.scans.clear();self.clock[0]=50;self.run.meta['commands']=[];self.run.meta['owned_uuid']=self.uid
                def changed():
                    if fault=='uuid':self.run.meta['owned_uuid']='different-owner'
                    else:self.device.rename(self.device.with_name('old-device'));self.device.mkdir()
                self.after_set=changed
                with self.assertRaises(AssertionError):self.invoke()
                self.assertEqual(len(self.calls),1);self.assertEqual(self.run.end,560)
    def test_symlink_device_is_rejected_before_any_child(self):
        self.device.rmdir();self.device.symlink_to(self.root,target_is_directory=True)
        with self.assertRaises(AssertionError):self.invoke()
        self.assertEqual(self.calls,[])
    def test_original_startup_clips_setter_and_blocks_readback_when_reserve_spent(self):
        self.clock[0]=200
        with self.assertRaises(subprocess.TimeoutExpired):self.invoke()
        self.assertEqual(len(self.calls),1);self.assertEqual(self.clock[0],252)
        self.assertEqual(self.run.meta['commands'][0]['timeout_seconds'],52)
        self.assertEqual(self.run.end,560);self.assertEqual(self.run.start,0)
    def test_blocking_scan_persist_or_open_cannot_start_late_readback(self):
        original_open=Path.open
        for stage in ('scan','persist','open'):
            with self.subTest(stage=stage):
                self.calls.clear();self.scans.clear();self.clock[0]=50;self.run.meta['commands']=[]
                self.before_read_scan=(lambda:self.clock.__setitem__(0,256)) if stage=='scan' else None
                def persisted():
                    if stage=='persist' and self.run.meta['commands'][-1]['args'][-1]=='content_size':self.clock[0]=252
                self.run.persist=persisted
                def opened(path,*args,**kwargs):
                    stream=original_open(path,*args,**kwargs)
                    if stage=='open' and path.name=='ax5-readback.txt':self.clock[0]=252
                    return stream
                with mock.patch.object(Path,'open',opened):
                    with self.assertRaises((AssertionError,TimeoutError)):self.invoke()
                self.assertEqual(len(self.calls),1);self.assertEqual(self.run.end,560);self.assertEqual(self.run.start,0)

if __name__=='__main__':unittest.main()
