"""Pure binding/admission controls for the one native payment command; no native/network."""
import contextlib,datetime as dt,hashlib,importlib.util,io,json,os,signal,subprocess,tempfile,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
ROOT=Path(__file__).resolve().parents[1]
DRIVER=Path(__file__).with_name('check-native-storekit.py')
MODULES=ROOT/'scripts/release_smoke'

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def jobs(now,elapsed=600):
    return {'total_count':1,'jobs':[{'id':7,'name':'macOS core, independent export corpus, iOS build','run_id':123,'run_attempt':1,'head_sha':'a'*40,'status':'in_progress','runner_id':55,'runner_name':'fixture','labels':['macos-15'],'started_at':(now-dt.timedelta(seconds=elapsed)).isoformat()}]}

class NativeStoreKitBindingTests(unittest.TestCase):
    def setUp(self):self.m=load('native_storekit_test',DRIVER);self.now=dt.datetime.now(dt.timezone.utc)
    def test_eight_existing_cases_share_one_unchanged_bounded_command(self):
        plan=self.m.validate_test_plan(json.loads((ROOT/'CleanSend.xctestplan').read_bytes()))
        self.assertEqual(len(plan['cases']),8);self.assertEqual(plan['maximum_case_seconds'],180);self.assertEqual(plan['outer_seconds'],300)
        args=self.m.test_arguments('A09F18F8-31EF-432D-A426-0197E73D75E8',Path('/fixture/result.xcresult'))
        self.assertEqual(args[:2],['xcodebuild','test-without-building'])
        self.assertEqual([a for a in args if a.startswith('-only-testing:')],['-only-testing:CleanSendTests/ProStoreTests'])
        self.assertEqual(args[args.index('-maximum-test-execution-time-allowance')+1],'180')
        self.assertEqual(args[args.index('-parallel-testing-enabled')+1],'NO')
    def test_exact_identity_set_and_no_skips_required(self):
        data={'nodes':[{'nodeType':'Test Case','nodeIdentifier':name+'()','result':'Passed'} for name in sorted(self.m.CASES)]}
        self.assertEqual(self.m.accepted_cases(data),sorted(self.m.CASES))
        for replacement in ('Skipped','Failed'):
            altered=json.loads(json.dumps(data));altered['nodes'][0]['result']=replacement
            with self.assertRaises(AssertionError):self.m.accepted_cases(altered)
        data['nodes'][0]=data['nodes'][1]
        with self.assertRaises(AssertionError):self.m.accepted_cases(data)
    def test_job_time_reserves_original_native_cleanup_and_upload(self):
        accepted=self.m.admit_job(jobs(self.now,840),'123','1','a'*40,self.now,780)
        self.assertEqual(accepted['remaining_job_seconds'],960)
        with self.assertRaises(AssertionError):self.m.admit_job(jobs(self.now,841),'123','1','a'*40,self.now,780)
        with self.assertRaises(AssertionError):self.m.admit_job(jobs(self.now,-1),'123','1','a'*40,self.now,780)
    def test_wrong_head_attempt_runner_and_plan_fail_closed(self):
        for key,value in (('head_sha','b'*40),('run_attempt',2),('labels',['macos-14'])):
            data=jobs(self.now);data['jobs'][0][key]=value
            with self.assertRaises(AssertionError):self.m.admit_job(data,'123','1','a'*40,self.now,780)
        plan=json.loads((ROOT/'CleanSend.xctestplan').read_bytes());plan['defaultOptions']['maximumTestExecutionTimeAllowance']=240
        with self.assertRaises(AssertionError):self.m.validate_test_plan(plan)
    def test_actual_context_preparation_does_one_metadata_read_and_drops_tokens(self):
        with tempfile.TemporaryDirectory(prefix='redact-payment-bind-') as temp:
            root=Path(temp).resolve();calls=[];window=load('native_window_fixture',MODULES/'window.py')
            class FakeTransport:
                def __init__(self,*_):self.report={'job_metadata':{'cleanup_confirmed':True}}
                @contextlib.contextmanager
                def command(inner,kind,limit,cap,argv,env):
                    calls.append((kind,limit,cap,argv(None)));yield io.BytesIO(json.dumps(jobs(self.now)).encode())
            transport=SimpleNamespace(Transport=FakeTransport,GH='/fixture/gh',environment=lambda *_:{})
            env={'GITHUB_ACTIONS':'true','RUNNER_OS':'macOS','GITHUB_EVENT_NAME':'pull_request','GITHUB_REPOSITORY':self.m.REPO,'GITHUB_RUN_ID':'123','GITHUB_RUN_ATTEMPT':'1','EXPECTED_HEAD_SHA':'a'*40,'GITHUB_SHA':'b'*40,'GH_TOKEN':'fixture-secret','GITHUB_TOKEN':'other-secret'}
            with mock.patch.dict(os.environ,env),mock.patch.object(self.m,'ROOT',root),mock.patch.object(self.m,'load',side_effect=lambda name:window if name=='window' else transport),mock.patch.object(self.m.shutil,'disk_usage',return_value=SimpleNamespace(free=100*2**30)),mock.patch.object(subprocess,'Popen',side_effect=AssertionError('real process forbidden')):
                started=time.monotonic();path,context=self.m.prepare_context(started)
                self.assertNotIn('GH_TOKEN',os.environ);self.assertNotIn('GITHUB_TOKEN',os.environ)
                self.assertEqual(len(calls),1);self.assertEqual(calls[0][:3],('job_metadata',12,1024*1024))
                os.environ['NATIVE_STOREKIT_CONTEXT_SHA']=hashlib.sha256(path.read_bytes()).hexdigest()
                self.assertEqual(self.m.validate_context(path,started),context)
                self.assertEqual(context['case_identities'],sorted(self.m.CASES))
                self.assertNotIn('fixture-secret',path.read_text())
                self.assertNotIn('other-secret',(path.parent/'admission.json').read_text())

    def test_actual_supervisor_timeout_keeps_child_ownership_and_cleanup_obligation(self):
        for correct_parent in (True,False):
            with self.subTest(correct_parent=correct_parent),tempfile.TemporaryDirectory(prefix='redact-payment-stop-') as temp:
                scope=Path(temp).resolve();self.m.SCOPE=scope;self.m.OWNED_ROOT=scope
                context=scope/'context.json';context.write_bytes(b'{}')
                lifecycle=load('native_cleanup_fixture',MODULES/'lifecycle.py')
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
                    self.assertNotIn('GH_TOKEN',kwargs['env']);self.assertNotIn('GITHUB_TOKEN',kwargs['env'])
                    (scope/'metadata.json').write_text(json.dumps({'owner_worker_pid':500,'owned_device_name':'fixture-owned-device','commands':[{'owned_process_group':700,'args':['xcodebuild'],'owned_group_absent':False}]}))
                    return process
                aggregate=self.m.aggregate_command_groups
                with mock.patch.object(self.m,'load',return_value=lifecycle),mock.patch.object(subprocess,'Popen',side_effect=spawn),mock.patch.object(self.m.Resources,'check',side_effect=AssertionError('injected allocation floor')),mock.patch.object(self.m,'await_cleanup_ack',side_effect=subprocess.TimeoutExpired('fixture-worker',3)),mock.patch.object(subprocess,'check_output',return_value='500\n' if correct_parent else '999\n') as parent_lookup,mock.patch.object(os,'getpgid',return_value=700),mock.patch.object(os,'killpg',side_effect=killpg),mock.patch.object(lifecycle,'stop_group',side_effect=lambda proc,row:row.update(owned_group_absent=True)),mock.patch.object(self.m,'aggregate_command_groups',side_effect=lambda meta,start:aggregate(meta,start,probe=killpg)),mock.patch.object(self.m,'terminal_stdout',return_value=True):
                    self.assertEqual(self.m.supervise(context,{},time.monotonic()),1)
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

class NativeStartupBudgetTests(unittest.TestCase):
    def setUp(self):
        self.m=load('native_budget_driver',DRIVER)
        self.l=load('native_budget_lifecycle',MODULES/'lifecycle.py')
        self.clock=[183.0];self.start=100.0
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.l.OUT=Path(self.temp.name).resolve();self.l.ROOT=self.l.OUT
        self.clock_patch=mock.patch.object(time,'monotonic',side_effect=lambda:self.clock[0]);self.clock_patch.start();self.addCleanup(self.clock_patch.stop)
        self.run=self.l.Run();self.run.start=self.start;self.run.persist=lambda:None
        self.phases=[]
        def check(phase):
            self.phases.append(phase)
            assert self.clock[0]<self.start+phase,'original phase deadline'
        self.resources=SimpleNamespace(check=check)
    def test_actual_install_command_uses_remaining_original_phase_once(self):
        proc=SimpleNamespace(pid=77,returncode=None)
        def wait(timeout):
            self.assertEqual(timeout,109);self.clock[0]+=10;proc.returncode=0
        proc.wait=wait
        with mock.patch.object(subprocess,'Popen',return_value=proc) as spawn,mock.patch.object(self.l,'stop_group',side_effect=lambda p,row:row.update(owned_group_absent=True)):
            self.assertEqual(self.m.install_once(self.run,self.resources,'owned','/fixture/app'),0)
        self.assertEqual(spawn.call_count,1);self.assertEqual(self.run.start,100);self.assertEqual(self.run.end,560)
        self.assertEqual(self.run.meta['commands'][0]['timeout_seconds'],109)
        self.assertEqual(self.phases,[196,196])
    def test_install_timeout_preserves_closure_and_original_cleanup_clock(self):
        proc=SimpleNamespace(pid=77,returncode=None)
        proc.wait=lambda **_:(_ for _ in ()).throw(subprocess.TimeoutExpired('install',109))
        def close(p,row):p.returncode=-15;row['owned_group_absent']=True
        with mock.patch.object(subprocess,'Popen',return_value=proc) as spawn,mock.patch.object(self.l,'stop_group',side_effect=close):
            with self.assertRaises(subprocess.TimeoutExpired):self.m.install_once(self.run,self.resources,'owned','/fixture/app')
        self.assertEqual(spawn.call_count,1);self.assertEqual(self.run.start,100);self.assertEqual(self.run.end,560)
        self.assertTrue(self.run.meta['commands'][0]['owned_group_absent'])
        self.assertEqual(self.run.meta['commands'][0]['returncode'],-15)
        self.assertEqual(self.l.CLEANUP_END,660)
    def test_late_install_does_not_spawn_and_does_not_reset_clock(self):
        self.clock[0]=292
        with mock.patch.object(subprocess,'Popen',side_effect=AssertionError('native forbidden')) as spawn:
            with self.assertRaises(TimeoutError):self.m.install_once(self.run,self.resources,'owned','/fixture/app')
        spawn.assert_not_called();self.assertEqual(self.run.start,100);self.assertEqual(self.run.end,560)
    def test_phase_never_extends_an_earlier_deadline_and_restores_after_failure(self):
        self.run.end=150;self.clock[0]=249
        with self.assertRaises(AssertionError):
            with self.m.work_phase(self.run,self.resources,196):
                self.assertEqual(self.run.end,150);self.clock[0]=250
        self.assertEqual(self.run.end,150);self.assertEqual(self.run.start,100)
    def test_before_inventory_checks_during_and_after_hashing(self):
        self.run.end=226;self.clock[0]=325
        def inventory(path,budget,check):
            check();self.clock[0]=326
            return {'hash':'unchanged'}
        with self.assertRaises(AssertionError):self.m.phase_payload_inventory(self.run,self.resources,SimpleNamespace(payload_inventory=inventory),None,'/fixture/app')
        self.assertEqual(self.phases,[226,226,226])
    def test_actual_resource_scan_respects_phase_after_each_stat(self):
        self.clock[0]=325;self.m.SCOPE=Path('/fixture');self.m.OWNED_ROOT=self.m.SCOPE
        resources=self.m.Resources(self.start)
        def late_stat(path):
            self.clock[0]=326
            return SimpleNamespace(st_blocks=0,st_mode=0o040700)
        with mock.patch.object(self.m.shutil,'disk_usage',return_value=SimpleNamespace(free=32*2**30)),mock.patch.object(os,'walk',return_value=[('/fixture',[],[])]),mock.patch.object(Path,'lstat',late_stat):
            with self.assertRaisesRegex(AssertionError,'owned stat deadline'):resources.check(226)
    def test_test_budget_retains300_body4_stop30_final_and_rejects_late_admission(self):
        self.clock[0]=326
        self.assertEqual(self.m.native_test_end(self.run,self.clock[0]),626)
        self.assertEqual(self.m.TEST_STOP_END-self.m.TEST_BODY_END,4)
        self.assertEqual(self.m.FINAL_VERIFY_END-self.m.TEST_STOP_END,30)
        self.clock[0]=326.001
        with self.assertRaises(AssertionError):self.m.native_test_end(self.run,self.clock[0])
        self.assertEqual(self.run.start,100)
    def test_final_inventory_has_original560_deadline(self):
        self.run.end=560;self.clock[0]=659
        def inventory(path,budget,check):check();self.clock[0]=660;return {}
        with self.assertRaises(AssertionError):self.m.phase_payload_inventory(self.run,self.resources,SimpleNamespace(payload_inventory=inventory),None,'/fixture/app')
        self.assertEqual(self.phases,[560,560,560])

class InstalledInventoryReceiptTests(unittest.TestCase):
    def setUp(self):
        self.m=load('native_inventory_receipt',DRIVER)
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name).resolve()/'installed-before.json'
        self.clock=[100.0];self.run=SimpleNamespace(start=100.0,end=226)
        self.patch=mock.patch.object(time,'monotonic',side_effect=lambda:self.clock[0]);self.patch.start();self.addCleanup(self.patch.stop)
        self.resources=SimpleNamespace(check=lambda phase:self.assertLess(self.clock[0],self.run.start+phase))
    def test_mismatch_is_persisted_then_rejected_with_sorted_exact_changes(self):
        expected={'.':{'directory':True,'mode':'0755'},'remove':{'mode':'0644','sha256':'a'},'mode':{'mode':'0644','sha256':'b'},'hash':{'mode':'0644','sha256':'c'},'type':{'directory':True,'mode':'0755'}}
        actual={'.':expected['.'],'add':{'mode':'0644','sha256':'d'},'mode':{'mode':'0600','sha256':'b'},'hash':{'mode':'0644','sha256':'changed'},'type':{'mode':'0755','sha256':'e'}}
        with self.assertRaisesRegex(AssertionError,'inventory saved'):self.m.persist_installed_payload(self.run,self.resources,'/fixture/app',actual,expected,self.path)
        saved=json.loads(self.path.read_bytes());self.assertFalse(saved['exact_payload']);self.assertEqual(saved['files'],actual)
        self.assertEqual([r['path'] for r in saved['differences']],['add','hash','mode','remove','type'])
        rows={r['path']:r for r in saved['differences']}
        self.assertEqual(rows['add']['change'],'added');self.assertEqual(rows['remove']['change'],'missing')
        self.assertEqual(rows['mode']['fields'],['mode']);self.assertEqual(rows['hash']['fields'],['sha256']);self.assertIn('type',rows['type']['fields'])
        for name,row in rows.items():self.assertEqual(row['actual'],actual.get(name));self.assertEqual(row['expected'],expected.get(name))
    def test_exact_payload_still_saves_truthful_success(self):
        files={'.':{'directory':True,'mode':'0755'},'main':{'mode':'0755','sha256':'abc'}}
        saved=self.m.persist_installed_payload(self.run,self.resources,'/fixture/app',files,files,self.path)
        self.assertTrue(saved['exact_payload']);self.assertEqual(saved['differences'],[]);self.assertEqual(json.loads(self.path.read_bytes()),saved)
    def test_expired_phase_and_oversize_receipt_fail_before_write(self):
        self.clock[0]=326
        with self.assertRaises(AssertionError):self.m.persist_installed_payload(self.run,self.resources,'/fixture/app',{}, {},self.path)
        self.assertFalse(self.path.exists());self.clock[0]=100
        actual={'large':{'mode':'0644','sha256':'x'*(1024*1024)}}
        with self.assertRaises(AssertionError):self.m.persist_installed_payload(self.run,self.resources,'/fixture/app',actual,{},self.path)
        self.assertFalse(self.path.exists())
    def test_phase_expiring_during_serialization_never_opens_output(self):
        original=self.m.json.dumps
        def encode_then_expire(*args,**kwargs):
            raw=original(*args,**kwargs);self.clock[0]=self.run.start+self.run.end;return raw
        with mock.patch.object(self.m.json,'dumps',side_effect=encode_then_expire),mock.patch.object(Path,'open') as opened:
            with self.assertRaises(AssertionError):self.m.persist_installed_payload(self.run,self.resources,'/fixture/app',{}, {},self.path)
        opened.assert_not_called();self.assertFalse(self.path.exists())
    def test_existing_receipt_is_not_overwritten(self):
        self.path.write_bytes(b'original')
        with self.assertRaises(FileExistsError):self.m.persist_installed_payload(self.run,self.resources,'/fixture/app',{}, {},self.path)
        self.assertEqual(self.path.read_bytes(),b'original')

class InitialInstallModeTests(unittest.TestCase):
    # Retained iOS18.5 installed-host observation, with synthetic file contents/hashes.
    observed_paths=(
        'CleanSend.debug.dylib','Frameworks/Testing.framework/Testing',
        'Frameworks/XCTAutomationSupport.framework/XCTAutomationSupport',
        'Frameworks/XCTest.framework/XCTest','Frameworks/XCTestCore.framework/XCTestCore',
        'Frameworks/XCTestSupport.framework/XCTestSupport','Frameworks/XCUIAutomation.framework/XCUIAutomation',
        'Frameworks/XCUnit.framework/XCUnit','Frameworks/libXCTestBundleInject.dylib',
        'Frameworks/libXCTestSwiftSupport.dylib','PlugIns/CleanSendShare.appex/CleanSendShare.debug.dylib',
        'PlugIns/CleanSendShare.appex/__preview.dylib','PlugIns/CleanSendTests.xctest/CleanSendTests','__preview.dylib')
    def setUp(self):
        self.m=load('initial_install_modes',DRIVER)
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name).resolve()
        self.run=SimpleNamespace(start=time.monotonic(),end=226);self.resources=SimpleNamespace(check=lambda _:None)
        self.expected={name:{'mode':'0755','sha256':hashlib.sha256(name.encode()).hexdigest()} for name in self.observed_paths+('CleanSend','PlugIns/CleanSendShare.appex/CleanSendShare')}
        self.expected['.']={'mode':'0755','directory':True}
        self.expected['Frameworks']={'mode':'0755','directory':True}
        self.actual=json.loads(json.dumps(self.expected))
        for name in self.observed_paths:self.actual[name]['mode']='0644'
    def save(self,name,files,expected,*,initial=False):
        return self.m.persist_installed_payload(self.run,self.resources,'/fixture/app',files,expected,self.root/name,initial_install=initial)
    def test_complete_observed_transition_keeps_raw_result_and_exact_later_baseline(self):
        before=self.save('before.json',self.actual,self.expected,initial=True)
        self.assertFalse(before['exact_payload']);self.assertTrue(before['accepted_payload'])
        self.assertEqual(len(before['accepted_install_transitions']),14)
        self.assertEqual({row['path'] for row in before['accepted_install_transitions']},set(self.observed_paths))
        self.assertEqual(before['files'],self.actual)
        for name in ('during.json','after.json'):
            result=self.save(name,self.actual,before['files'])
            self.assertTrue(result['exact_payload']);self.assertEqual(result['accepted_install_transitions'],[])
        self.assertTrue(all(self.expected[name]['mode']=='0755' for name in self.observed_paths))
    def test_unknown_content_type_path_or_mode_remains_fatal_and_is_recorded(self):
        first=self.observed_paths[0]
        variants={
            'changed-hash':lambda data:data[first].update(sha256='0'*64),
            'wrong-mode':lambda data:data[first].update(mode='0600'),
            'directory':lambda data:data[first].update(directory=True),
            'unknown-field':lambda data:data[first].update(extra=True),
            'added':lambda data:data.update(extra={'mode':'0644','sha256':'0'*64}),
            'missing':lambda data:data.pop(first),
            'main-executable':lambda data:data['CleanSend'].update(mode='0644'),
            'extension-executable':lambda data:data['PlugIns/CleanSendShare.appex/CleanSendShare'].update(mode='0644'),
            'directory-mode':lambda data:data['Frameworks'].update(mode='0700'),
        }
        for name,mutate in variants.items():
            with self.subTest(name=name):
                data=json.loads(json.dumps(self.actual));mutate(data)
                with self.assertRaisesRegex(AssertionError,'bounded inventory saved'):
                    self.save(name+'.json',data,self.expected,initial=True)
                saved=json.loads((self.root/(name+'.json')).read_bytes())
                self.assertFalse(saved['accepted_payload']);self.assertEqual(saved['accepted_install_transitions'],[])
                self.assertEqual(saved['files'],data)
    def test_partial_transition_is_not_general_mode_normalization(self):
        partial=json.loads(json.dumps(self.actual));partial[self.observed_paths[0]]['mode']='0755'
        with self.assertRaises(AssertionError):self.save('partial.json',partial,self.expected,initial=True)
        exact=self.save('unchanged.json',self.expected,self.expected,initial=True)
        self.assertTrue(exact['exact_payload']);self.assertEqual(exact['accepted_install_transitions'],[])
    def test_later_mode_or_hash_change_cannot_reuse_install_exception(self):
        for index,change in enumerate(({'mode':'0755'},{'sha256':'0'*64})):
            data=json.loads(json.dumps(self.actual));data[self.observed_paths[0]].update(change)
            with self.assertRaises(AssertionError):self.save(str(index)+'.json',data,self.actual)
        with self.assertRaises(AssertionError):self.save('not-initial.json',self.actual,self.expected)

if __name__=='__main__':unittest.main()
