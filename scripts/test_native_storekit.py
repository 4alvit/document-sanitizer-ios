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

if __name__=='__main__':unittest.main()
